# -*- coding: utf-8 -*-
"""
calc_calibration.py
===================
「当前校准值」唯一数据源：回溯过去 N 个**交易日**（默认 30），按**板数**分桶，
统计「当日以竞价价位近似开盘买入、收盘相对开盘有收益」的**竞价涨幅**分布，取中位数。

定义（与 SKILL「30日实战经验数值」一致）：
  - 样本范围：各交易日 limit_list_d 涨停池（limit_type=U）
  - 板数：该日 limit_times（连板数）
  - 竞价涨幅：(stk_auction.price - pre_close) / pre_close * 100
  - 有收益：日线 close > open（按官方开盘价买入的简化假设）
  - 剔除竞价涨幅 ≥ 9.5% 的一字样本（与速查「可操作」一致，可用 --include-yizi 关闭）

用法：
  python calc_calibration.py
  python calc_calibration.py --end-date 20260326 --trade-days 30
  python calc_calibration.py --legacy   # 仅打印旧版「经验库命中中位数」对照
  python calc_calibration.py --rebuild-cache   # 强制全量回溯并重写 outputs/cache/calibration_cache.json

增量缓存（默认开启）下：
  首次或窗口无法衔接时全量拉取过去 N 个交易日，结果写入 ``outputs/cache/calibration_cache.json``（按日存各桶样本）。
  之后若复盘日仅为「上一窗口末端」的下一交易日，只拉取 1 天并滑窗丢弃最旧一日，显著加速。
  窗口已对齐同一 end-date 时直接读缓存、零 API 逐日回溯。

输出：控制台打印各板数区间中位数，供写入 SKILL「当前校准值」与速查卡。
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import chinadata.ca_data as ts
import chinamindata.min as tss

from _paths import CACHE_DIR, KNOWLEDGE_DIR

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"
TOKEN_MIN = "ne34e6697159de73c228e34379b510ec554"

EXP_PATH = str(KNOWLEDGE_DIR / "经验库.md")
CACHE_PATH = CACHE_DIR / "calibration_cache.json"
CACHE_VERSION = 1
AUCTION_CACHE_DIR = CACHE_DIR / ".calibration_auction_cache"
DAILY_OC_CACHE_DIR = CACHE_DIR / ".calibration_daily_oc_cache"

# ── 新版：30 日市场回溯 ────────────────────────────────────────


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2


def _board_bucket(limit_times: int) -> str:
    lt = int(limit_times)
    if lt <= 1:
        return "首板"
    if lt == 2:
        return "2板"
    if lt == 3:
        return "3板"
    if lt == 4:
        return "4板"
    return "5板+"


def _get_trade_days(pro, end_date: str, n: int) -> List[str]:
    start = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
    try:
        df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end_date, is_open="1")
        if isinstance(df, pd.DataFrame) and not df.empty:
            dates = sorted(d for d in df["cal_date"].astype(str).str.zfill(8).tolist() if d <= end_date)
            return dates[-n:] if len(dates) >= n else dates
    except Exception:
        pass

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = sorted(
            pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d").tolist()
        )
        dates = [d for d in dates if d <= end_date]
        return dates[-n:] if len(dates) >= n else dates
    except Exception:
        return []


def _fetch_auction_map(pro_min, trade_date: str) -> Dict[str, dict]:
    cache_path = AUCTION_CACHE_DIR / f"{trade_date}.json"
    if cache_path.is_file():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            try:
                cache_path.unlink()
            except Exception:
                pass
    try:
        auc = pro_min.stk_auction(trade_date=trade_date)
    except Exception:
        return {}
    if not isinstance(auc, pd.DataFrame):
        return {}
    if auc is None or auc.empty:
        return {}
    out: Dict[str, dict] = {}
    for _, r in auc.iterrows():
        code = r.get("ts_code")
        if not code:
            continue
        pre = float(r.get("pre_close") or 0)
        price = float(r.get("price") or 0)
        pct = (price - pre) / pre * 100 if pre > 0 else 0.0
        out[str(code)] = {"pct": pct, "amount": float(r.get("amount") or 0)}
    AUCTION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path = cache_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        tmp_path.replace(cache_path)
    except Exception:
        pass
    return out


def _fetch_daily_open_close_map(pro, trade_date: str) -> Dict[str, Tuple[float, float]]:
    cache_path = DAILY_OC_CACHE_DIR / f"{trade_date}.json"
    if cache_path.is_file():
        try:
            with open(cache_path, encoding="utf-8") as f:
                raw = json.load(f)
            return {str(k): (float(v[0]), float(v[1])) for k, v in raw.items()}
        except Exception:
            try:
                cache_path.unlink()
            except Exception:
                pass
    try:
        df = pro.daily(trade_date=trade_date, fields="ts_code,open,close")
    except Exception:
        return {}
    if not isinstance(df, pd.DataFrame):
        return {}
    if df is None or df.empty:
        return {}
    out: Dict[str, Tuple[float, float]] = {}
    for _, row in df.iterrows():
        code = str(row.get("ts_code") or "").strip()
        if not code:
            continue
        try:
            open_p = float(row.get("open") or 0)
            close_p = float(row.get("close") or 0)
        except Exception:
            continue
        out[code] = (open_p, close_p)
    DAILY_OC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        tmp_path = cache_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        tmp_path.replace(cache_path)
    except Exception:
        pass
    return out


def calibration_single_day(
    pro,
    pro_min,
    trade_date: str,
    *,
    exclude_yizi: bool,
    workers: int = 16,
    verbose: bool = True,
) -> Tuple[Dict[str, List[float]], Dict[str, int], int]:
    """
    单个交易日：涨停池 + 竞价 + 日线收盘>开盘 → 各桶有效竞价涨幅样本。
    返回 (各桶列表, 各桶剔除一字计数, 当日涨停池行数)
    """
    buckets: Dict[str, List[float]] = {k: [] for k in ["首板", "2板", "3板", "4板", "5板+"]}
    yz_skipped: Dict[str, int] = {k: 0 for k in buckets}
    total_rows = 0

    if verbose:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在处理交易日: {trade_date} ...", flush=True)
    try:
        df_zt = pro.limit_list_d(trade_date=trade_date, limit_type="U")
    except Exception:
        df_zt = None
    if df_zt is None or df_zt.empty:
        return buckets, yz_skipped, total_rows
    if "limit_times" not in df_zt.columns:
        df_zt = df_zt.copy()
        df_zt["limit_times"] = 1
    df_zt["limit_times"] = pd.to_numeric(df_zt["limit_times"], errors="coerce").fillna(1).astype(int)

    auc_map = _fetch_auction_map(pro_min, trade_date)
    daily_oc_map = _fetch_daily_open_close_map(pro, trade_date)
    if not daily_oc_map:
        return buckets, yz_skipped, total_rows

    for _, row in df_zt.iterrows():
        code = str(row.get("ts_code") or "").strip()
        if not code:
            continue
        total_rows += 1
        lt = int(row.get("limit_times") or 1)
        if code not in auc_map:
            continue
        pct = float(auc_map[code]["pct"])
        if exclude_yizi and pct >= 9.5:
            bk = _board_bucket(lt)
            yz_skipped[bk] = yz_skipped.get(bk, 0) + 1
            continue
        oh = daily_oc_map.get(code)
        if oh is None:
            continue
        open_p, close_p = oh
        if open_p <= 0 or close_p <= open_p:
            continue
        bk = _board_bucket(lt)
        buckets[bk].append(pct)

    return buckets, yz_skipped, total_rows


def _calibration_single_day_fresh(
    trade_date: str,
    *,
    exclude_yizi: bool,
    workers: int,
) -> Tuple[str, Dict[str, List[float]], Dict[str, int], int]:
    ts.set_token(TOKEN)
    tss.set_token(TOKEN_MIN)
    pro = ts.pro_api()
    pro_min = tss.pro_api()
    buckets, yz_skipped, total_rows = calibration_single_day(
        pro,
        pro_min,
        trade_date,
        exclude_yizi=exclude_yizi,
        workers=workers,
        verbose=True,
    )
    return trade_date, buckets, yz_skipped, total_rows


def _day_entry_from_result(
    trade_date: str,
    buckets: Dict[str, List[float]],
    yz_skipped: Dict[str, int],
    total_rows: int,
) -> Dict[str, Any]:
    return {
        "date": trade_date,
        "buckets": {k: list(v) for k, v in buckets.items()},
        "yz_skipped": dict(yz_skipped),
        "total_rows": int(total_rows),
    }


def _aggregate_day_entries(day_entries: List[Dict[str, Any]]) -> Tuple[Dict[str, List[float]], Dict[str, int], int]:
    buckets: Dict[str, List[float]] = {k: [] for k in ["首板", "2板", "3板", "4板", "5板+"]}
    yz_skipped: Dict[str, int] = {k: 0 for k in buckets}
    total_rows = 0
    for d in day_entries:
        for k, vals in d.get("buckets", {}).items():
            buckets.setdefault(k, []).extend(vals)
        for k, n in d.get("yz_skipped", {}).items():
            yz_skipped[k] = yz_skipped.get(k, 0) + int(n)
        total_rows += int(d.get("total_rows", 0))
    return buckets, yz_skipped, total_rows


def _load_cache() -> Optional[Dict[str, Any]]:
    if not CACHE_PATH.is_file():
        return None
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(
    *,
    end_date: str,
    trade_days: int,
    exclude_yizi: bool,
    day_entries: List[Dict[str, Any]],
) -> None:
    payload = {
        "version": CACHE_VERSION,
        "end_date": end_date,
        "trade_days": trade_days,
        "exclude_yizi": exclude_yizi,
        "days": day_entries,
    }
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def calibration_from_market_backtest(
    pro,
    pro_min,
    *,
    end_date: str,
    trade_days: int,
    exclude_yizi: bool,
    workers: int = 16,
) -> Tuple[Dict[str, List[float]], Dict[str, int], int, List[Dict[str, Any]]]:
    """
    全量：逐日回溯，返回 (各桶竞价涨幅列表, 各桶剔除一字计数, 总扫描涨停行数, 每日缓存条目)
    """
    days = _get_trade_days(pro, end_date, trade_days)
    day_entries: List[Dict[str, Any]] = []

    max_day_workers = min(6, max(1, len(days)))
    with ThreadPoolExecutor(max_workers=max_day_workers) as ex:
        futures = {
            ex.submit(
                _calibration_single_day_fresh,
                td,
                exclude_yizi=exclude_yizi,
                workers=workers,
            ): td
            for td in days
        }
        tmp: Dict[str, Dict[str, Any]] = {}
        for fut in as_completed(futures):
            td = futures[fut]
            try:
                day, b, y, tr = fut.result()
                tmp[day] = _day_entry_from_result(day, b, y, tr)
            except Exception as e:
                print(f"[Error] 处理交易日 {td} 失败: {e}", flush=True)
                tmp[td] = _day_entry_from_result(
                    td,
                    {k: [] for k in ["首板", "2板", "3板", "4板", "5板+"]},
                    {k: 0 for k in ["首板", "2板", "3板", "4板", "5板+"]},
                    0,
                )

    day_entries = [tmp[td] for td in days if td in tmp]

    buckets, yz_skipped, total_rows = _aggregate_day_entries(day_entries)
    return buckets, yz_skipped, total_rows, day_entries


def calibration_with_cache(
    pro,
    pro_min,
    *,
    end_date: str,
    trade_days: int,
    exclude_yizi: bool,
    workers: int,
    use_cache: bool,
    rebuild_cache: bool,
) -> Tuple[Dict[str, List[float]], Dict[str, int], int, str]:
    """
    返回 (buckets, yz_skipped, total_rows, mode)
    mode: cache_hit | incremental | full
    """
    target_days = _get_trade_days(pro, end_date, trade_days)
    if not target_days:
        empty = {k: [] for k in ["首板", "2板", "3板", "4板", "5板+"]}
        yz0 = {k: 0 for k in empty}
        return empty, yz0, 0, "full"

    if rebuild_cache or not use_cache:
        buckets, yz_skipped, total_rows, day_entries = calibration_from_market_backtest(
            pro,
            pro_min,
            end_date=end_date,
            trade_days=trade_days,
            exclude_yizi=exclude_yizi,
            workers=workers,
        )
        _save_cache(
            end_date=end_date,
            trade_days=trade_days,
            exclude_yizi=exclude_yizi,
            day_entries=day_entries,
        )
        return buckets, yz_skipped, total_rows, "full"

    cached = _load_cache()
    if (
        cached
        and int(cached.get("version", 0)) == CACHE_VERSION
        and int(cached.get("trade_days", 0)) == trade_days
        and bool(cached.get("exclude_yizi")) == exclude_yizi
    ):
        cds = [str(d.get("date", "")) for d in cached.get("days", [])]
        if cds == target_days:
            b, y, tr = _aggregate_day_entries(cached["days"])
            print(
                f"[缓存] 窗口已与 {end_date} 对齐（{trade_days} 个交易日），跳过 API 逐日回溯。",
                flush=True,
            )
            return b, y, tr, "cache_hit"

        if (
            len(cds) == trade_days
            and len(target_days) == trade_days
            and cds[1:] == target_days[:-1]
        ):
            new_td = target_days[-1]
            print(
                f"[增量] 仅拉取新交易日 {new_td}（滑窗：丢弃 {cds[0]}）",
                flush=True,
            )
            b, y, tr = calibration_single_day(
                pro,
                pro_min,
                new_td,
                exclude_yizi=exclude_yizi,
                workers=workers,
                verbose=True,
            )
            new_entry = _day_entry_from_result(new_td, b, y, tr)
            old_days = list(cached.get("days", []))
            if len(old_days) != trade_days:
                pass  # 缓存条数异常，落到下方全量
            else:
                day_entries = old_days[1:] + [new_entry]
                _save_cache(
                    end_date=end_date,
                    trade_days=trade_days,
                    exclude_yizi=exclude_yizi,
                    day_entries=day_entries,
                )
                agg_b, agg_y, agg_tr = _aggregate_day_entries(day_entries)
                return agg_b, agg_y, agg_tr, "incremental"

    print(
        f"[全量] 无可用缓存或窗口无法增量衔接，回溯 {trade_days} 个交易日至 {end_date} ...",
        flush=True,
    )
    buckets, yz_skipped, total_rows, day_entries = calibration_from_market_backtest(
        pro,
        pro_min,
        end_date=end_date,
        trade_days=trade_days,
        exclude_yizi=exclude_yizi,
        workers=workers,
    )
    _save_cache(
        end_date=end_date,
        trade_days=trade_days,
        exclude_yizi=exclude_yizi,
        day_entries=day_entries,
    )
    return buckets, yz_skipped, total_rows, "full"


def _print_report(
    buckets: Dict[str, List[float]],
    yz_skipped: Dict[str, int],
    total_rows: int,
    end_date: str,
    trade_days: int,
    cache_mode: str = "",
) -> None:
    order = ["2板", "3板", "4板", "5板+", "首板"]
    print("=== 当前校准值（30日实战经验 · 市场回溯）===")
    if cache_mode:
        hint = {"cache_hit": "（命中本地缓存，未重复拉取 30 日）", "incremental": "（增量：仅新交易日入库）", "full": "（全量回溯已写入 calibration_cache.json）"}.get(
            cache_mode, ""
        )
        if hint:
            print(hint)
    print(f"窗口：截至 {end_date} 向前 {trade_days} 个交易日 | 条件：收盘>开盘 | 剔除竞价≥9.5%一字（可操作样本）")
    print(f"扫描涨停池行数（去重前累计）≈ {total_rows}")
    print()

    for k in order:
        samples = buckets.get(k, [])
        m = _median(samples)
        yz = yz_skipped.get(k, 0)
        if not samples:
            print(f"{k}：0 条有效样本（另剔除一字约 {yz} 条）→ 使用兜底：首板/低吸 3%，其余参考 2.5%~3.5% 黄金底线或上桶")
            continue
        pcts = sorted(samples)
        print(f"\n{k}：{len(samples)} 条有效样本（另剔除一字 {yz} 条）")
        print(f"  涨幅中位数 = {m:+.2f}%  ← 速查卡「当前校准值」")
        print(f"  样本涨幅（升序）：{[round(p, 2) for p in pcts[:20]]}{'...' if len(pcts) > 20 else ''}")


# ── 旧版：经验库表格中位数（仅 --legacy 对照）──────────────────


def legacy_from_experience_md() -> None:
    text = open(EXP_PATH, encoding="utf-8").read()
    section = re.search(r"## 竞价阈值校准记录(.*?)(?=\n## )", text, re.DOTALL)
    if not section:
        print("未找到经验库「竞价阈值校准记录」")
        return
    rows = section.group(1)
    hits: Dict[str, List[Tuple[float, str, str]]] = {}
    hits_yz: Dict[str, List] = {}

    for line in rows.splitlines():
        is_hit = "**命中**" in line
        is_yz = "**命中（一字板）**" in line
        if not is_hit and not is_yz:
            continue

        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 7:
            continue
        board_raw = cols[2].strip()
        pct_raw = cols[5].strip()
        m = re.search(r"([+-]?/d+/.?/d*)", pct_raw.replace("%", ""))
        if not m:
            continue
        pct = float(m.group(1))
        b = re.search(r"(/d+)", board_raw)
        if not b:
            continue
        n = int(b.group(1))
        if n <= 1:
            key = "首板"
        elif n == 2:
            key = "2板"
        elif n == 3:
            key = "3板"
        elif n == 4:
            key = "4板"
        else:
            key = "5板+"
        entry = (pct, cols[1].strip(), cols[0].strip())
        if is_yz or pct >= 9.5:
            hits_yz.setdefault(key, []).append(entry)
        else:
            hits.setdefault(key, []).append(entry)

    print("=== [legacy] 经验库「命中」非一字板涨幅中位数（旧逻辑，仅供参考）===")
    for k in ["2板", "3板", "4板", "5板+", "首板"]:
        samples = hits.get(k, [])
        if not samples:
            print(f"{k}：无样本")
            continue
        pcts = sorted([s[0] for s in samples])
        n = len(pcts)
        med = pcts[n // 2] if n % 2 == 1 else (pcts[n // 2 - 1] + pcts[n // 2]) / 2
        print(f"{k}：{n} 条，中位数 = {med:+.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser(description="竞价涨幅校准：默认 30 交易日市场回溯")
    ap.add_argument("--end-date", default="", help="窗口末端交易日 YYYYMMDD，默认最近一个交易日")
    ap.add_argument("--trade-days", type=int, default=30, help="回溯交易日数量，默认 30")
    ap.add_argument(
        "--include-yizi",
        action="store_true",
        help="纳入竞价≥9.5%样本（默认剔除，与速查可操作定义一致）",
    )
    ap.add_argument("--legacy", action="store_true", help="仅打印旧版经验库中位数")
    ap.add_argument("--workers", type=int, default=16, help="并行拉取日线线程数，默认 16")
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用/不读取本地缓存，当次全量回溯（结束后仍写入 calibration_cache.json）",
    )
    ap.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="同 --no-cache：强制重建缓存窗口",
    )
    args = ap.parse_args()

    ts.set_token(TOKEN)
    tss.set_token(TOKEN_MIN)
    pro = ts.pro_api()
    pro_min = tss.pro_api()

    if args.legacy:
        legacy_from_experience_md()
        return

    end_date = args.end_date.strip()
    if not end_date:
        today = datetime.now().strftime("%Y%m%d")
        try:
            df = pro.trade_cal(exchange="SSE", start_date=(datetime.now() - timedelta(days=15)).strftime("%Y%m%d"), end_date=today, is_open="1")
            if isinstance(df, pd.DataFrame) and not df.empty:
                ds = sorted(df["cal_date"].astype(str).str.zfill(8).tolist())
                end_date = ds[-1]
            else:
                end_date = _get_trade_days(pro, today, 1)[-1]
        except Exception:
            trade_days = _get_trade_days(pro, today, 1)
            end_date = trade_days[-1] if trade_days else today

    rebuild = bool(args.rebuild_cache or args.no_cache)
    buckets, yz_skipped, total_rows, mode = calibration_with_cache(
        pro,
        pro_min,
        end_date=end_date,
        trade_days=args.trade_days,
        exclude_yizi=not args.include_yizi,
        workers=max(1, args.workers),
        use_cache=not rebuild,
        rebuild_cache=rebuild,
    )
    _print_report(buckets, yz_skipped, total_rows, end_date, args.trade_days, cache_mode=mode)


if __name__ == "__main__":
    main()
