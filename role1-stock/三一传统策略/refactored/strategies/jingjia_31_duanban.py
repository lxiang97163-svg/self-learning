# -*- coding: utf-8 -*-
"""竞价三一 + 断板弱转强（重构 v2 策略层增强）。

相对 v1 的新增策略行为:
* 断板次日铁律硬拦截：推荐列表清空 + 顶端单行告警 + 原始数据折叠到研究区。
* 情绪节点按用户校准阈值 (见 common.sentiment v2)。
* 三一比较范围补全：300三一 / 创业板三一 / 票池三一（若 config.local.json 配置了 watchlist）。
* 多题材共振：同一只股命中 >=2 个主流题材 (topic_strength 前 5) → 💎双主线共振。
* 顺位分级：推荐上挂 妖股/市场龙头/题材龙头/核心票/... — 砸毛强制过滤。
* 高位三一 B 点递减：同一题材 N>=2 次 三一 → ⚠️第N次B点, 赔率递减。
* 超小盘：流通<15亿 无论换手 → ⚠️超小盘。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 允许 python strategies/xxx.py 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.auction import enrich_auction, fetch_auction, wait_for_complete_auction  # noqa: E402
from common.config import CONFIG_FILENAME, DEFAULT_SEARCH_DIRS, init_tushare_clients  # noqa: E402
from common.filters import (  # noqa: E402
    TrapFlags,
    build_trap_flags,
    is_dangerous_node_31,
)
from common.notifier import dispatch, parse_notify_args  # noqa: E402
from common.reason_tag import (  # noqa: E402
    RANK_ZHEMAO,
    StockInfo,
    TagContext,
    build_reason_tag,
    judge_rank,
)
from common.sentiment import judge_emotion_node  # noqa: E402
from common.stock_pool import build_pool  # noqa: E402
from common.trading_calendar import build_context  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ========== 本模块阈值 ==========
CYB_PREFIXES = ("300", "301")
HS300_INDEX = "399300.SZ"  # 沪深300 指数
TOPIC_TOP_N = 5            # 多题材共振识别范围：前 N 个主流题材


def _load_watchlist_from_config() -> List[str]:
    """Read ``watchlist`` from ``config.local.json`` if present, else []."""
    for base in DEFAULT_SEARCH_DIRS:
        path = base / CONFIG_FILENAME
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
                wl = data.get("watchlist") or []
                return [str(c).strip().upper() for c in wl if c]
            except (OSError, json.JSONDecodeError):
                pass
    return []


def _fetch_hs300_members(pro) -> Set[str]:
    """Return the sets of 沪深300 成份股 codes. Returns empty set on failure."""
    try:
        df = pro.index_weight(index_code=HS300_INDEX)
        if df is None or df.empty:
            return set()
        # most recent trade_date
        latest = df["trade_date"].max()
        return set(df.loc[df["trade_date"] == latest, "con_code"].tolist())
    except Exception:  # noqa: BLE001 — 接口偶尔 404，降级为空集合
        return set()


def _top_by(df: pd.DataFrame, col: str, n: int = 1) -> List[str]:
    if df is None or df.empty or col not in df.columns:
        return []
    return df.nlargest(n, col)["ts_code"].tolist()


def _rank_best(codes: List[str], hot_rank_map, auc_df: pd.DataFrame, n: int) -> List[str]:
    counts = Counter(codes)

    def _key(code: str):
        rank = hot_rank_map.get(code, 9999)
        sub = auc_df[auc_df["ts_code"] == code]
        mv = sub["total_mv_yi"].iloc[0] if not sub.empty and "total_mv_yi" in sub.columns else 999999
        return (-counts[code], rank, mv)

    return sorted(counts.keys(), key=_key)[:n]


def _compute_31_group(
    auc: pd.DataFrame,
    *,
    filter_codes: Iterable[str],
    require_pct_ge: float = 0.0,
    hot_rank_map: Optional[Dict[str, int]] = None,
) -> Tuple[List[str], List[str], Optional[pd.Series]]:
    """Generic 三一 calculator: returns (res_31, res_32, best_auction_ratio_row)."""
    codes_set = set(filter_codes)
    if not codes_set:
        return [], [], None
    df = auc[auc["ts_code"].isin(codes_set) & (auc["pct_chg"] >= require_pct_ge)]
    if df.empty:
        return [], [], None
    t1 = _top_by(df, "amount_wan")
    t2 = _top_by(df, "turnover_rate")
    t3 = _top_by(df, "pct_chg", 3)
    res_31 = _rank_best(t1 + t2, hot_rank_map or {}, auc, 1)
    res_32 = _rank_best(t1 + t2 + t3, hot_rank_map or {}, auc, 2)
    # Fix HIGH #4: guard against missing auction_ratio column
    if "auction_ratio" not in df.columns:
        best_lb = None
    else:
        best_lb = df.loc[df["auction_ratio"].idxmax()] if df["auction_ratio"].max() > 0 else None
    return res_31, res_32, best_lb


def _topic_31_hit_count_map(topic_strength: List[Dict[str, Any]]) -> Dict[str, int]:
    """Track how many consecutive days each topic has been in top-5 (best effort).

    Persisted via ``~/.jingjia_31_duanban_topic_hits.json``. If load/save fails,
    returns the current day's count=1 only (no multi-day accumulation).
    """
    cache_path = Path.home() / ".jingjia_31_duanban_topic_hits.json"
    today_topics = {t["name"] for t in topic_strength}
    today_str = datetime.now().strftime("%Y%m%d")
    hits: Dict[str, int] = {}
    try:
        if cache_path.is_file():
            with cache_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
            last_day = data.get("_day")
            prev_counts: Dict[str, int] = data.get("counts", {})
            if last_day == today_str:
                # Already computed today
                return prev_counts
            for t, c in prev_counts.items():
                if t in today_topics:
                    hits[t] = int(c) + 1
            for t in today_topics:
                hits.setdefault(t, 1)
        else:
            hits = {t: 1 for t in today_topics}
    except (OSError, json.JSONDecodeError, ValueError):
        hits = {t: 1 for t in today_topics}

    try:
        with cache_path.open("w", encoding="utf-8") as fh:
            json.dump({"_day": today_str, "counts": hits}, fh, ensure_ascii=False)
    except OSError:
        pass
    return hits


def run() -> int:
    start = time.time()
    options = parse_notify_args()

    cfg, pro, pro_min = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    logger.info("今日: %s 昨日: %s 前日: %s", ctx.today, ctx.yesterday, ctx.day_before_yesterday)

    logger.info("=" * 70 + "\n数据完整性检测\n" + "=" * 70)
    wait_for_complete_auction(pro_min, ctx.today, ctx.yesterday)
    logger.info("=" * 70 + "\n")

    pool = build_pool(pro, yesterday=ctx.yesterday)

    df_today_raw = fetch_auction(pro_min, ctx.today)
    if df_today_raw is None:
        logger.warning("⚠️ 无法获取今日竞价数据，退出")
        return 1
    df_yester_raw = fetch_auction(pro_min, ctx.yesterday)
    yester_amt_map = (
        dict(zip(df_yester_raw["ts_code"], df_yester_raw["amount"])) if df_yester_raw is not None else {}
    )

    auc = enrich_auction(
        df_today_raw, yester_amt_map=yester_amt_map, stock_name_map=pool.name_map
    )
    auc["circ_mv_yi"] = auc["ts_code"].map(pool.circ_mv_map).fillna(0)
    auc["total_mv_yi"] = auc["ts_code"].map(pool.total_mv_map).fillna(0)
    auc["float_mv"] = auc["ts_code"].map(pool.float_mv_map).fillna(0)

    # 情绪节点 (v2: 传入 auc 和 lookback 以支持 启动/发酵 判据)
    lookback_dates = list(ctx.long_window_dates[-5:]) if ctx.long_window_dates else []
    emotion = judge_emotion_node(
        pro,
        ctx.yesterday,
        ctx.day_before_yesterday,
        today=ctx.today,
        df_auction_today=auc,
        lookback_dates=lookback_dates,
    )
    logger.info("【情绪节点】%s score=%d 证据=%s", emotion.node, emotion.score, emotion.evidence)

    # 涨停/炸板候选
    df_zhaban = pro.limit_list_d(trade_date=ctx.yesterday, limit_type="Z")
    df_prev_zt = pro.limit_list_d(trade_date=ctx.day_before_yesterday, limit_type="U")
    df_cur_zt = pro.limit_list_d(trade_date=ctx.yesterday, limit_type="U")
    zhaban = [s for s in (df_zhaban["ts_code"].tolist() if df_zhaban is not None else []) if s in pool.stock_pool]
    prev_zt_codes = set(df_prev_zt["ts_code"].tolist()) if df_prev_zt is not None and not df_prev_zt.empty else set()
    # Fix HIGH #3: check both None and empty to avoid treating all prev_zt as duanban
    cur_zt_codes = set(df_cur_zt["ts_code"].tolist()) if (df_cur_zt is not None and not df_cur_zt.empty) else set()
    duanban = list((prev_zt_codes & pool.stock_pool) - cur_zt_codes)
    candidates = list(set(zhaban + duanban))

    # 过滤大阴线
    if candidates:
        df_y = pro.daily(trade_date=ctx.yesterday, ts_code=",".join(candidates))
        if df_y is not None and not df_y.empty:
            yin = {
                row["ts_code"]: (row["close"] - row["open"]) / row["open"]
                for _, row in df_y.iterrows()
                if row["open"] > 0
            }
            candidates = [c for c in candidates if yin.get(c, -1) >= -0.06]

    # 人气 / 热股
    df_hot = pro.dc_hot(market="A股市场", hot_type="人气榜", trade_date=ctx.yesterday, fields="ts_code,rank")
    hot_rank_map: Dict[str, int] = dict(zip(df_hot["ts_code"], df_hot["rank"])) if df_hot is not None else {}
    df_ths_hot = pro.ths_hot(trade_date=ctx.yesterday, market="热股", is_new="Y")
    ths_rank_map: Dict[str, int] = (
        dict(zip(df_ths_hot["ts_code"], df_ths_hot["rank"])) if isinstance(df_ths_hot, pd.DataFrame) else {}
    )

    # 涨停原因
    zt_reason: Dict[str, str] = {}
    if candidates:
        start_date = (datetime.strptime(ctx.yesterday, "%Y%m%d") - timedelta(days=15)).strftime("%Y%m%d")
        df_kpl = pro.kpl_list(ts_code=",".join(candidates), start_date=start_date, end_date=ctx.yesterday, list_type="limit_up")
        if df_kpl is not None and not df_kpl.empty:
            for code in candidates:
                sub = df_kpl[df_kpl["ts_code"] == code]
                if not sub.empty:
                    zt_reason[code] = sub.sort_values("trade_date").iloc[-1].get("lu_desc", "未知")

    if cur_zt_codes:
        df_kpl_zt = pro.kpl_list(
            ts_code=",".join(cur_zt_codes),
            start_date=ctx.yesterday,
            end_date=ctx.yesterday,
            list_type="limit_up",
        )
        if df_kpl_zt is not None and not df_kpl_zt.empty:
            for code in cur_zt_codes:
                if code not in zt_reason:
                    sub = df_kpl_zt[df_kpl_zt["ts_code"] == code]
                    if not sub.empty:
                        zt_reason[code] = sub.iloc[0].get("lu_desc", "未知")

    # 题材情绪
    topic_strength: List[Dict[str, Any]] = []
    topic_to_cons: Dict[str, Set[str]] = {}  # 题材名 -> 成分股 set (用于共振)
    df_topics = pro.kpl_concept(trade_date=ctx.yesterday)
    if df_topics is not None:
        # Fix MEDIUM #10: use ThreadPoolExecutor to fetch topic concept members concurrently
        topics_to_fetch = df_topics.head(20)

        def _fetch_topic_cons(topic_row) -> Optional[Dict[str, Any]]:
            try:
                df_cons = pro.kpl_concept_cons(ts_code=topic_row["ts_code"], trade_date=ctx.yesterday)
            except Exception:
                return None
            if df_cons is None or len(df_cons) < 3:
                return None
            cons_codes = set(df_cons["con_code"].tolist())
            avg = auc[auc["ts_code"].isin(cons_codes)]["pct_chg"].mean()
            if pd.notna(avg):
                return {"name": topic_row["name"], "avg_pct": avg, "cons_codes": cons_codes}
            return None

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_topic_cons, row): row for _, row in topics_to_fetch.iterrows()}
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    topic_strength.append({"name": result["name"], "avg_pct": result["avg_pct"]})
                    topic_to_cons[result["name"]] = result["cons_codes"]

        topic_strength = sorted(topic_strength, key=lambda x: x["avg_pct"], reverse=True)[:TOPIC_TOP_N]
    topic_hit_counts = _topic_31_hit_count_map(topic_strength)  # 用于 高位三一 B 点递减

    # 板块核心股 (同花顺 ths_member)
    sector_results: List[Dict[str, Any]] = []
    all_core_stocks: List[Dict[str, Any]] = []
    df_cpt = pro.limit_cpt_list(trade_date=ctx.yesterday)
    if isinstance(df_cpt, pd.DataFrame) and not df_cpt.empty:
        for _, sector in df_cpt.nsmallest(10, "rank").iterrows():
            df_members = pro.ths_member(ts_code=sector["ts_code"], fields="con_code")
            if df_members is None or df_members.empty:
                continue
            codes = df_members["con_code"].tolist()
            df_sec = auc[auc["ts_code"].isin(codes)]
            if df_sec.empty:
                continue
            if "float_mv" in df_sec.columns and df_sec["float_mv"].sum() > 0:
                weighted = (df_sec["pct_chg"] * df_sec["float_mv"]).sum() / df_sec["float_mv"].sum()
            else:
                weighted = df_sec["pct_chg"].mean()
            sector_results.append({"name": sector["name"], "weighted_pct": weighted, "codes": codes})
        sector_results = sorted(sector_results, key=lambda x: x["weighted_pct"], reverse=True)[:5]

        for sector in sector_results:
            sector_stocks = []
            for code in sector["codes"]:
                sub = auc[auc["ts_code"] == code]
                if not sub.empty and ths_rank_map.get(code, 9999) < 9999:
                    sector_stocks.append(
                        {
                            "code": code,
                            "name": pool.name_of(code),
                            "sector_name": sector["name"],
                            "today_pct": sub["pct_chg"].iloc[0],
                            "hot_rank": ths_rank_map[code],
                        }
                    )
            all_core_stocks.extend(sorted(sector_stocks, key=lambda x: x["hot_rank"])[:5])

    # ------ 三一家族：断板混合 + 首板/二板/高度板/弱转强 + 市场 + 300 + 创业板 + 票池 ------
    jingjia_stocks: Set[str] = set()

    # 断板混合
    res_31, res_32, best_lb = _compute_31_group(
        auc, filter_codes=candidates, require_pct_ge=-2, hot_rank_map=hot_rank_map
    )
    jingjia_stocks.update(res_31 + res_32)

    # 市场三一
    market_res_31, market_res_32, market_best_lb = _compute_31_group(
        auc, filter_codes=pool.market_pool, require_pct_ge=0.0, hot_rank_map=hot_rank_map
    )
    jingjia_stocks.update(market_res_31 + market_res_32)

    # 首板/二板/高度板/弱转强
    df_yzt = df_cur_zt if df_cur_zt is not None else pro.limit_list_d(trade_date=ctx.yesterday, limit_type="U")
    board_configs: Dict[str, Set[str]] = {}
    if df_yzt is not None and not df_yzt.empty:
        board_configs = {
            "首板": set(df_yzt[df_yzt["limit_times"] == 1]["ts_code"]),
            "二板": set(df_yzt[df_yzt["limit_times"] == 2]["ts_code"]),
            "高度板": set(df_yzt[df_yzt["limit_times"] >= 3]["ts_code"]),
            "弱转强": set(df_yzt[pd.to_numeric(df_yzt["last_time"], errors="coerce").fillna(0).astype(int) >= 130000]["ts_code"]),
        }
    board_results: Dict[str, Dict[str, Any]] = {}
    for name, codes in board_configs.items():
        r31, r32, blb = _compute_31_group(
            auc, filter_codes=(pool.stock_pool & codes), require_pct_ge=0.0, hot_rank_map=hot_rank_map
        )
        if r31 or r32:
            board_results[name] = {"res_31": r31, "res_32": r32, "best_lb": blb}
            jingjia_stocks.update(r31 + r32)

    # v2 新: 沪深300 / 创业板 / 票池 三一
    hs300_members = _fetch_hs300_members(pro)
    hs300_res_31, hs300_res_32, hs300_best_lb = _compute_31_group(
        auc, filter_codes=hs300_members, require_pct_ge=0.0, hot_rank_map=hot_rank_map
    )
    jingjia_stocks.update(hs300_res_31 + hs300_res_32)

    cyb_codes = {c for c in auc["ts_code"].tolist() if c.startswith(CYB_PREFIXES)}
    cyb_res_31, cyb_res_32, cyb_best_lb = _compute_31_group(
        auc, filter_codes=cyb_codes, require_pct_ge=0.0, hot_rank_map=hot_rank_map
    )
    jingjia_stocks.update(cyb_res_31 + cyb_res_32)

    watchlist = _load_watchlist_from_config()
    watchlist_res_31, watchlist_res_32, watchlist_best_lb = _compute_31_group(
        auc, filter_codes=watchlist, require_pct_ge=-2, hot_rank_map=hot_rank_map
    )
    jingjia_stocks.update(watchlist_res_31 + watchlist_res_32)

    # 交集
    intersection = []
    core_code_set = {s["code"] for s in all_core_stocks}
    for code in jingjia_stocks & core_code_set:
        s = next((x for x in all_core_stocks if x["code"] == code), None)
        if s:
            intersection.append(
                {"code": code, "name": s["name"], "sector": s["sector_name"], "pct_chg": s["today_pct"], "rank": s["hot_rank"]}
            )
    intersection.sort(key=lambda x: x["pct_chg"], reverse=True)

    # 今日推荐
    recommendations: List[Dict[str, Any]] = []
    sources: List[Tuple[Optional[List[str]], str]] = [
        (res_31, "断板混合"),
        (board_results.get("首板", {}).get("res_31"), "首板三一"),
        (board_results.get("二板", {}).get("res_31"), "二板三一"),
        (board_results.get("高度板", {}).get("res_31"), "高度板三一"),
        (board_results.get("弱转强", {}).get("res_31"), "弱转强三一"),
        (market_res_31, "市场三一"),
        (hs300_res_31, "沪深300三一"),
        (cyb_res_31, "创业板三一"),
        (watchlist_res_31, "票池三一") if watchlist else (None, "票池三一"),
    ]
    for res, cat in sources:
        if not res:
            continue
        code = res[0]
        sub = auc[auc["ts_code"] == code]
        if sub.empty:
            continue
        row = sub.iloc[0]
        recommendations.append(
            {
                "code": code,
                "name": pool.name_of(code),
                "cat": cat,
                "pct": row["pct_chg"],
                "rank": hot_rank_map.get(code, 9999),
                "reason": zt_reason.get(code, "未知"),
                "circ_mv": pool.circ_mv_map.get(code, 0),
                "turnover_rate": row.get("turnover_rate", 0),
                "auction_ratio": row.get("auction_ratio", 0),
            }
        )

    # 去重 + 合并 cat
    seen: Dict[str, Dict[str, Any]] = {}
    unique_rec: List[Dict[str, Any]] = []
    for r in recommendations:
        if r["code"] in seen:
            seen[r["code"]]["cat"] += f"+{r['cat']}"
        else:
            seen[r["code"]] = r
            unique_rec.append(r)

    # 板块附加信息
    yester_zt_set = set(df_yzt["ts_code"]) if df_yzt is not None and not df_yzt.empty else set()
    for s in sector_results:
        s["zt_count"] = sum(1 for c in s["codes"] if c in yester_zt_set)
    code_to_sector = {}
    for s in sector_results:
        for c in s["codes"]:
            code_to_sector[c] = {"name": s["name"], "weighted_pct": s["weighted_pct"], "zt_count": s["zt_count"]}
    for r in unique_rec:
        info = code_to_sector.get(r["code"], {})
        r["sector_name"] = info.get("name") or r.get("reason") or "未知"
        r["sector_open"] = info.get("weighted_pct")
        r["sector_zt_count"] = info.get("zt_count")

    # v2: 多题材共振 + 顺位分级 + B 点递减 + reason_tag
    top_topic_names = [t["name"] for t in topic_strength]

    def _topics_hit(code: str) -> List[str]:
        return [t for t in top_topic_names if code in topic_to_cons.get(t, set())]

    def _consecutive_days(code: str) -> int:
        """昨日连板天数 (from df_yzt.limit_times). 未命中返回 0."""
        if df_yzt is None or df_yzt.empty:
            return 0
        sub = df_yzt[df_yzt["ts_code"] == code]
        if sub.empty:
            return 0
        try:
            return int(sub.iloc[0].get("limit_times", 0) or 0)
        except (TypeError, ValueError):
            return 0

    # 题材 N 次三一 -> B 点编号 (N>=2 才打)
    def _b_point_for_code(code: str) -> int:
        topics = _topics_hit(code)
        if not topics:
            return 0
        return max(topic_hit_counts.get(t, 0) for t in topics)

    for r in unique_rec:
        topics = _topics_hit(r["code"])
        r["topics_matched"] = topics

        ladder_info = {
            "is_market_leader": r["code"] in core_code_set and r.get("rank", 9999) <= 3,
            "is_topic_leader": _consecutive_days(r["code"]) >= 3,
            "is_trend": False,  # 接口无趋势判据, 保留
        }
        sector_info = {
            "is_mainstream": r["sector_name"] in top_topic_names,
            "is_bottom_of_sector": False,
        }
        stock_obj = StockInfo(
            code=r["code"],
            name=r["name"],
            pct_chg=r["pct"],
            circ_mv_yi=r["circ_mv"],
            turnover_rate=r.get("turnover_rate"),
            hot_rank=r["rank"],
            auction_ratio=r.get("auction_ratio"),
            consecutive_limit_days=_consecutive_days(r["code"]),
        )
        rank_label = judge_rank(
            stock_obj,
            hot_rank=r["rank"] if r["rank"] < 9999 else None,
            ladder_info=ladder_info,
            sector_info=sector_info,
        )
        b_point = _b_point_for_code(r["code"])
        flags = build_trap_flags(
            circ_mv_yi=r["circ_mv"],
            turnover_rate=r.get("turnover_rate"),
            emotion_node=emotion.node,
            is_31_candidate=True,
            b_point_count=b_point,
            rank_label=rank_label,
            broken_ladder_next_day=emotion.is_forced_empty(),
        )
        r["flags"] = flags
        r["rank_label"] = rank_label
        r["b_point"] = b_point
        base_reason_tag = build_reason_tag(
            stock_obj,
            TagContext(
                emotion_node=emotion.node,
                category=r["cat"],
                sector_name=r["sector_name"],
                sector_open_pct=r["sector_open"],
                sector_zt_count=r["sector_zt_count"],
                reason=r["reason"],
                flags=flags,
                rank_label=rank_label,
                topics_matched=tuple(topics),
            ),
        )
        # Fix LOW #18: append score annotation for easier post-session review
        r["reason_tag"] = f"{base_reason_tag} (score={emotion.score})"

    # v2: 硬过滤（断板次日 + 砸毛）
    forced_empty = emotion.is_forced_empty()
    blocked_rec = [r for r in unique_rec if r["flags"].is_blocking() and not forced_empty]
    kept_rec = [r for r in unique_rec if not r["flags"].is_blocking()] if not forced_empty else []

    # ------ Build report ------
    lines: List[str] = [f"📊 {ctx.today} 竞价统计(快报)\n"]
    lines.append(f"【情绪节点】{emotion.node}({emotion.score}分) — {emotion.evidence}")
    if emotion.ladder_missing:
        lines.append(f"【梯队缺口】9-4-3-1 缺 {list(emotion.ladder_missing)}")
    lines.append("")

    if topic_strength:
        lines.append(
            "【题材情绪】"
            + "、".join(
                [
                    f"{t['name']}({t['avg_pct']:.2f}%, B{topic_hit_counts.get(t['name'], 1)})"
                    for t in topic_strength
                ]
            )
            + "\n"
        )

    # v2: 断板次日铁律硬拦截
    if forced_empty:
        lines.append("⚠️ 情绪=0分（断板次日铁律）| 今日强制空仓 | 以下原始数据仅作研究\n")
        lines.append("⭐ 【今日推荐】")
        lines.append("  今日强制空仓, 无推荐。\n")
        lines.append("==== 以下仅供研究，勿操作 ====\n")

    if intersection:
        lines.append("🎯 【核心股交集】")
        for s in intersection:
            lines.append(f"  {s['name']} {s['sector']} 竞价{s['pct_chg']:+.2f}% rank{s['rank']}")
        lines.append("")
    else:
        lines.append("🎯 【核心股交集】今日无交集\n")

    if not forced_empty:
        lines.append("⭐ 【今日推荐】")
        if kept_rec:
            for r in kept_rec:
                rank_str = f"rank{r['rank']}" if r["rank"] < 9999 else "无rank"
                open_str = f"{r['sector_open']:+.2f}%" if r["sector_open"] is not None else "-"
                zt_str = f"{r['sector_zt_count']}只" if r["sector_zt_count"] is not None else "-"
                lines.append(f"  {r['name']} [{r['cat']}] <{r['rank_label']}>")
                lines.append(f"  竞价{r['pct']:+.2f}% {rank_str} 流通市值{r['circ_mv']:.1f}亿 原因:{r['reason']}")
                lines.append(f"  所属概念:{r['sector_name']} 板块今日高开:{open_str} 板块内涨停:{zt_str}")
                if r.get("topics_matched"):
                    lines.append(f"  命中题材: {'、'.join(r['topics_matched'])}")
                lines.append(f"  🏷 {r['reason_tag']}")
                if r["flags"].any():
                    lines.append(f"  {r['flags'].tags()}")
                lines.append("")
        else:
            lines.append("  今日无推荐\n")

        if blocked_rec:
            lines.append(f"🚫 【硬过滤】{len(blocked_rec)}只砸毛/断板次日, 不展示")
            for r in blocked_rec:
                lines.append(f"  - {r['name']} {r['flags'].tags()}")
            lines.append("")

    # 详细三一分节（始终展示给研究）
    def _add_section(title: str, data: Optional[Dict[str, Any]]):
        if data and data.get("res_31"):
            lines.append(f"【{title}】")
            code = data["res_31"][0]
            lines.append(f"1、三一:{pool.name_of(code)}({zt_reason.get(code, '未知')})")
            if data.get("res_32"):
                lines.append(
                    "2、三二:"
                    + "、".join(f"{pool.name_of(c)}({zt_reason.get(c, '未知')})" for c in data["res_32"])
                )
            else:
                lines.append("2、三二:无")
            if data.get("best_lb") is not None:
                lb = data["best_lb"]
                lines.append(
                    f"3、量比:{lb.get('name', pool.name_of(lb['ts_code']))}({zt_reason.get(lb['ts_code'], '未知')}) 量比:{lb['auction_ratio']:.2f}"
                )
            else:
                lines.append("3、量比:无")
            lines.append("")
        else:
            lines.append(f"【{title}】无\n")

    _add_section("断板混合", {"res_31": res_31, "res_32": res_32, "best_lb": best_lb})
    for b in ("首板", "二板", "高度板", "弱转强"):
        _add_section(f"{b}三一", board_results.get(b, {}))
    _add_section("市场三一", {"res_31": market_res_31, "res_32": market_res_32, "best_lb": market_best_lb})
    _add_section("沪深300三一", {"res_31": hs300_res_31, "res_32": hs300_res_32, "best_lb": hs300_best_lb})
    _add_section("创业板三一", {"res_31": cyb_res_31, "res_32": cyb_res_32, "best_lb": cyb_best_lb})
    if watchlist:
        _add_section("票池三一", {"res_31": watchlist_res_31, "res_32": watchlist_res_32, "best_lb": watchlist_best_lb})

    if sector_results:
        lines.append("\n" + "=" * 70)
        lines.append("📊 板块核心股报告")
        lines.append("=" * 70 + "\n🔥 高开板块前五")
        for s in sector_results:
            lines.append(f"{s['name']} 高开{s['weighted_pct']:.2f}%")
        lines.append("")

    lines.append(f"⏱️ 耗时: {time.time() - start:.1f}秒")
    lines.append("💡 一红定江山正在计算中, 稍后推送...")
    lines.append("\n(研究参考, 不构成投资建议)")

    content = "\n".join(lines)
    dispatch(content, title=f"竞价快报 {ctx.today}", token=cfg.pushplus_token, options=options)
    logger.info("✅ 完成！总耗时: %.1f秒", time.time() - start)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
