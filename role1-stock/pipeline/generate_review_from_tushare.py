#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""严格对齐模板字段顺序的每日复盘生成器。"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import os
import pickle
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import chinadata.ca_data as ts
import chinamindata.min as tss

from _paths import CACHE_DIR, KNOWLEDGE_DIR, REVIEW_DIR

PROFILE_ENABLED = False
CACHE_ENABLED = True
PROFILE_ROWS: List[Dict[str, object]] = []
CACHE_ROOT = CACHE_DIR / ".review_api_cache"


def _normalize_cache_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_cache_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize_cache_value(v) for k, v in sorted(value.items())}
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _record_profile(name: str, elapsed_s: float, category: str, extra: Optional[dict] = None) -> None:
    if not PROFILE_ENABLED:
        return
    row: Dict[str, object] = {
        "name": name,
        "category": category,
        "elapsed_s": round(float(elapsed_s), 6),
    }
    if extra:
        for k, v in extra.items():
            row[str(k)] = _normalize_cache_value(v)
    PROFILE_ROWS.append(row)


def _profiled_function(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not PROFILE_ENABLED:
            return func(*args, **kwargs)
        started = time.perf_counter()
        ok = False
        try:
            result = func(*args, **kwargs)
            ok = True
            return result
        finally:
            _record_profile(
                name=func.__name__,
                elapsed_s=time.perf_counter() - started,
                category="function",
                extra={"ok": ok},
            )

    return wrapper


def _timed_call(name: str, fn, category: str = "block", extra: Optional[dict] = None):
    started = time.perf_counter()
    ok = False
    try:
        result = fn()
        ok = True
        return result
    finally:
        payload = dict(extra or {})
        payload["ok"] = ok
        _record_profile(name=name, elapsed_s=time.perf_counter() - started, category=category, extra=payload)


def _cache_file_path(namespace: str, params: dict) -> Path:
    raw = json.dumps(
        {"namespace": namespace, "params": _normalize_cache_value(params)},
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    safe_ns = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace)
    return CACHE_ROOT / f"{safe_ns}_{digest}.pkl"


def _ensure_frame(value):
    """统一把异常返回值降级为空 DataFrame，避免字符串缓存污染主流程。"""
    if isinstance(value, pd.DataFrame):
        return value
    return pd.DataFrame()


def _cached_frame(namespace: str, fetch_fn, **params):
    cache_path = _cache_file_path(namespace, params)
    if CACHE_ENABLED:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            started = time.perf_counter()
            with open(cache_path, "rb") as f:
                payload = pickle.load(f)
            _record_profile(
                name=namespace,
                elapsed_s=time.perf_counter() - started,
                category="cache_hit",
                extra={"path": str(cache_path), **params},
            )
            cached_value = payload.get("value")
            if isinstance(cached_value, pd.DataFrame):
                return cached_value
            try:
                cache_path.unlink()
            except OSError:
                pass
    result = _ensure_frame(_timed_call(namespace, fetch_fn, category="api", extra={"cache": "miss", **params}))
    if CACHE_ENABLED:
        with open(cache_path, "wb") as f:
            pickle.dump({"value": result}, f)
        _record_profile(name=namespace, elapsed_s=0.0, category="cache_write", extra={"path": str(cache_path), **params})
    return result


def _fetch_daily_pct(pro, trade_date: str) -> pd.DataFrame:
    return _cached_frame(
        "pro.daily.pct",
        lambda: pro.daily(trade_date=trade_date, fields="ts_code,trade_date,pct_chg"),
        trade_date=trade_date,
        fields="ts_code,trade_date,pct_chg",
    )


def _fetch_daily_market(pro, trade_date: str) -> pd.DataFrame:
    return _cached_frame(
        "pro.daily.market",
        lambda: pro.daily(trade_date=trade_date, fields="ts_code,trade_date,pct_chg,amount"),
        trade_date=trade_date,
        fields="ts_code,trade_date,pct_chg,amount",
    )


def _fetch_daily_pct_fresh(trade_date: str) -> pd.DataFrame:
    """
    用新的 pro_api 会话抓取单日窗口涨幅数据。
    实测新交易日放在主流程复用同一个 pro 会话时可能卡住，而独立会话通常能正常返回。
    """
    fresh_pro = _timed_call("ts.pro_api.daily", ts.pro_api, category="api")
    return _cached_frame(
        "pro.daily.pct",
        lambda: fresh_pro.daily(trade_date=trade_date, fields="ts_code,trade_date,pct_chg"),
        trade_date=trade_date,
        fields="ts_code,trade_date,pct_chg",
    )


def _load_late_stage_data(trade_date: str, next_end: str) -> Dict[str, pd.DataFrame]:
    """
    后段基础数据稳定加载：
    - 缓存命中：直接从本地读取
    - 缓存缺失：用新的 API 会话顺序抓取

    说明：实测把这些请求放到线程池并共享 API 会话时，个别日期会出现长时间挂住；
    这里优先保证稳定完成，不牺牲数据准确性。
    """
    results: Dict[str, pd.DataFrame] = {}

    late_specs = [
        (
            "daily_basic",
            "pro.daily_basic",
            {"trade_date": trade_date, "fields": "ts_code,turnover_rate,amount"},
            lambda pro: pro.daily_basic(trade_date=trade_date, fields="ts_code,turnover_rate,amount"),
        ),
        (
            "top_list",
            "pro.top_list",
            {"trade_date": trade_date},
            lambda pro: pro.top_list(trade_date=trade_date),
        ),
        (
            "trade_cal",
            "pro.trade_cal",
            {"exchange": "SSE", "start_date": trade_date, "end_date": next_end},
            lambda pro: pro.trade_cal(exchange="SSE", start_date=trade_date, end_date=next_end),
        ),
    ]

    for result_key, namespace, params, fetcher in late_specs:
        cache_path = _cache_file_path(namespace, params)
        if cache_path.exists():
            with open(cache_path, "rb") as f:
                payload = pickle.load(f)
            results[result_key] = payload.get("value")
            _record_profile(name=namespace, elapsed_s=0.0, category="cache_hit", extra={"path": str(cache_path), **params})
            continue

        print(f"[DEBUG] 正在获取后段数据 {result_key} ...")
        fresh_pro = _timed_call(f"ts.pro_api.{result_key}", ts.pro_api, category="api")
        results[result_key] = _cached_frame(namespace, lambda fetcher=fetcher, pro=fresh_pro: fetcher(pro), **params)

    auction_params = {"trade_date": trade_date}
    auction_cache_path = _cache_file_path("pro_min.stk_auction", auction_params)
    if auction_cache_path.exists():
        with open(auction_cache_path, "rb") as f:
            payload = pickle.load(f)
        results["stk_auction"] = payload.get("value")
        _record_profile(
            name="pro_min.stk_auction",
            elapsed_s=0.0,
            category="cache_hit",
            extra={"path": str(auction_cache_path), **auction_params},
        )
    else:
        print(f"[DEBUG] 正在获取后段数据 stk_auction ...")
        fresh_pro_min = _timed_call("tss.pro_api.stk_auction", tss.pro_api, category="api")
        results["stk_auction"] = _cached_frame(
            "pro_min.stk_auction",
            lambda: fresh_pro_min.stk_auction(trade_date=trade_date),
            **auction_params,
        )

    return results


def _parallel_map(task_specs: List[Tuple[str, object]], max_workers: int = 5) -> Dict[str, object]:
    results: Dict[str, object] = {}
    if not task_specs:
        return results
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(func): key for key, func in task_specs}
        for future in as_completed(future_map):
            key = future_map[future]
            results[key] = future.result()
    return results


def _load_daily_window_frames(pro, dates: List[str]) -> Dict[str, pd.DataFrame]:
    """
    优先顺序：
    1. 命中磁盘缓存的日期直接读取
    2. 未命中的日期串行拉取并立即写缓存

    说明：实测 `pro.daily` 单次请求本身并不慢，但放在线程池里对新日期请求时存在不稳定卡住现象。
    为了保证首跑稳定性，这里对未缓存日期改为串行获取；已缓存日期仍走本地秒级读取。
    """
    frames: Dict[str, pd.DataFrame] = {}
    missing_dates: List[str] = []
    for d in dates:
        cache_path = _cache_file_path("pro.daily.pct", {"trade_date": d, "fields": "ts_code,trade_date,pct_chg"})
        if cache_path.exists():
            with open(cache_path, "rb") as f:
                payload = pickle.load(f)
            frames[d] = payload.get("value")
            _record_profile(
                name="pro.daily.pct",
                elapsed_s=0.0,
                category="cache_hit",
                extra={"path": str(cache_path), "trade_date": d, "fields": "ts_code,trade_date,pct_chg"},
            )
        else:
            missing_dates.append(d)

    for d in missing_dates:
        print(f"[DEBUG] 正在获取窗口日行情 {d} ...")
        frames[d] = _fetch_daily_pct_fresh(d)

    return frames


def _write_profile_report(trade_date: str) -> Optional[Path]:
    if not PROFILE_ENABLED or not PROFILE_ROWS:
        return None
    out_dir = CACHE_DIR / ".review_profile"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = out_dir / f"profile_events_{trade_date}_{timestamp}.csv"
    summary_path = out_dir / f"profile_summary_{trade_date}_{timestamp}.md"

    df = pd.DataFrame(PROFILE_ROWS)
    df.to_csv(raw_path, index=False, encoding="utf-8-sig")
    agg = (
        df.groupby(["category", "name"], dropna=False)
        .agg(
            call_count=("elapsed_s", "size"),
            total_s=("elapsed_s", "sum"),
            avg_s=("elapsed_s", "mean"),
            max_s=("elapsed_s", "max"),
        )
        .reset_index()
        .sort_values(["total_s", "max_s"], ascending=[False, False])
    )
    lines = [
        f"# generate_review_from_tushare 性能报告 {trade_date}",
        "",
        f"- 原始事件：`{raw_path.name}`",
        f"- 汇总时间：`{timestamp}`",
        f"- 缓存目录：`{CACHE_ROOT}`",
        "",
        "## Top 20 耗时项",
        "",
        "| 分类 | 名称 | 调用次数 | 总耗时(s) | 平均(s) | 最大单次(s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, row in agg.head(20).iterrows():
        lines.append(
            f"| {row['category']} | {row['name']} | {int(row['call_count'])} | "
            f"{float(row['total_s']):.3f} | {float(row['avg_s']):.3f} | {float(row['max_s']):.3f} |"
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("[PROFILE] Top 10 慢调用：")
    for _, row in agg.head(10).iterrows():
        print(
            f"[PROFILE] {row['category']:<10} {row['name']:<30} "
            f"count={int(row['call_count']):<4} total={float(row['total_s']):>8.3f}s "
            f"avg={float(row['avg_s']):>7.3f}s max={float(row['max_s']):>7.3f}s"
        )
    print(f"[PROFILE] 原始事件已写入: {raw_path}")
    print(f"[PROFILE] 汇总报告已写入: {summary_path}")
    return summary_path

# ─────────────────────────────────────────────────────────────────────────────
# AKShare 替代层
#
# chinadata 的 limit_list_d / kpl_list / top_list 当日收盘后约 1~2 小时才入库。
# 以下函数用 AKShare 封装的东方财富接口获取同等真实数据，字段对齐 chinadata 格式。
# 调用方：_load_limit / kpl_list / top_list 三处，chinadata 返回空时自动切换。
# ─────────────────────────────────────────────────────────────────────────────

def _code_to_ts(code: str) -> str:
    """东财6位代码 → tushare ts_code（000001 → 000001.SZ / 600001 → 600001.SH）"""
    c = str(code).strip().zfill(6)
    if c.startswith(("60", "68", "90")):
        return c + ".SH"
    if c.startswith(("00", "30", "20")):
        return c + ".SZ"
    if c.startswith(("43", "83", "87", "92")):
        return c + ".BJ"
    return c + ".SZ"


# 韭研异动 JSON：`pipeline/fetch_jiuyan_daily.py` 产出 `韭研异动_YYYY-MM-DD.json`
_JIUYAN_SKIP_PLATES = frozenset({"简图", "ST板块"})


def _jiuyan_em_prefixed_code_to_ts(code: object) -> Optional[str]:
    """韭研 JSON 代码字段：sh603950 / sz002384 → tushare ts_code。"""
    c = str(code or "").strip().lower()
    if len(c) < 8:
        return None
    prefix, digits = c[:2], c[2:]
    if prefix not in ("sh", "sz") or not digits.isdigit():
        return None
    return _code_to_ts(digits)


def _parse_jiuyan_limit_time_sec(t: object) -> Optional[int]:
    """解析「09:25:01」→ 当日秒数；无效则 None。"""
    if t is None:
        return None
    s = str(t).strip()
    if not s or s.lower() in ("none", "null", "—", "-"):
        return None
    parts = s.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
        return h * 3600 + m * 60 + sec
    except ValueError:
        return None


def _fmt_sec_hhmmss(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_delta_vs_first(delta_sec: int) -> str:
    """相对题材首封的时差（秒）→ 可读字符串。"""
    if delta_sec == 0:
        return "同步"
    sign = "+" if delta_sec > 0 else ""
    a = abs(delta_sec)
    return f"{sign}{a // 60}分{a % 60:02d}秒"


def _load_jiuyan_action_json(trade_date_h: str) -> Optional[List[dict]]:
    path = REVIEW_DIR / f"韭研异动_{trade_date_h}.json"
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _build_overlap_anchor_section(
    trade_date_h: str,
    zt_codes: set,
    top_concepts: List[Tuple[str, str, int]],
    theme_code_map: Dict[str, List[str]],
    zt_map: Dict[str, object],
) -> str:
    """
    双题材锚「证据表」：
    1) 韭研：同一 ts_code 出现在 ≥2 个韭研板块；
    2) 复盘 Top5 概念：同一 ts_code 同时命中 ≥2 个当日前排概念成分（缓解「公告单列 vs 概念双线」不一致）。
    供次日执行手册/速查做非盘中归因与预案（与 9:25 矛盾时以竞价为准）。
    """
    header = "### 3.4.1 双题材锚·证据表（韭研多板块 ∪ Top5概念交集）\n\n"
    items = _load_jiuyan_action_json(trade_date_h)
    notes: List[str] = []
    if not items:
        notes.append(
            f"> 未读取到 `outputs/review/韭研异动_{trade_date_h}.json`，"
            "「韭研板块·时间 / 首封」列为空；请先运行 `python pipeline/fetch_jiuyan_daily.py`（文件名日期与复盘日一致）。\n"
        )

    plate_rows: Dict[str, List[Tuple[str, Optional[int], str, str]]] = {}
    if items:
        for it in items:
            plate = str(it.get("板块") or "").strip()
            if plate in _JIUYAN_SKIP_PLATES:
                continue
            ts_c = _jiuyan_em_prefixed_code_to_ts(it.get("代码", ""))
            if not ts_c:
                continue
            name = str(it.get("名称") or "").strip()
            t_raw = it.get("涨停时间")
            t_disp = str(t_raw).strip() if t_raw is not None else "—"
            sec = _parse_jiuyan_limit_time_sec(t_raw)
            plate_rows.setdefault(plate, []).append((ts_c, sec, name, t_disp if t_disp else "—"))

    theme_first_sec: Dict[str, Optional[int]] = {}
    for pl, lst in plate_rows.items():
        secs = [s for _, s, _, _ in lst if s is not None]
        theme_first_sec[pl] = min(secs) if secs else None

    ts_plates: Dict[str, Dict[str, Tuple[Optional[int], str, str]]] = {}
    for pl, lst in plate_rows.items():
        for ts_c, sec, name, t_disp in lst:
            bucket = ts_plates.setdefault(ts_c, {})
            if pl not in bucket:
                bucket[pl] = (sec, name, t_disp)
            else:
                old_sec, old_name, old_t = bucket[pl]
                cand_secs = [x for x in (old_sec, sec) if x is not None]
                new_sec = min(cand_secs) if cand_secs else None
                bucket[pl] = (new_sec, name or old_name, t_disp if t_disp != "—" else old_t)

    top5_names = [str(name) for _cc, name, _cnt in top_concepts[:5] if name]
    theme_sets: Dict[str, frozenset] = {
        th: frozenset(str(c) for c in (theme_code_map.get(th) or []))
        for th in top5_names
    }
    concept_hits: Dict[str, List[str]] = {}
    for ts_c in zt_codes:
        hits = [th for th in top5_names if ts_c in theme_sets.get(th, frozenset())]
        if len(hits) >= 2:
            concept_hits[ts_c] = hits

    table_lines: List[str] = []
    for ts_c in sorted(zt_codes):
        jp = ts_plates.get(ts_c, {})
        ch = concept_hits.get(ts_c, [])
        if len(jp) < 2 and len(ch) < 2:
            continue
        zrow = zt_map.get(ts_c)
        name0 = ""
        if zrow is not None:
            try:
                name0 = str(zrow["name"])
            except Exception:
                name0 = ""
        if not name0 and jp:
            name0 = next(iter(jp.values()))[1]
        if not name0:
            name0 = "—"

        types: List[str] = []
        if len(jp) >= 2:
            types.append("韭研≥2板块")
        if len(ch) >= 2:
            types.append("Top5概念交集")
        type_s = " + ".join(types)

        col_parts: List[str] = []
        stock_secs: List[Tuple[int, str]] = []
        for pl in sorted(jp.keys()):
            sec, _nm, t_disp = jp[pl]
            col_parts.append(f"{pl}@{t_disp}")
            if sec is not None:
                stock_secs.append((sec, pl))
        jiuyan_disp = "；".join(col_parts) if col_parts else "—"
        top5_disp = "、".join(ch) if ch else "—"

        if stock_secs:
            msec = min(s for s, _ in stock_secs)
            first_plates = [pl for s, pl in stock_secs if s == msec]
            first_side = "、".join(first_plates) + f"（{_fmt_sec_hhmmss(msec)}）"
            st_sec = msec
        else:
            first_side = "—（韭研无有效涨停时间）"
            st_sec = None

        ref_parts: List[str] = []
        delta_parts: List[str] = []
        for pl in sorted(jp.keys()):
            tf = theme_first_sec.get(pl)
            if tf is not None:
                ref_parts.append(f"{pl}首封{_fmt_sec_hhmmss(tf)}")
            else:
                ref_parts.append(f"{pl}首封—")
            if st_sec is not None and tf is not None:
                delta_parts.append(f"{pl}{_fmt_delta_vs_first(st_sec - tf)}")
            else:
                delta_parts.append(f"{pl}—")
        ref_s = "；".join(ref_parts) if ref_parts else "—"
        dl_s = "；".join(delta_parts) if delta_parts else "—"

        if stock_secs:
            lead_sec = min(s for s, _ in stock_secs)
            main_side = "、".join(sorted({pl for s, pl in stock_secs if s == lead_sec}))
        elif ch:
            main_side = ch[0]
        else:
            main_side = "—"

        table_lines.append(
            "| **{n}** | `{c}` | {tp} | {ms} | {t5} | {jd} | {fs} | {rf} | {dl} |".format(
                n=name0,
                c=ts_c,
                tp=type_s,
                ms=main_side,
                t5=top5_disp,
                jd=jiuyan_disp,
                fs=first_side,
                rf=ref_s,
                dl=dl_s,
            )
        )

    if not table_lines:
        body = (
            "> 未发现双题材锚：**韭研多板块**与**Top5概念交集**均未命中当日涨停池标的（或数据不全）。\n\n"
        )
    else:
        body = (
            "> 数据来源：韭研 `韭研异动_{trade_date_h}.json`（如有）+ 当日 `limit_cpt_list` Top5 概念成分映射。**仅作复盘归因**；次日仍以 9:25 竞价与「非重叠宽度」为准。\n\n".replace(
                "{trade_date_h}", trade_date_h
            )
            + "| 股票 | ts_code | 重叠类型 | 建议主归因 | Top5概念同时命中 | 韭研板块·涨停时间 | 本股先涨停侧（韭研口径） | 各韭研板块首封 | 本股相对各板块首封 |\n"
            + "|:---:|---|---|---|---|---|---|---|---|\n"
            + "\n".join(table_lines)
            + "\n\n"
        )

    rules = (
        "> **双题材锚·次日预案（速查/执行手册强制）**\n"
        "> 1. **唯一主归因、唯一入链**：双题材票只允许按上表「建议主归因」进入**一条**完整链；另一条线最多在表外一句话备注，**不得**进入完整链、健康度验证或作为宽度确认票。\n"
        "> 2. **宽度不认双份**：重叠票不得单独证明两条主线都成立；某条线是否可接力，仍至少需要 **1 只非重叠票**在该线龙二/龙三/龙五中同步走强。\n"
        "> 3. 若主归因那条线的风标/龙头已被预案否决，另一条线只有在 **龙一强 + 非重叠跟风≥1 同步强** 时，才允许把该票当作表外观察补充；否则直接放弃，不做双线摇摆。\n\n"
    )
    return header + "".join(notes) + body + rules


def _ak_zt_pool(date: str) -> pd.DataFrame:
    """
    AKShare stock_zt_pool_em → 对齐 limit_list_d(limit_type='U') 字段。
    字段：ts_code, name, trade_date, limit_times, fd_amount, open_times, up_stat
    """
    try:
        import akshare as ak
        df = _cached_frame("ak.stock_zt_pool_em", lambda: ak.stock_zt_pool_em(date=date), date=date)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_code"] = df["代码"].astype(str).apply(_code_to_ts)
    df["name"] = df["名称"].astype(str)
    df["trade_date"] = date
    df["limit_times"] = pd.to_numeric(df.get("连板数", 1), errors="coerce").fillna(1).astype(int)
    df["fd_amount"] = pd.to_numeric(df.get("封板资金", 0), errors="coerce").fillna(0)
    df["open_times"] = pd.to_numeric(df.get("炸板次数", 0), errors="coerce").fillna(0).astype(int)
    df["up_stat"] = df.get("涨停统计", pd.Series([""] * len(df))).fillna("").astype(str)
    df["limit"] = "U"
    return df[["ts_code", "name", "trade_date", "limit_times", "fd_amount", "open_times", "up_stat", "limit"]]


def _ak_dt_pool(date: str) -> pd.DataFrame:
    """
    AKShare stock_zt_pool_dtgc_em → 对齐 limit_list_d(limit_type='D') 字段。
    """
    try:
        import akshare as ak
        df = _cached_frame("ak.stock_zt_pool_dtgc_em", lambda: ak.stock_zt_pool_dtgc_em(date=date), date=date)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_code"] = df["代码"].astype(str).apply(_code_to_ts)
    df["name"] = df["名称"].astype(str)
    df["trade_date"] = date
    df["limit_times"] = pd.to_numeric(df.get("连续跌停", 1), errors="coerce").fillna(1).astype(int)
    df["fd_amount"] = pd.to_numeric(df.get("封单资金", 0), errors="coerce").fillna(0)
    df["open_times"] = pd.to_numeric(df.get("开板次数", 0), errors="coerce").fillna(0).astype(int)
    df["up_stat"] = ""
    df["limit"] = "D"
    return df[["ts_code", "name", "trade_date", "limit_times", "fd_amount", "open_times", "up_stat", "limit"]]


def _ak_zb_pool(date: str) -> pd.DataFrame:
    """
    AKShare stock_zt_pool_zbgc_em → 对齐 limit_list_d(limit_type='Z') 字段。
    """
    try:
        import akshare as ak
        df = _cached_frame("ak.stock_zt_pool_zbgc_em", lambda: ak.stock_zt_pool_zbgc_em(date=date), date=date)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_code"] = df["代码"].astype(str).apply(_code_to_ts)
    df["name"] = df["名称"].astype(str)
    df["trade_date"] = date
    df["limit_times"] = 1
    df["fd_amount"] = 0.0
    df["open_times"] = pd.to_numeric(df.get("炸板次数", 0), errors="coerce").fillna(0).astype(int)
    df["up_stat"] = df.get("涨停统计", pd.Series([""] * len(df))).fillna("").astype(str)
    df["limit"] = "Z"
    return df[["ts_code", "name", "trade_date", "limit_times", "fd_amount", "open_times", "up_stat", "limit"]]


def _ak_kpl_list(date: str) -> pd.DataFrame:
    """
    AKShare stock_zt_pool_em → 对齐 kpl_list 字段（theme/lu_desc 用所属行业近似）。
    kpl_list 用途：提供 theme/lu_desc 供题材映射，以及 bid_amount 竞价成交额。
    """
    try:
        import akshare as ak
        df = _cached_frame("ak.stock_zt_pool_em.kpl", lambda: ak.stock_zt_pool_em(date=date), date=date)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_code"] = df["代码"].astype(str).apply(_code_to_ts)
    df["name"] = df["名称"].astype(str)
    df["trade_date"] = date
    # 用「所属行业」作为 theme/lu_desc（东财涨停池没有开盘啦的题材标签，但有行业）
    df["theme"] = df.get("所属行业", pd.Series([""] * len(df))).fillna("").astype(str)
    df["lu_desc"] = df["theme"]
    df["limit_order"] = pd.to_numeric(df.get("封板资金", 0), errors="coerce").fillna(0)
    df["pct_chg"] = pd.to_numeric(df.get("涨跌幅", 0), errors="coerce").fillna(0)
    return df[["ts_code", "name", "trade_date", "theme", "lu_desc", "limit_order", "pct_chg"]]


def _ak_top_list(date: str) -> pd.DataFrame:
    """
    AKShare stock_lhb_detail_em → 对齐 top_list 字段。
    字段：ts_code, name, trade_date, reason, net_buy
    """
    try:
        import akshare as ak
        df = _cached_frame(
            "ak.stock_lhb_detail_em",
            lambda: ak.stock_lhb_detail_em(start_date=date, end_date=date),
            start_date=date,
            end_date=date,
        )
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts_code"] = df["代码"].astype(str).apply(_code_to_ts)
    df["name"] = df["名称"].astype(str)
    df["trade_date"] = date
    df["reason"] = df.get("上榜原因", pd.Series([""] * len(df))).fillna("").astype(str)
    df["net_buy"] = pd.to_numeric(df.get("龙虎榜净买额", 0), errors="coerce").fillna(0)
    return df[["ts_code", "name", "trade_date", "reason", "net_buy"]]


def _ak_top_inst(ts_code: str, date: str) -> pd.DataFrame:
    """
    AKShare stock_lhb_stock_detail_em → 对齐 top_inst 字段（net_buy）。
    """
    try:
        import akshare as ak
        code = ts_code.split(".")[0]
        df_buy = _cached_frame(
            "ak.stock_lhb_stock_detail_em.buy",
            lambda: ak.stock_lhb_stock_detail_em(symbol=code, date=date, flag="买入"),
            symbol=code,
            date=date,
            flag="buy",
        )
        df_sell = _cached_frame(
            "ak.stock_lhb_stock_detail_em.sell",
            lambda: ak.stock_lhb_stock_detail_em(symbol=code, date=date, flag="卖出"),
            symbol=code,
            date=date,
            flag="sell",
        )
        buy = pd.to_numeric(df_buy.get("买入金额", pd.Series([0])), errors="coerce").fillna(0).sum() if df_buy is not None and not df_buy.empty else 0.0
        sell = pd.to_numeric(df_sell.get("卖出金额", pd.Series([0])), errors="coerce").fillna(0).sum() if df_sell is not None and not df_sell.empty else 0.0
        return pd.DataFrame([{"net_buy": buy - sell}])
    except Exception:
        return pd.DataFrame()

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"
TOKEN_MIN = "ne34e6697159de73c228e34379b510ec554"


def _safe_float(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v, default=0):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return default
        return int(float(v))
    except Exception:
        return default


def _fmt_pct(v: float) -> str:
    return f"{v:+.2f}%"


def _fmt_yi_from_thousand(v: float) -> str:
    return f"{_safe_float(v) / 100000:.2f}亿"


def _fd_yi(v: float) -> str:
    x = _safe_float(v)
    yi = x / 1e8 if abs(x) >= 1e7 else x / 10000
    return f"{yi:.2f}亿"


def _to_trade_date(s: str) -> str:
    s = s.replace("-", "").strip()
    datetime.strptime(s, "%Y%m%d")
    return s


def _is_excluded(ts_code: str, name: str) -> bool:
    c = str(ts_code or "")
    n = str(name or "")
    if "ST" in n.upper():
        return True
    if c.endswith(".BJ"):
        return True
    # 科创板与相关 68x（如 688/689）
    if c.startswith("68"):
        return True
    return False


def _parse_theme_cell(s: str) -> List[str]:
    if not isinstance(s, str):
        return []
    parts = re.split(r"[+|,，/、;；\s]+", s.strip())
    return [p for p in parts if p]


def _get_concept_cons_codes(pro, concept_code: str, trade_date: str) -> List[str]:
    """
    从概念代码取成分/关联股票代码。
    优先用 kpl_concept_cons（更贴近涨停概念体系），不行则回退 ths_member。
    返回 ts_code 列表（如 000001.SZ）。
    """
    concept_code = str(concept_code or "").strip()
    if not concept_code:
        return []
    df = None
    try:
        df = _cached_frame(
            "pro.kpl_concept_cons",
            lambda: pro.kpl_concept_cons(ts_code=concept_code, trade_date=trade_date),
            ts_code=concept_code,
            trade_date=trade_date,
        )
    except Exception:
        df = None
    if df is None or df.empty:
        try:
            df = _cached_frame(
                "pro.ths_member",
                lambda: pro.ths_member(ts_code=concept_code, fields="con_code"),
                ts_code=concept_code,
                fields="con_code",
            )
        except Exception:
            df = None
    if df is None or df.empty:
        return []
    for col in ("con_code", "ts_code"):
        if col in df.columns:
            codes = df[col].dropna().astype(str).tolist()
            return list(dict.fromkeys(codes))
    return []


def _upsert_emotion_calendar(
    calendar_csv_path: str,
    trade_date_h: str,
    emotion: str,
    sentence: str,
    trend: str,
) -> List[Tuple[str, str, str, str]]:
    cols = ["date", "emotion_node", "summary", "trend"]
    if os.path.exists(calendar_csv_path):
        try:
            df = pd.read_csv(calendar_csv_path, encoding="utf-8-sig")
        except Exception:
            df = pd.DataFrame(columns=cols)
    else:
        df = pd.DataFrame(columns=cols)

    for c in cols:
        if c not in df.columns:
            df[c] = ""

    # 同日期则覆盖，保证重复运行不会追加重复行
    df = df[df["date"].astype(str) != trade_date_h]
    df = pd.concat(
        [
            df,
            pd.DataFrame(
                [
                    {
                        "date": trade_date_h,
                        "emotion_node": emotion,
                        "summary": sentence,
                        "trend": trend,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    # 按日期排序并写回
    try:
        df["_d"] = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
        df = df.sort_values("_d").drop(columns=["_d"])
    except Exception:
        pass
    df.to_csv(calendar_csv_path, index=False, encoding="utf-8-sig")

    tail = df.tail(5).fillna("")
    rows = []
    for _, r in tail.iterrows():
        rows.append(
            (
                str(r.get("date", "")),
                str(r.get("emotion_node", "")),
                str(r.get("summary", "")),
                str(r.get("trend", "")),
            )
        )
    return rows


def _build_rotation_section(
    pro,
    past_5_days: List[str],
    trade_date: str,
    name_map: dict,
    theme_code_map: Dict[str, List[str]],
) -> str:
    """
    生成「近5日题材热力追踪」章节（Section 3.5）。
    供执行手册「轮动方向」板块直接引用。
    修复点：
      1. 热力趋势表全量输出（不再[:15]截断），退潮题材优先，活跃题材附后
      2. 龙头池概念映射缺失时，从 df_cpt_5d 提取历史概念代码，调 _get_concept_cons_codes() 补全成员股
    """
    if len(past_5_days) < 2:
        return "> 交易数据不足（少于2个交易日），无法生成轮动追踪。\n"

    start_d = past_5_days[0]

    # ── 1. 5日概念涨停统计（一次 API 拉全量）────────────────────────────────
    df_cpt_5d: Optional[pd.DataFrame] = None
    try:
        df_cpt_5d = _cached_frame(
            "pro.limit_cpt_list.range",
            lambda: pro.limit_cpt_list(start_date=start_d, end_date=trade_date),
            start_date=start_d,
            end_date=trade_date,
        )
    except Exception:
        pass
    if df_cpt_5d is None or df_cpt_5d.empty:
        return "> 概念涨停历史数据获取失败，轮动追踪暂无数据。\n"

    df_cpt_5d = df_cpt_5d[
        ~df_cpt_5d["name"].astype(str).str.contains("ST", case=False, na=False)
    ]
    cnt_col = (
        "up_nums" if "up_nums" in df_cpt_5d.columns
        else ("count" if "count" in df_cpt_5d.columns else None)
    )
    if cnt_col is None:
        return "> 概念涨停字段缺失，跳过轮动追踪。\n"
    df_cpt_5d["_cnt"] = pd.to_numeric(df_cpt_5d[cnt_col], errors="coerce").fillna(0).astype(int)

    # 构建两个映射：
    #   theme_daily:     theme_name -> {date: cnt}
    #   name_to_cpt_code: theme_name -> 最新出现的概念代码（用于后续查成员股）
    theme_daily: Dict[str, Dict[str, int]] = {}
    name_to_cpt_code: Dict[str, str] = {}
    for _, row in df_cpt_5d.iterrows():
        th = str(row.get("name", "")).strip()
        dt = str(row.get("trade_date", "")).strip()
        cpt_code = str(row.get("ts_code", "")).strip()
        if not th or dt not in past_5_days:
            continue
        cnt = int(row.get("_cnt", 0))
        if cnt > 0:
            theme_daily.setdefault(th, {})[dt] = cnt
        # 记录概念代码（覆盖更新，保留最近一次出现的）
        if cpt_code:
            name_to_cpt_code[th] = cpt_code

    # 过滤：5日内至少1天涨停数 ≥ 8
    theme_daily = {k: v for k, v in theme_daily.items() if max(v.values()) >= 8}
    if not theme_daily:
        return "> 5日内无显著热门题材（峰值涨停数均低于8只），轮动追踪暂无数据。\n"

    # ── 2. 阶段判断 ─────────────────────────────────────────────────────────
    @_profiled_function
    def _stage(cnts: List[int], peak_idx: int) -> str:
        today_cnt = cnts[-1]
        peak_cnt = cnts[peak_idx]
        days_from_peak = (len(cnts) - 1) - peak_idx
        if today_cnt >= peak_cnt * 0.8:
            return "高潮"
        if len(cnts) >= 2 and cnts[-1] > cnts[-2] and today_cnt >= 5:
            return "发酵"
        if days_from_peak >= 1:
            if today_cnt <= max(3, peak_cnt * 0.25):
                return "深度退潮"
            if today_cnt < peak_cnt * 0.6:
                return "退潮中"
        return "观察"

    theme_analysis: List[Tuple] = []
    for th, day_cnt in theme_daily.items():
        cnts = [day_cnt.get(d, 0) for d in past_5_days]
        peak_cnt = max(cnts)
        peak_idx = cnts.index(peak_cnt)
        today_cnt = cnts[-1]
        stage = _stage(cnts, peak_idx)
        trend = "↑" if len(cnts) >= 2 and cnts[-1] > cnts[-2] else (
            "↓" if len(cnts) >= 2 and cnts[-1] < cnts[-2] else "→"
        )
        theme_analysis.append((th, peak_idx, peak_cnt, today_cnt, stage, cnts, trend, past_5_days[peak_idx]))

    # 排序：退潮系（深度退潮/退潮中）按峰值降序在前，活跃系（发酵/高潮）按今日数降序在后
    @_profiled_function
    def _sort_key(item):
        th, peak_idx, peak_cnt, today_cnt, stage, cnts, trend, peak_day = item
        order = {"深度退潮": 0, "退潮中": 1, "观察": 2, "发酵": 3, "高潮": 4}
        return (order.get(stage, 5), -peak_cnt)

    theme_analysis.sort(key=_sort_key)

    # ── 3. 5日个股涨停明细（一次 API 拉全量）──────────────────────────────────
    df_zt_5d: Optional[pd.DataFrame] = None
    try:
        df_zt_5d = _cached_frame(
            "pro.limit_list_d.range",
            lambda: pro.limit_list_d(limit_type="U", start_date=start_d, end_date=trade_date),
            limit_type="U",
            start_date=start_d,
            end_date=trade_date,
        )
    except Exception:
        pass

    day_stock_map: Dict[str, Dict[str, dict]] = {}
    if df_zt_5d is not None and not df_zt_5d.empty:
        if "name" not in df_zt_5d.columns:
            df_zt_5d["name"] = df_zt_5d["ts_code"].map(name_map)
        df_zt_5d = df_zt_5d[
            ~df_zt_5d.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)
        ]
        for col, default in [("limit_times", 1), ("fd_amount", 0), ("open_times", 0)]:
            df_zt_5d[col] = pd.to_numeric(
                df_zt_5d.get(col, pd.Series([default] * len(df_zt_5d))),
                errors="coerce",
            ).fillna(default)
        df_zt_5d["limit_times"] = df_zt_5d["limit_times"].astype(int)
        df_zt_5d["open_times"] = df_zt_5d["open_times"].astype(int)
        df_zt_5d["up_stat"] = (
            df_zt_5d.get("up_stat", pd.Series([""] * len(df_zt_5d))).fillna("").astype(str)
        )
        for _, row in df_zt_5d.iterrows():
            d = str(row.get("trade_date", ""))
            code = str(row.get("ts_code", ""))
            if d in past_5_days:
                day_stock_map.setdefault(d, {})[code] = row.to_dict()

    # ── 4. 构建 Markdown ─────────────────────────────────────────────────────
    day_labels = []
    for i, d in enumerate(past_5_days):
        days_ago = len(past_5_days) - 1 - i
        d_label = f"{d[4:6]}/{d[6:]}"
        if days_ago == 0:
            day_labels.append(f"今日({d_label})")
        elif days_ago == 1:
            day_labels.append(f"昨日({d_label})")
        else:
            day_labels.append(f"D-{days_ago}({d_label})")

    stage_icon: Dict[str, str] = {
        "高潮": "🔥高潮",
        "发酵": "📈发酵",
        "退潮中": "⚠️退潮中",
        "深度退潮": "✅低吸窗口",
        "观察": "👀观察",
    }

    # ── 热力趋势表：全量输出，不截断 ──────────────────────────────────────────
    # 退潮阶段（深度退潮/退潮中）全部显示；观察/发酵/高潮各最多显示5条（给当前市场背景）
    retirement_rows = [x for x in theme_analysis if x[4] in ("深度退潮", "退潮中")]
    active_rows = [x for x in theme_analysis if x[4] not in ("深度退潮", "退潮中")][:5]
    display_rows = retirement_rows + active_rows

    hdr = " | ".join(day_labels)
    heatmap_lines = [
        f"| 题材 | {hdr} | 趋势 | 阶段 |",
        "|---|" + "|".join([":---:"] * len(past_5_days)) + "|:---:|:---:|",
    ]
    for th, peak_idx, peak_cnt, today_cnt, stage, cnts, trend, peak_day in display_rows:
        cells = []
        for i, c in enumerate(cnts):
            cell = f"**{c}**" if (i == peak_idx and c == peak_cnt and c > 0) else (str(c) if c > 0 else "—")
            cells.append(cell)
        heatmap_lines.append(
            f"| {th} | {' | '.join(cells)} | {trend} | {stage_icon.get(stage, stage)} |"
        )
    heatmap_md = "\n".join(heatmap_lines)

    # ── 退潮题材龙头池：优先用 theme_code_map，缺失时从概念代码查成员股 ─────
    dragon_sections: List[str] = []
    for th, peak_idx, peak_cnt, today_cnt, stage, cnts, trend, peak_day in retirement_rows:
        peak_day_stocks = day_stock_map.get(peak_day, {})
        if not peak_day_stocks:
            # 当天个股数据为空（可能该日无行情），跳过
            dragon_sections.append(
                f"\n**{th}**（峰值 {peak_cnt}只 · {peak_day} → 今日 {today_cnt}只 · {stage}）\n\n"
                f"> ⚠️ 峰值日 {peak_day} 个股明细数据缺失，请手动补充龙头信息。\n"
            )
            continue

        # ① 优先：今日 theme_code_map（适用于当前仍活跃的题材）
        theme_codes = theme_code_map.get(th, [])
        peak_stocks = [peak_day_stocks[c] for c in theme_codes if c in peak_day_stocks]

        # ② 回退：从 df_cpt_5d 取到的历史概念代码，查当日成员股
        if not peak_stocks:
            cpt_code = name_to_cpt_code.get(th, "")
            if cpt_code:
                try:
                    member_codes = _get_concept_cons_codes(pro, cpt_code, peak_day)
                    peak_stocks = [peak_day_stocks[c] for c in member_codes if c in peak_day_stocks]
                except Exception:
                    peak_stocks = []

        # ③ 最终兜底：若题材名能在个股行业字段中找到，则用行业匹配
        if not peak_stocks:
            for code, stock_data in peak_day_stocks.items():
                industry = str(stock_data.get("industry", ""))
                if th in industry or industry in th:
                    peak_stocks.append(stock_data)

        if not peak_stocks:
            dragon_sections.append(
                f"\n**{th}**（峰值 {peak_cnt}只 · {peak_day} → 今日 {today_cnt}只 · {stage}）\n\n"
                f"> ⚠️ 该题材概念成员映射未能匹配，建议手动查找龙头（峰值日：{peak_day}，涨停{peak_cnt}只）。\n"
            )
            continue

        peak_stocks.sort(
            key=lambda x: (_safe_int(x.get("limit_times", 1)), _safe_float(x.get("fd_amount", 0))),
            reverse=True,
        )
        peak_date_h = f"{peak_day[:4]}-{peak_day[4:6]}-{peak_day[6:]}"
        rows = [
            f"\n**{th}**（峰值 {peak_cnt}只 · {peak_date_h} → 今日 {today_cnt}只 · {stage}）\n",
            "| 顺位 | 股票 | 峰值板数 | 峰值封单 | 涨停历史 | 开板次数 |",
            "|:---:|---|:---:|---|---|:---:|",
        ]
        for rank, z in enumerate(peak_stocks[:5], 1):
            n = z.get("name", "")
            b = _safe_int(z.get("limit_times", 1))
            ot = _safe_int(z.get("open_times", 0))
            ot_s = f"开{ot}次" if ot > 0 else "✅未开板"
            fd = _fd_yi(z.get("fd_amount", 0))
            up_s = str(z.get("up_stat", "")).strip()
            up_s = up_s if up_s and up_s not in ("nan", "") else "—"
            rows.append(f"| 龙{rank} | **{n}** | {b}板 | {fd} | {up_s} | {ot_s} |")
        dragon_sections.append("\n".join(rows))

    dragon_md = (
        "\n".join(dragon_sections)
        if dragon_sections
        else "> 当前5日内无明显退潮题材（均处于高潮或发酵期），轮动低吸暂无参考。"
    )

    retire_cnt = len(retirement_rows)
    active_cnt = len(active_rows)
    return f"""#### 热力趋势表（退潮题材{retire_cnt}个·全量显示，当前活跃题材取前{active_cnt}个作背景参考）

{heatmap_md}

> 峰值数字**加粗**。✅低吸窗口 = 深度退潮，有资金记忆，等信号低吸；⚠️退潮中 = 刚开始退潮，观察为主；🔥/📈 = 当前活跃题材，参考背景用，不属于轮动低吸候选。

#### 退潮题材龙头池

{dragon_md}
"""


for _func_name in [
    "_ak_zt_pool",
    "_ak_dt_pool",
    "_ak_zb_pool",
    "_ak_kpl_list",
    "_ak_top_list",
    "_ak_top_inst",
    "_get_concept_cons_codes",
    "_upsert_emotion_calendar",
    "_build_rotation_section",
]:
    globals()[_func_name] = _profiled_function(globals()[_func_name])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", "--trade_date", dest="trade_date", default="20260305")
    parser.add_argument("--profile", action="store_true", help="开启函数/API 耗时统计")
    parser.add_argument("--no-cache", action="store_true", help="关闭 API 响应落盘缓存")
    args = parser.parse_args()
    global PROFILE_ENABLED, CACHE_ENABLED
    PROFILE_ENABLED = args.profile
    CACHE_ENABLED = not args.no_cache
    trade_date = _to_trade_date(args.trade_date)
    trade_date_h = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

    print(f"[DEBUG] 设置 token...")
    ts.set_token(TOKEN)
    tss.set_token(TOKEN_MIN)
    print(f"[DEBUG] 初始化 pro_api()...")
    pro = _timed_call("ts.pro_api", ts.pro_api, category="api")
    pro_min = _timed_call("tss.pro_api", tss.pro_api, category="api")
    print(f"[DEBUG] ✅ API 初始化完成")

    print(f"[DEBUG] 正在读取股票映射缓存...")
    df_sb = _cached_frame(
        "pro.stock_basic",
        lambda: pro.stock_basic(exchange="", list_status="L", fields="ts_code,name"),
        exchange="",
        list_status="L",
        fields="ts_code,name",
    )

    if df_sb is None:
        df_sb = pd.DataFrame(columns=["ts_code", "name"])
    name_map = dict(zip(df_sb.get("ts_code", []), df_sb.get("name", [])))

    def nm(code: str, fallback: str = "") -> str:
        return str(name_map.get(code, fallback if fallback else code))

    start_lookback = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=50)).strftime("%Y%m%d")
    print(f"[DEBUG] 正在获取指数历史数据 {start_lookback} → {trade_date}")
    idx_hist = _cached_frame(
        "pro.index_daily.range",
        lambda: pro.index_daily(ts_code="000001.SH", start_date=start_lookback, end_date=trade_date),
        ts_code="000001.SH",
        start_date=start_lookback,
        end_date=trade_date,
    )
    if idx_hist is None or idx_hist.empty:
        raise RuntimeError("无法获取指数数据")
    print(f"[DEBUG] ✅ 指数历史数据获取完成")
    idx_hist = idx_hist.sort_values("trade_date")
    tdays = idx_hist["trade_date"].tolist()
    if trade_date not in tdays:
        trade_date = tdays[-1]
        trade_date_h = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    t_idx = tdays.index(trade_date)
    prev_trade = tdays[t_idx - 1] if t_idx > 0 else trade_date
    past_5_days = tdays[max(0, t_idx - 4) : t_idx + 1]  # 含今日的最近5个交易日

    print(f"[DEBUG] 正在并行获取指数单日数据...")
    index_day_data = _parallel_map(
        [
            ("sh", lambda: _cached_frame(
                "pro.index_daily.day",
                lambda: pro.index_daily(ts_code="000001.SH", trade_date=trade_date),
                ts_code="000001.SH",
                trade_date=trade_date,
            )),
            ("sz", lambda: _cached_frame(
                "pro.index_daily.day",
                lambda: pro.index_daily(ts_code="399001.SZ", trade_date=trade_date),
                ts_code="399001.SZ",
                trade_date=trade_date,
            )),
            ("cyb", lambda: _cached_frame(
                "pro.index_daily.day",
                lambda: pro.index_daily(ts_code="399006.SZ", trade_date=trade_date),
                ts_code="399006.SZ",
                trade_date=trade_date,
            )),
            ("sh_prev", lambda: _cached_frame(
                "pro.index_daily.day",
                lambda: pro.index_daily(ts_code="000001.SH", trade_date=prev_trade),
                ts_code="000001.SH",
                trade_date=prev_trade,
            )),
        ],
        max_workers=4,
    )
    sh = index_day_data.get("sh")
    sz = index_day_data.get("sz")
    cyb = index_day_data.get("cyb")
    sh_prev = index_day_data.get("sh_prev")
    print(f"[DEBUG] ✅ 指数单日数据获取完成")
    sh_r = sh.iloc[0] if sh is not None and not sh.empty else {}
    sz_r = sz.iloc[0] if sz is not None and not sz.empty else {}
    cyb_r = cyb.iloc[0] if cyb is not None and not cyb.empty else {}
    sh_p = sh_prev.iloc[0] if sh_prev is not None and not sh_prev.empty else {}

    sh_open = _safe_float(sh_r.get("open"))
    sh_high = _safe_float(sh_r.get("high"))
    sh_low = _safe_float(sh_r.get("low"))
    sh_close = _safe_float(sh_r.get("close"))
    sh_pct = _safe_float(sh_r.get("pct_chg"))
    sh_amount = _safe_float(sh_r.get("amount"))
    sh_prev_amount = _safe_float(sh_p.get("amount"), sh_amount)
    amount_ratio = ((sh_amount - sh_prev_amount) / sh_prev_amount * 100) if sh_prev_amount else 0
    recent10 = idx_hist[idx_hist["trade_date"] <= trade_date].tail(10)
    support = _safe_float(recent10["low"].min())
    pressure = _safe_float(recent10["high"].max())
    index_state = "攻击盘" if sh_pct > 0.8 and amount_ratio > 5 else ("杀盘" if sh_pct < -0.8 else "整理盘")

    print(f"[DEBUG] 正在获取全市场日行情（最小必要字段）...")
    df_daily = _fetch_daily_market(pro, trade_date)
    print(f"[DEBUG] ✅ 全市场日行情获取完成 ({0 if df_daily is None else len(df_daily)} 条)")
    if df_daily is None:
        df_daily = pd.DataFrame()
    if not df_daily.empty:
        df_daily = df_daily.copy()
        if "name" not in df_daily.columns:
            df_daily["name"] = df_daily["ts_code"].map(name_map)
        df_daily = df_daily[~df_daily.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)].copy()
    red_cnt = int((pd.to_numeric(df_daily.get("pct_chg", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum()) if not df_daily.empty else 0
    green_cnt = int((pd.to_numeric(df_daily.get("pct_chg", pd.Series(dtype=float)), errors="coerce").fillna(0) < 0).sum()) if not df_daily.empty else 0

    def _load_limit(limit_type: str, date_for_query: Optional[str] = None) -> pd.DataFrame:
        qd = date_for_query if date_for_query else trade_date
        d = _cached_frame(
            "pro.limit_list_d.day",
            lambda: pro.limit_list_d(trade_date=qd, limit_type=limit_type),
            trade_date=qd,
            limit_type=limit_type,
        )
        if d is None:
            d = pd.DataFrame()
        # chinadata 当日为空时，切换到 AKShare 东财真实数据
        if d.empty:
            if limit_type == "U":
                d = _ak_zt_pool(qd)
            elif limit_type == "D":
                d = _ak_dt_pool(qd)
            elif limit_type == "Z":
                d = _ak_zb_pool(qd)
        if not d.empty:
            if "name" not in d.columns:
                d["name"] = d["ts_code"].map(name_map)
            d = d[~d.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)]
            d["limit_times"] = pd.to_numeric(d.get("limit_times", 1), errors="coerce").fillna(1).astype(int)
            d["fd_amount"] = pd.to_numeric(d.get("fd_amount", 0), errors="coerce").fillna(0)
            d["open_times"] = pd.to_numeric(d.get("open_times", 0), errors="coerce").fillna(0).astype(int)
            d["up_stat"] = d.get("up_stat", pd.Series([""] * len(d))).fillna("").astype(str)
        return d

    print(f"[DEBUG] 正在获取涨停池数据...")
    df_zt = _load_limit("U", trade_date)
    print(f"[DEBUG] ✅ 涨停池获取完成 ({len(df_zt)} 只)")

    print(f"[DEBUG] 正在获取跌停池数据...")
    df_dt = _load_limit("D")
    print(f"[DEBUG] ✅ 跌停池获取完成 ({len(df_dt)} 只)")

    print(f"[DEBUG] 正在获取炸板数据...")
    df_zb = _load_limit("Z")
    print(f"[DEBUG] ✅ 炸板数据获取完成 ({len(df_zb)} 只)")
    zt_cnt, dt_cnt, zb_cnt = len(df_zt), len(df_dt), len(df_zb)
    zt_dt_ratio = (zt_cnt / dt_cnt) if dt_cnt else float(zt_cnt)
    zt_counts = df_zt["limit_times"].value_counts().to_dict() if not df_zt.empty else {}
    max_height = max(zt_counts.keys()) if zt_counts else 0
    zt_dist = "，".join([f"{k}板:{v}只" for k, v in sorted(zt_counts.items(), reverse=True)]) if zt_counts else "—"

    # 昨日涨停（用于晋级率）
    print(f"[DEBUG] 正在获取昨日涨停池数据...")
    df_zt_prev = _load_limit("U", prev_trade)
    print(f"[DEBUG] ✅ 昨日涨停池获取完成 ({len(df_zt_prev)} 只)")

    bull1 = "—"
    bull2 = "—"
    if not df_zt.empty:
        t = df_zt.sort_values(["limit_times", "fd_amount"], ascending=[False, False])
        r1 = t.iloc[0]
        bull1 = f"{r1['name']}（{int(r1['limit_times'])}板，封单{_fd_yi(r1['fd_amount'])}）"
        if len(t) > 1:
            r2 = t.iloc[1]
            bull2 = f"{r2['name']}（{int(r2['limit_times'])}板，封单{_fd_yi(r2['fd_amount'])}）"
    bear1 = "—"
    if not df_dt.empty:
        t = df_dt.sort_values("fd_amount", ascending=False)
        r = t.iloc[0]
        bear1 = f"{r['name']}（跌停封单{_fd_yi(r['fd_amount'])}）"
    bear2 = f"{df_zb.iloc[0]['name']}（炸板样本）" if not df_zb.empty else "—"

    print(f"[DEBUG] 正在获取概念涨停数据...")
    df_cpt = _cached_frame(
        "pro.limit_cpt_list.day",
        lambda: pro.limit_cpt_list(trade_date=trade_date),
        trade_date=trade_date,
    )
    print(f"[DEBUG] ✅ 概念涨停获取完成")
    if df_cpt is None:
        df_cpt = pd.DataFrame()
    # top_concepts: (concept_ts_code, concept_name, count)
    top_concepts: List[Tuple[str, str, int]] = []
    if not df_cpt.empty and ("name" in df_cpt.columns):
        t = df_cpt.copy()
        # 不同版本字段可能为 count / up_nums（涨停数量）
        cnt_col = "count" if "count" in t.columns else ("up_nums" if "up_nums" in t.columns else None)
        if cnt_col is not None:
            t["_cnt"] = pd.to_numeric(t[cnt_col], errors="coerce").fillna(0).astype(int)
        else:
            t["_cnt"] = 0
        t = t[~t["name"].astype(str).str.contains("ST", case=False, na=False)]
        t = t.sort_values("_cnt", ascending=False).head(12)
        # 兼容字段：ts_code 有时是概念代码（如 885xxx.TI）
        if "ts_code" not in t.columns:
            t["ts_code"] = ""
        top_concepts = [(str(x.get("ts_code", "")), str(x["name"]), int(x["_cnt"])) for _, x in t.iterrows()]

    print(f"[DEBUG] 正在获取竞价排行数据...")
    df_kpl = _cached_frame(
        "pro.kpl_list",
        lambda: pro.kpl_list(trade_date=trade_date, list_type="limit_up"),
        trade_date=trade_date,
        list_type="limit_up",
    )
    print(f"[DEBUG] ✅ 竞价排行获取完成")
    if df_kpl is None:
        df_kpl = pd.DataFrame()
    # chinadata kpl_list 当日为空时，用 AKShare 涨停池（含行业标签）替代
    if df_kpl.empty:
        df_kpl = _ak_kpl_list(trade_date)
    if not df_kpl.empty and "name" not in df_kpl.columns:
        df_kpl["name"] = df_kpl["ts_code"].map(name_map)
    if not df_kpl.empty:
        df_kpl = df_kpl[~df_kpl.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)]

    # 主题/题材映射（保证不依赖 kpl_list 的更新时间）
    # theme_code_map: 题材名 -> [ts_code...]
    theme_code_map: Dict[str, List[str]] = {}

    # A) 优先：limit_cpt_list 已更新时，用 concept_cons 回填题材成分
    if top_concepts:
        # 并行化：用 ThreadPoolExecutor 并行查询 10 个概念的成分股
        concept_tasks = [(c_code, c_name) for c_code, c_name, _cnt in top_concepts[:10]]
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_get_concept_cons_codes, pro, c_code, trade_date): (c_code, c_name)
                       for c_code, c_name in concept_tasks}
            for future in as_completed(futures):
                c_code, c_name = futures[future]
                try:
                    codes = future.result()
                    if codes:
                        theme_code_map[c_name] = codes
                except Exception:
                    pass

    # B) 兜底：如果 concept_cons 也拿不到（或 limit_cpt_list 为空），再用 kpl_list 的 theme/lu_desc 统计
    if not theme_code_map and (df_kpl is not None) and (not df_kpl.empty):
        theme_counter: Dict[str, int] = {}
        tmp_map: Dict[str, List[str]] = {}
        for _, r in df_kpl.iterrows():
            code = str(r.get("ts_code", ""))
            theme_tokens = [x for x in _parse_theme_cell(r.get("theme", "")) if "ST" not in x.upper()]
            if not theme_tokens:
                lu_desc = str(r.get("lu_desc", "")).strip()
                if lu_desc:
                    theme_tokens = [lu_desc[:20]]
            for th in theme_tokens[:3]:
                if not th:
                    continue
                theme_counter[th] = theme_counter.get(th, 0) + 1
                tmp_map.setdefault(th, []).append(code)
        top_concepts = [("", k, v) for k, v in sorted(theme_counter.items(), key=lambda x: x[1], reverse=True)[:10]]
        theme_code_map = tmp_map

    zt_map = {r["ts_code"]: r for _, r in df_zt.iterrows()} if not df_zt.empty else {}
    prev_zt_map = {r["ts_code"]: r.to_dict() for _, r in df_zt_prev.iterrows()} if not df_zt_prev.empty else {}
    dt_map = {r["ts_code"]: r for _, r in df_dt.iterrows()} if not df_dt.empty else {}
    zb_map_dict = {r["ts_code"]: r for _, r in df_zb.iterrows()} if not df_zb.empty else {}

    # 昨日题材涨停数
    df_cpt_prev = _cached_frame(
        "pro.limit_cpt_list.day",
        lambda: pro.limit_cpt_list(trade_date=prev_trade),
        trade_date=prev_trade,
    )
    prev_concept_count_map: Dict[str, int] = {}
    if df_cpt_prev is not None and not df_cpt_prev.empty:
        _cnt_col = "count" if "count" in df_cpt_prev.columns else ("up_nums" if "up_nums" in df_cpt_prev.columns else None)
        if _cnt_col:
            df_cpt_prev["_cnt"] = pd.to_numeric(df_cpt_prev[_cnt_col], errors="coerce").fillna(0).astype(int)
            prev_concept_count_map = dict(zip(df_cpt_prev["name"].astype(str), df_cpt_prev["_cnt"].astype(int)))

    def _stock_label(z: dict, show_fd: bool = True) -> str:
        """生成股票标签：名称(N板/开M次/封单X亿/涨停历史)"""
        name_s = z.get("name", "")
        boards_s = _safe_int(z.get("limit_times", 1))
        ot_s = _safe_int(z.get("open_times", 0))
        ot_str = f"开{ot_s}次" if ot_s > 0 else "未开板"
        fd_str = f"/{_fd_yi(z.get('fd_amount', 0))}" if show_fd else ""
        up_s = str(z.get("up_stat", "")).strip()
        up_str = f"/{up_s}" if up_s and up_s not in ("nan", "") else ""
        return f"{name_s}({boards_s}板/{ot_str}{fd_str}{up_str})"

    theme_rows = []
    for _c_code, th, cnt in top_concepts[:10]:
        cand = []
        for code in theme_code_map.get(th, []):
            z = zt_map.get(code)
            if z is not None:
                cand.append(z)
        if not cand and (not df_kpl.empty) and ("theme" in df_kpl.columns):
            mk = df_kpl[df_kpl["theme"].astype(str).str.contains(re.escape(str(th)), na=False)]
            for _, r in mk.iterrows():
                z = zt_map.get(r["ts_code"])
                if z is not None:
                    cand.append(z)
        cand = sorted(cand, key=lambda x: (_safe_int(x.get("limit_times", 1)), _safe_float(x.get("fd_amount", 0))), reverse=True)
        if cand:
            c1 = cand[0]
            c2 = cand[1] if len(cand) > 1 else None
            l1 = _stock_label(c1)
            l2 = _stock_label(c2) if c2 is not None else "—"
            # 今日 vs 昨日封单对比
            fd_today = _fd_yi(c1["fd_amount"])
            prev_c1 = prev_zt_map.get(str(c1.get("ts_code", "")))
            fd_prev = _fd_yi(prev_c1["fd_amount"]) if prev_c1 else "—"
            fd = f"今{fd_today}/昨{fd_prev}"
        else:
            l1, l2, fd = "—", "—", "—"
        stage = "发酵" if cnt >= 4 else "轮动"
        theme_rows.append((th, l1, l2, stage, fd, "近10日高低点复核", "按龙头分时", "延续/分化观察"))
    while len(theme_rows) < 10:
        theme_rows.append(("", "", "", "", "", "", "", ""))

    def _calc_window_top_text_from_cache(window_days: int, daily_frames: Dict[str, pd.DataFrame]) -> str:
        if len(tdays) < window_days:
            return "—"
        use_days = tdays[max(0, t_idx - window_days + 1) : t_idx + 1]
        agg: Dict[str, float] = {}
        obs: Dict[str, int] = {}

        for d in use_days:
            dd = daily_frames.get(d)
            if dd is None or dd.empty:
                continue
            if "name" not in dd.columns:
                dd = dd.copy()
                dd["name"] = dd["ts_code"].map(name_map)
            dd = dd[~dd.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)].copy()
            if dd.empty:
                continue
            dd["pct_chg"] = pd.to_numeric(dd["pct_chg"], errors="coerce").fillna(0.0)
            for _, r in dd.iterrows():
                code = str(r["ts_code"])
                agg[code] = agg.get(code, 0.0) + float(r["pct_chg"])
                obs[code] = obs.get(code, 0) + 1

        if not agg:
            return "—"

        min_obs = max(1, window_days - 2)
        rows = []
        for code, v in agg.items():
            if obs.get(code, 0) >= min_obs:
                rows.append((nm(code), v))
        if not rows:
            rows = [(nm(code), v) for code, v in agg.items()]
        rows = sorted(rows, key=lambda x: x[1], reverse=True)
        top = rows[:5]
        return "；".join([f"{n}({_fmt_pct(p)})" for n, p in top]) if top else "—"

    daily_window_dates = tdays[max(0, t_idx - 9): t_idx + 1]
    print(f"[DEBUG] 正在并行获取窗口日行情数据...")
    daily_window_frames = _load_daily_window_frames(pro, daily_window_dates)
    print(f"[DEBUG] ✅ 窗口日行情数据获取完成 ({len(daily_window_frames)} 天)")

    top_5d_text = _calc_window_top_text_from_cache(5, daily_window_frames)
    top_10d_text = _calc_window_top_text_from_cache(10, daily_window_frames)

    print(f"[DEBUG] 正在并行获取后段基础数据...")
    _next_end = (datetime.strptime(trade_date, "%Y%m%d") + timedelta(days=10)).strftime("%Y%m%d")
    late_stage_data = _load_late_stage_data(trade_date, _next_end)
    print(f"[DEBUG] ✅ 后段基础数据获取完成")

    db = late_stage_data.get("daily_basic")
    if db is None:
        db = pd.DataFrame()
    if not db.empty:
        db = db.copy()
        db["name"] = db["ts_code"].map(name_map)
        db = db[~db.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)].copy()
        db["turnover_rate"] = pd.to_numeric(db["turnover_rate"], errors="coerce").fillna(0)
        turn_text = "；".join([f"{x['name']}({x['turnover_rate']:.2f}%)" for _, x in db.sort_values("turnover_rate", ascending=False).head(5).iterrows()])
    else:
        turn_text = "—"

    amount_text = "—"
    if not df_daily.empty and "amount" in df_daily.columns:
        da = df_daily.copy()
        da["amount"] = pd.to_numeric(da["amount"], errors="coerce").fillna(0)
        amount_text = "；".join([f"{x['name']}({_fmt_yi_from_thousand(x['amount'])})" for _, x in da.sort_values("amount", ascending=False).head(5).iterrows()])

    market_style = "首板主导，轮动明显" if zt_counts.get(1, 0) > sum(v for k, v in zt_counts.items() if k >= 2) else "连板接力偏强"
    if dt_cnt > zt_cnt:
        market_style = "风险偏好偏弱，防守风格"

    lhb = late_stage_data.get("top_list")
    if lhb is None:
        lhb = pd.DataFrame()
    # chinadata top_list 当日为空时，用 AKShare 龙虎榜替代
    _lhb_from_ak = lhb.empty
    if lhb.empty:
        lhb = _ak_top_list(trade_date)
    if not lhb.empty:
        if "name" not in lhb.columns:
            lhb["name"] = lhb["ts_code"].map(name_map)
        lhb = lhb[~lhb.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)]
    lhb_rows = []
    top_lhb_rows = list(lhb.head(8).iterrows())
    top_inst_map: Dict[str, pd.DataFrame] = {}
    if not _lhb_from_ak and top_lhb_rows:
        print(f"[DEBUG] 正在并行获取龙虎榜明细...")
        top_inst_map = _parallel_map(
            [
                (
                    str(r["ts_code"]),
                    lambda code=str(r["ts_code"]): _cached_frame(
                        "pro.top_inst",
                        lambda: pro.top_inst(ts_code=code, trade_date=trade_date),
                        ts_code=code,
                        trade_date=trade_date,
                    ),
                )
                for _, r in top_lhb_rows
            ],
            max_workers=4,
        )
        print(f"[DEBUG] ✅ 龙虎榜明细获取完成 ({len(top_inst_map)} 只)")

    for _, r in top_lhb_rows:
        code = str(r["ts_code"])
        net = 0.0
        if _lhb_from_ak:
            net = _safe_float(r.get("net_buy", 0))
        else:
            di = top_inst_map.get(code)
            if di is not None and not di.empty:
                if "net_buy" in di.columns:
                    net = pd.to_numeric(di["net_buy"], errors="coerce").fillna(0).sum()
                elif {"buy", "sell"}.issubset(di.columns):
                    net = pd.to_numeric(di["buy"], errors="coerce").fillna(0).sum() - pd.to_numeric(di["sell"], errors="coerce").fillna(0).sum()
        lhb_rows.append((str(r.get("name", nm(code))), str(r.get("reason", ""))[:20], net / 1e8))
    while len(lhb_rows) < 5:
        lhb_rows.append(("", "", 0.0))

    auc = late_stage_data.get("stk_auction")
    auc_text = "—"
    if auc is not None and not auc.empty:
        auc = auc.copy()
        auc["name"] = auc["ts_code"].map(name_map)
        auc = auc[~auc.apply(lambda r: _is_excluded(r.get("ts_code"), r.get("name")), axis=1)].copy()
        auc["amount"] = pd.to_numeric(auc["amount"], errors="coerce").fillna(0)
        auc["price"] = pd.to_numeric(auc["price"], errors="coerce").fillna(0)
        auc["pre_close"] = pd.to_numeric(auc["pre_close"], errors="coerce").fillna(0)
        auc["pct"] = (auc["price"] - auc["pre_close"]) / auc["pre_close"].replace(0, pd.NA) * 100
        lines = []
        for _, r in auc.sort_values("amount", ascending=False).head(5).iterrows():
            lines.append(f"{r['name']} 金额{_safe_float(r['amount'])/10000:.2f}万，竞价涨跌{_fmt_pct(_safe_float(r['pct']))}")
        auc_text = "；".join(lines) if lines else "—"

    if zt_cnt >= 65 and dt_cnt <= 15:
        emotion = "发酵"
    elif zt_cnt <= 30 and dt_cnt >= 25:
        emotion = "退潮"
    elif zt_cnt >= 90 and dt_cnt <= 8:
        emotion = "高潮"
    else:
        emotion = "混沌/轮动"
    combo = "共振走强" if (sh_pct > 0 and zt_cnt > dt_cnt) else ("背离" if (sh_pct < 0 and zt_cnt > dt_cnt) else "割裂")

    score_idx = 4 if index_state == "攻击盘" else (2 if index_state == "整理盘" else 1)
    score_emo = 3 if emotion in {"发酵", "高潮"} else (1 if "退潮" in emotion else 2)
    score_theme = 2 if len([x for x in top_concepts if x[2] > 0]) >= 3 else 1
    score_total = score_idx + score_emo + score_theme + 1
    if score_total <= 4:
        wh = "总仓≤4成；单票≤1成；以防守为主"
    elif score_total <= 6:
        wh = "总仓4～6成；单票1～2成"
    elif score_total <= 8:
        wh = "总仓6～8成；单票2～3成"
    else:
        wh = "可重仓，建议留20%机动仓"

    theme_rank_text = "、".join([f"{x[1]}({x[2]})" for x in top_concepts[:5]]) if top_concepts else "—"
    lhb_buy = next((f"{x[0]}({x[2]:+.2f}亿)" for x in lhb_rows if x[0]), "—")
    lhb_sell = next((f"{x[0]}({x[2]:+.2f}亿)" for x in sorted(lhb_rows, key=lambda y: y[2]) if x[0]), "—")

    board_lines = "\n".join([f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} |" for r in theme_rows])
    ladder_rows = []
    concept_count_map = {name: cnt for _cc, name, cnt in top_concepts}
    for i, r in enumerate(theme_rows[:5], 1):
        th_name = r[0]
        # 题材下对应的涨停股（按连板和封单排序）
        themed_candidates = []
        for code in theme_code_map.get(th_name, []):
            z = zt_map.get(code)
            if z is not None:
                themed_candidates.append(z)
        themed_candidates = sorted(
            themed_candidates,
            key=lambda x: (_safe_int(x.get("limit_times", 1)), _safe_float(x.get("fd_amount", 0))),
            reverse=True,
        )

        def _pick_by_board(board_n: int) -> str:
            for z in themed_candidates:
                if _safe_int(z.get("limit_times", 1)) == board_n:
                    return _stock_label(z)
            return "—"

        b5 = _pick_by_board(5)
        b4 = _pick_by_board(4)
        b3 = _pick_by_board(3)
        b2 = _pick_by_board(2)
        b1 = _pick_by_board(1)
        prev_cnt = prev_concept_count_map.get(th_name, 0)
        cnt_today = concept_count_map.get(th_name, 0)
        cnt_str = f"{cnt_today}(昨{prev_cnt})" if prev_cnt else str(cnt_today)
        ladder_rows.append(
            f"| {th_name if th_name else '—'} | {cnt_str} | {b5} | {b4} | {b3} | {b2} | {b1} | {r[4]} |"
        )
    while len(ladder_rows) < 5:
        ladder_rows.append("|  |  |  |  |  |  |  |  |")
    ladder_text = "\n".join(ladder_rows)

    # 各题材完整候选股池（供 AI 生成执行手册时直接引用）
    stock_pool_sections: List[str] = []
    for _cc, th_name, cnt_today in top_concepts[:5]:
        if not th_name:
            continue
        cands_pool = [zt_map[c] for c in theme_code_map.get(th_name, []) if c in zt_map]
        cands_pool = sorted(cands_pool, key=lambda x: (_safe_int(x.get("limit_times", 1)), _safe_float(x.get("fd_amount", 0))), reverse=True)
        prev_cnt_pool = prev_concept_count_map.get(th_name, 0)
        rows_pool = [f"| 顺位 | 股票 | 板数 | 开板次数 | 今日封单 | 昨日封单 | 涨停历史 |",
                     "|:---:|---|:---:|:---:|---|---|---|"]
        for rank_p, z in enumerate(cands_pool[:6], 1):
            n = z.get("name", "")
            b = _safe_int(z.get("limit_times", 1))
            ot = _safe_int(z.get("open_times", 0))
            ot_s = f"开{ot}次" if ot > 0 else "✅未开板"
            fd_t = _fd_yi(z.get("fd_amount", 0))
            prev_z = prev_zt_map.get(str(z.get("ts_code", "")))
            fd_p = _fd_yi(prev_z["fd_amount"]) if prev_z else "—"
            up_s = str(z.get("up_stat", "")).strip()
            up_s = up_s if up_s and up_s not in ("nan", "") else "—"
            rows_pool.append(f"| 龙{rank_p} | **{n}** | {b}板 | {ot_s} | {fd_t} | {fd_p} | {up_s} |")
        section_title = f"#### {th_name}（今日涨停{cnt_today}只 / 昨日{prev_cnt_pool}只）"
        stock_pool_sections.append(section_title + "\n\n" + "\n".join(rows_pool))
    stock_pool_md = "\n\n".join(stock_pool_sections) if stock_pool_sections else "— 暂无数据 —"
    jiuyan_overlap_md = _build_overlap_anchor_section(
        trade_date_h, set(zt_map.keys()), top_concepts, theme_code_map, zt_map
    )

    lhb_lines = "\n".join([f"| {r[0]} | {r[1]} | 机构/游资明细汇总 | {r[2]:+.2f}亿 | {'偏正面' if r[2] > 0 else ('偏负面' if r[2] < 0 else '')} |" for r in lhb_rows[:5]])

    # 晋级率（市场口径：今N+1板数量 / 昨N板数量）
    promote_text = "—"
    if (df_zt_prev is not None) and (not df_zt_prev.empty) and (df_zt is not None) and (not df_zt.empty):
        promo_parts = []
        for n in [1, 2, 3, 4, 5]:
            prev_n_cnt = int((df_zt_prev["limit_times"] == n).sum())
            if prev_n_cnt <= 0:
                continue
            today_n1_cnt = int((df_zt["limit_times"] == (n + 1)).sum())
            rate = (today_n1_cnt / prev_n_cnt * 100.0) if prev_n_cnt else 0.0
            promo_parts.append(f"{n}→{n+1}:{today_n1_cnt}/{prev_n_cnt}({rate:.1f}%)")
        if promo_parts:
            promote_text = "；".join(promo_parts)

    # 情绪日历持久化（方案A）
    trend_arrow = "↑" if zt_cnt > dt_cnt else ("↓" if zt_cnt < dt_cnt else "→")
    emo_sentence = f"涨停{zt_cnt}、跌停{dt_cnt}，结构偏{market_style}"
    calendar_csv = str(KNOWLEDGE_DIR / "情绪日历.csv")
    emo_rows = _upsert_emotion_calendar(
        calendar_csv_path=calendar_csv,
        trade_date_h=trade_date_h,
        emotion=emotion,
        sentence=emo_sentence,
        trend=trend_arrow,
    )
    while len(emo_rows) < 5:
        emo_rows.insert(0, ("", "", "", ""))
    emo_rows_md = "\n".join([f"| {d} | {e} | {s} | {t} |" for d, e, s, t in emo_rows])

    # ── 修正的如果则触发逻辑 ─────────────────────────────────────────────────
    # 情-3 割裂：同一题材中既有涨停又有跌停/炸板（而非全市场涨跌停数之差）
    split_themes: List[str] = []
    for th_name in [r[0] for r in theme_rows[:6] if r[0]]:
        codes_in_theme = theme_code_map.get(th_name, [])
        has_zt = any(c in zt_map for c in codes_in_theme)
        has_weak = any((c in dt_map or c in zb_map_dict) for c in codes_in_theme)
        if has_zt and has_weak:
            split_themes.append(th_name)
    qing3_trigger = "触发" if split_themes else "未触发"
    qing3_note = f"割裂题材：{'、'.join(split_themes[:3])}" if split_themes else ""

    # 题-1 封单回流：对前3题材各自龙头，今日封单 > 昨日同股封单 → 视为回流
    fd_increase_themes: List[str] = []
    fd_decrease_themes: List[str] = []
    for th_name in [r[0] for r in theme_rows[:4] if r[0]]:
        codes_in_theme = theme_code_map.get(th_name, [])
        cand_today = [zt_map[c] for c in codes_in_theme if c in zt_map]
        if not cand_today:
            continue
        cand_today = sorted(cand_today, key=lambda x: (_safe_int(x.get("limit_times", 1)), _safe_float(x.get("fd_amount", 0))), reverse=True)
        dragon = cand_today[0]
        ts_code_dragon = dragon.get("ts_code", "")
        fd_today_val = _safe_float(dragon.get("fd_amount", 0))
        prev_dragon = prev_zt_map.get(ts_code_dragon)
        if prev_dragon is not None:
            fd_prev_val = _safe_float(prev_dragon.get("fd_amount", 0))
            if fd_today_val > fd_prev_val:
                fd_increase_themes.append(th_name)
            else:
                fd_decrease_themes.append(th_name)
    if len(fd_increase_themes) >= 2:
        ti1_trigger = "触发"
    elif len(fd_increase_themes) == 1:
        ti1_trigger = "部分触发"
    else:
        ti1_trigger = "未触发"
    ti1_note = f"回流：{'、'.join(fd_increase_themes)}；分化：{'、'.join(fd_decrease_themes)}" if (fd_increase_themes or fd_decrease_themes) else "昨日数据不足以比较"

    # 题-3 切换：新题材（今日涨停数 ↑ 且昨日排名靠后）vs 旧题材涨停数 ↓
    new_themes: List[str] = []
    weak_old_themes: List[str] = []
    for _cc, th_name, cnt_today in top_concepts[:10]:
        cnt_prev = prev_concept_count_map.get(th_name, 0)
        rank_today = next((i for i, x in enumerate(top_concepts) if x[1] == th_name), 99)
        if cnt_prev == 0 and cnt_today >= 3:
            new_themes.append(th_name)
        elif cnt_prev > 0 and cnt_today < cnt_prev and rank_today >= 5:
            weak_old_themes.append(th_name)
    ti3_trigger = "触发" if new_themes else ("部分触发" if weak_old_themes else "未触发")
    ti3_note = f"新题材：{'、'.join(new_themes[:2])}" if new_themes else ""

    # ── 获取下一交易日 ────────────────────────────────────────────────────────
    next_trade = None
    try:
        _cal = late_stage_data.get("trade_cal")
        if _cal is not None and not _cal.empty:
            _cal = _cal.copy()
            _cal["cal_date"] = _cal["cal_date"].astype(str).str.zfill(8)
            _cal["is_open"] = pd.to_numeric(_cal["is_open"], errors="coerce").fillna(0).astype(int)
            _open_days = _cal[(_cal["is_open"] == 1) & (_cal["cal_date"] > trade_date)]["cal_date"].tolist()
            if _open_days:
                next_trade = sorted(_open_days)[0]
    except Exception:
        pass
    if next_trade is None:
        try:
            import akshare as ak
            _trade_days = pd.to_datetime(ak.tool_trade_date_hist_sina()["trade_date"]).dt.strftime("%Y%m%d").tolist()
            _next_days = [d for d in _trade_days if d > trade_date]
            if _next_days:
                next_trade = _next_days[0]
        except Exception:
            pass
    if next_trade is None:
        _fallback = datetime.strptime(trade_date, "%Y%m%d") + timedelta(days=1)
        while _fallback.weekday() >= 5:
            _fallback += timedelta(days=1)
        next_trade = _fallback.strftime("%Y%m%d")
    next_trade_h = f"{next_trade[:4]}-{next_trade[4:6]}-{next_trade[6:]}"

    # ── 近5日题材热力追踪（轮动方向数据源，必须在 md f-string 之前赋值）────────
    print(f"[DEBUG] 正在构建近5日题材热力追踪...")
    rotation_section_md = _build_rotation_section(
        pro=pro,
        past_5_days=past_5_days,
        trade_date=trade_date,
        name_map=name_map,
        theme_code_map=theme_code_map,
    )
    print(f"[DEBUG] ✅ 近5日题材热力追踪构建完成")

    md = f"""# 每日复盘表

> **日期**：{trade_date_h}
> **两市成交额**：{_fmt_yi_from_thousand(sh_amount)}
> **目的**：准确描述当日市场 + 为次日预案做准备

---

## 整体框架

| 区域 | 模块 | 完成✓ |
|------|------|-------|
| **盘后复盘区** | 一、指数复盘 | ✓ |
| | 二、板块与题材复盘 | ✓ |
| | 三、涨停梯队与情绪复盘（含3.5近5日热力追踪） | ✓ |
| | 四、660 个股复盘 | ✓ |
| | 五、龙虎榜复盘 | ✓ |
| | 六、消息面复盘 | ✓ |
| | 七、自我交易回顾 | ✓ |
| **次日预案区** | 八、如果则执行清单（15 条） | ✓ |
| | 九、可做方向与次日票池 | ✓ |
| | 十、仓位计划 | ✓ |
| **次日盘前区** | 十一、隔夜外盘与竞价观察 | ✓ |

---

# 盘后复盘区

---

## 一、指数复盘

| 项目 | 填写 |
|------|------|
| 昨日 K 线 / 形态 | 上证开{sh_open:.2f}，高{sh_high:.2f}，低{sh_low:.2f}，收{sh_close:.2f}，涨跌{_fmt_pct(sh_pct)} |
| 关键点位 - 支撑 | {support:.2f} |
| 关键点位 - 压力 | {pressure:.2f} |
| 量能情况 | 上证成交额{_fmt_yi_from_thousand(sh_amount)}，较前日{_fmt_pct(amount_ratio)} |
| 指数结构（谁护盘 / 谁砸盘） | 深成指{_fmt_pct(_safe_float(sz_r.get('pct_chg')))}；创业板{_fmt_pct(_safe_float(cyb_r.get('pct_chg')))} |
| 盘形 / 盘式（多头式 / 空头式） | {index_state} |
| 明日关键点位（支撑＋压力） | 支撑{support:.2f} / 压力{pressure:.2f} |
| 近期指数预期（1～2 日） | {"震荡偏强" if score_idx >= 3 else "震荡偏弱"} |

**本模块总结：**
> 指数当前为{index_state}，关键观察是否守住支撑并放量向上。

---

## 二、板块与题材复盘

| 板块名称 | 龙一 | 龙二 | 运行阶段 | 封单 / 强度 | 前高 / 支撑 | 上车点 / 出局点 | 明日预期 |
|----|----|----|----|----|----|----|----|
{board_lines}

> 运行阶段可选：启动 / 发酵 / 高潮 / 分歧 / 分化 / 退潮 / 混沌
> 明日预期可选：延续 / 分化 / 回流 / 切换 / 轮动

| 补充项 | 填写 |
|------|------|
| 昨日题材排名（Top3～5） | {theme_rank_text} |
| 日内最佳机会（触发信号＋买点＋模式） | 龙头分歧转一致、首板前排确认 |
| 明日最佳机会预判 | 优先强题材龙一，分歧看弱转强 |

**本模块总结：**
> 已排除 ST 板块，当前题材分布以前排概念为主，建议聚焦核心龙头。

---

## 三、涨停梯队与情绪复盘

### 3.1 涨停梯队表

| 题材 | 今日涨停(昨日) | 5板 | 4板 | 3板 | 2板 | 首板前排 | 今日龙头封单/昨日 |
|---|---|---|---|---|---|---|---|
{ladder_text}

| 梯队汇总项 | 填写 |
|---------------|------|
| 市场最高板 / 高度 | {max_height}板 |
| 梯队完整性（是否断档） | {"有断档（仅低位）" if max_height <= 2 else "相对完整"} |
| 晋级率（昨 N 板→今晋级数） | {promote_text} |
| 主线是否清晰 / 多题材轮动 | {market_style} |

### 3.2 情绪复盘表

| 项目 | 填写 |
|---------------------------|------|
| 多头风标 1 | {bull1} |
| 多头风标 2 | {bull2} |
| 空头风标 1 | {bear1} |
| 空头风标 2 | {bear2} |
| 情绪节点（启动/发酵/高潮/分歧/分化/退潮/混沌） | {emotion} |
| 指数与情绪组合（共振走强 / 背离 / 割裂） | {combo} |
| 涨停家数 | {zt_cnt} |
| 跌停家数 | {dt_cnt} |
| 红盘数 | {red_cnt} |
| 绿盘数 | {green_cnt} |

### 3.3 情绪日历（连续记录）

| 日期 | 情绪节点 | 一句话描述当日情绪 | 趋势（↑ / → / ↓） |
|---|----|-----------|-------------|
{emo_rows_md}

**本模块总结：**
> 情绪处于{emotion}，强弱分化仍在，建议只做前排。

### 3.4 各题材完整候选股池（供执行手册选股）

> 格式：开板次数✅=未开板（更强），今日封单 vs 昨日封单可判断回流/分化，涨停历史(N/T)=T天内涨停N次

{stock_pool_md}

{jiuyan_overlap_md}

### 3.5 近5日题材热力追踪（供执行手册「轮动方向」板块使用）

> 展示最近5个交易日各热门题材的涨停家数走势，识别已退潮但有资金记忆的题材及其龙头股。
> AI 生成执行手册「轮动方向」板块时，直接读取本节数据。

{rotation_section_md}

---

## 四、660 个股复盘

| 排序维度 | 要点记录 |
|------------------------|------|
| 5 日涨幅前排 | {top_5d_text} |
| 10 日涨幅前排 | {top_10d_text} |
| 成交额异常（题材中军识别） | {amount_text} |
| 换手率异常（模式机会筛选） | {turn_text} |
| DDE / 主力净量前排（攻击 / 兑现方向） | 当前接口未直接提供，建议补充专用数据源 |
| 尾盘竞价抢筹前排（3:00 排序） | {auc_text} |
| 市场风格识别（断板反包 / 弱转强 / 趋势等） | {market_style} |

**本模块总结：**
> 660 维度显示“高换手 + 题材前排”仍是核心筛选逻辑。

---

## 五、龙虎榜复盘

| 标的 | 上榜原因 | 机构 / 游资 | 净买入(+) / 净卖出(-) | 对次日预期的影响 |
|---|----|-------|---------------|--------|
{lhb_lines}

| 汇总项 | 填写 |
|-------------|------|
| 机构净买入最大的标的 | {lhb_buy} |
| 机构净卖出最大的标的 | {lhb_sell} |
| 有影响力游资的动向 | 以净买入前排票为主观察 |
| 机构被套 → 次日低吸候选 | 净卖出过大的票仅观察，不抢反抽 |

**本模块总结：**
> 龙虎榜方向偏分化，次日优先看净买入前排反馈。

---

## 六、消息面复盘

| 序号 | 消息要点 | 影响方向（利多 / 利空 / 不确定） | 涉及题材 |
|---|----|-------------------|----|
| 1 | 上证{_fmt_pct(sh_pct)}，量能{_fmt_pct(amount_ratio)} | {"利多" if sh_pct > 0 else "利空"} | 指数 |
| 2 | 涨停{zt_cnt}、跌停{dt_cnt} | {"利多" if zt_cnt > dt_cnt else "利空"} | 全市场 |
| 3 | 最高板{max_height}板，连板结构{zt_dist} | 不确定 | 连板接力 |
| 4 | 题材前排：{theme_rank_text} | 不确定 | 题材轮动 |
| 5 | 竞价前排：{auc_text} | 不确定 | 竞价资金 |

**本模块总结：**
> 当日主要由量价结构和题材轮动主导，消息驱动偏中性。

---

## 七、自我交易回顾

| 项目 | 填写 |
|------------------|------|
| 今日持仓与操作记录 | 依个人实盘补充 |
| 每笔交易的模式归因 | 依个人实盘补充 |
| 做对了什么（可复制的好动作） | 只做前排、避免后排追高 |
| 做错了什么（需要改正的坏习惯） | 盘中随意切换、忽视仓位纪律 |
| 票池中看到但没做的机会，为什么没做？ | 依个人实盘补充 |
| 票池中做了但失败的机会，为什么失败？ | 依个人实盘补充 |
| 明日改进计划 | 先看风标竞价，再按如果则执行 |

**本模块总结：**
> 操作以纪律优先，先环境后个股。

---

# 次日预案区

---

## 八、如果则执行清单（15 条）

### 8.1 指数（4 条）

| 编号 | 如果（条件） | 是否触发 | 则（操作） | 备注 |
|---|-------------------------|----|-----|---|
| 指-1 | 高开在关键点位之上，且第一根 5 分 K 带量上攻 | {"触发" if (sh_open > support and amount_ratio > 0) else "未触发"} | 可上仓 |  |
| 指-2 | 高开在关键点位之下 | {"触发" if (sh_open > _safe_float(sh_p.get('close')) and sh_open < support) else "未触发"} | 等站稳再加仓 |  |
| 指-3 | 低开且缩量 | {"触发" if (sh_open <= _safe_float(sh_p.get('close')) and amount_ratio < 0) else "未触发"} | 控仓≤6成 |  |
| 指-4 | 破支撑 | {"触发" if sh_low < support else "未触发"} | 防守/降仓 |  |

### 8.2 情绪（3 条）

| 编号 | 如果（条件） | 是否触发 | 则（操作） | 备注 |
|---|------------------|----|-----|---|
| 情-1 | 多头风标强 + 空头风标弱 | {"触发" if zt_cnt > dt_cnt else "未触发"} | 顺强做强 |  |
| 情-2 | 空头风标崩盘（一字跌停 / 瀑布杀） | {"触发" if dt_cnt >= 20 else "未触发"} | 防守优先 |  |
| 情-3 | 割裂（同题材一涨停一跌停） | {qing3_trigger} | 只做核心 | {qing3_note} |

### 8.3 题材（4 条）

| 编号 | 如果（条件） | 是否触发 | 则（操作） | 备注 |
|---|---------------|----|-----|---|
| 题-1 | 龙一龙二封单比昨日加大（回流） | {ti1_trigger} | 做龙一 | {ti1_note} |
| 题-2 | 龙头强、后排掉队（分化） | {"触发" if (zt_cnt > 0 and zb_cnt > 0) else "未触发"} | 去弱留强 |  |
| 题-3 | 新题材抢筹、旧题材弱（切换） | {ti3_trigger} | 低位试错 | {ti3_note} |
| 题-4 | 量能不大、连板数不多（轮动） | {"触发" if '轮动' in market_style else "未触发"} | 快进快出 |  |

### 8.4 持仓（4 条）

| 编号 | 如果（条件） | 是否触发 | 则（操作） | 备注 |
|---|--------------------------|----|-----|---|
| 仓-1 | 持仓股高开且强势 | 依个人持仓 | 持有/加仓 |  |
| 仓-2 | 高档爆量形态（十字星 / 最长红 / 大阴）次日低开 | 依个人持仓 | 减仓/止损 |  |
| 仓-3 | 低开但题材有预期 | 依个人持仓 | 看支撑再决策 |  |
| 仓-4 | 四块共振（指数 + 情绪 + 题材 + 个股） | {"触发" if score_total >= 8 else "未触发"} | 单票可提至2-3成 |  |

| 执行结论 | 填写 |
|------|------|
| 整体操作基调 | {wh} |

**本模块总结：**
> 总评分{score_total}/10，建议执行节奏：先防守后进攻。

---

## 九、可做方向与次日票池

### 9.1 可做方向

| 类型 | 标的候选 | 参与条件 | 否决条件 |
|---|----|----|----|
| 核心龙头 | {bull1} | 竞价强、封单稳 | 高开过度放量 |
| 低位新启动 / 首板试错 | 前排题材首板 | 量价共振 | 尾盘抢高 |
| 弱转强 / 卡位 | 炸板样本次日转强 | 开盘承接强 | 开盘走弱 |
| 空头风标反核 | {bear1} | 情绪修复确认 | 继续走弱 |

### 9.2 次日票池

| 来源 | 标的 | 关注理由 | 竞价观察信号 |
|---|---|----|------|
| 涨停梯队（龙头 + 封单前排） | {bull1} | 强度最高 | 竞价封单变化 |
| 660 排序（换手 / DDE / 尾盘抢筹） | {turn_text} | 资金活跃 | 开盘承接 |
| 龙虎榜（机构大买 / 游资入场） | {lhb_buy} | 资金方向 | 是否延续 |
| 炸板 / 断板池（次日弱转强候选） | {bear2} | 观察转强 | 竞价弱转强 |
| 消息催化（新题材 / 新逻辑） | {theme_rank_text} | 题材驱动 | 板块联动 |

**本模块总结：**
> 次日票池以“龙头 + 资金确认 + 竞价强度”三要素筛选。

---

## 十、仓位计划

### 10.1 四块拼图打分

| 维度 | 权重 | 当日评分 | 评分依据 |
|---|------|-------|----|
| 指数 | 4 | {score_idx}/4 | {index_state} |
| 情绪 | 3 | {score_emo}/3 | {emotion} |
| 题材 | 2 | {score_theme}/2 | 前排题材数量与一致性 |
| 个股（符合模式=1） | 1 | 1/1 | 仅做模式内 |
| **合计** | **10** | **{score_total}/10** |  |

### 10.2 仓位锚定

| 项目 | 填写 |
|---|---|
| 明日总仓位上限 | {wh} |
| 明日单票仓位上限 | 2-3成（环境好） |
| 机动仓预留 | 2成 |

> 仓位参考：合计≤4 → 总仓≤4成；5～6 → 总仓4～6成；7～8 → 总仓6～8成；9～10 → 可重仓，留20%活钱

**本模块总结：**
> 仓位随环境动态调整，避免重仓追高。

---

# 次日盘前区

---

## 十一、隔夜外盘与竞价观察

### 11.1 隔夜外盘 / 中概股（盘前填写）

| 项目 | 填写 |
|---|---|
| 美股主要指数涨跌 | 盘前待补 |
| 中国金龙指数涨跌 | 盘前待补 |
| 对 A 股情绪的影响倾向 | 盘前待补 |

### 11.2 竞价 / 隔夜单观察（9:15～9:25 填写）

| 时间 | 观察内容 |
|-------------------------------|----|
| 9:15（隔夜封单雏形） | 盘前待补 |
| 9:20（加单 / 撤单变化） | 盘前待补 |
| 9:25（成交额 / 封单额 / 换手 / 关键风标竞价强弱） | {auc_text} |

### 11.3 开盘定调

| 项目 | 填写 |
|------------------------------|---|
| 指数开盘位置（相对关键点位） | 观察是否守{support:.2f} |
| 盘形判断（攻击盘 / 多方整理 / 空方整理 / 杀盘） | {index_state} |
| 风标开盘反馈 | 重点看{bull1} |
| 今日题材预期（延续 / 分化 / 回流 / 切换 / 轮动） | 延续/分化并存 |
| 开盘操作基调 | 先确认再出手 |

**本模块总结：**
> 盘前执行要点：先看指数位置，再看风标竞价确认。

---

# 全文总结

| 项目 | 填写 |
|-----------------------------|---|
| 当日市场一句话描述 | {trade_date_h} 市场整体为“{index_state}+{emotion}”，风格偏{market_style}。 |
| 当日情绪核心矛盾 | 指数量能与题材持续性是否同步。 |
| 次日最需关注的一件事 | 支撑{support:.2f}附近承接 + 龙头竞价反馈。 |
| 次日操作关键词（如：控仓观望 / 积极做多 / 顺强做强） | 顺强做强，去弱留强。 |

> **详细总结：**
>
> 指数收于{sh_close:.2f}（{_fmt_pct(sh_pct)}），量能较前日{_fmt_pct(amount_ratio)}。  
> 市场涨停{zt_cnt}、跌停{dt_cnt}、炸板{zb_cnt}，最高板{max_height}，情绪定性为{emotion}。  
> 题材前排为{theme_rank_text}，已自动排除 ST / 北交所 / 科创干扰样本。  
> 次日执行建议：{wh}
"""

    out_md = str(REVIEW_DIR / f"每日复盘表_{trade_date_h}.md")
    print(f"[DEBUG] 正在写出复盘文件...")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[OK] 已生成复盘文件: {out_md}")
    print(f"[INFO] 次日交易日: {next_trade_h}")
    print(f"[INFO] 执行手册将由 AI 读取复盘表后生成，无需此脚本输出。")
    _write_profile_report(trade_date)


if __name__ == "__main__":
    main = _profiled_function(main)
    main()


