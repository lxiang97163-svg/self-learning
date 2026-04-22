# -*- coding: utf-8 -*-
"""连板天梯 + 爆量 + 一红定江山（重构版）。"""

from __future__ import annotations

import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.auction import enrich_auction, fetch_auction, wait_for_complete_auction  # noqa: E402
from common.config import init_tushare_clients  # noqa: E402
from common.filters import TrapFlags, is_small_cap_trap  # noqa: E402
from common.notifier import dispatch, parse_notify_args  # noqa: E402
from common.reason_tag import StockInfo, TagContext, build_reason_tag  # noqa: E402
from common.sentiment import judge_emotion_node  # noqa: E402
from common.stock_pool import build_pool  # noqa: E402
from common.trading_calendar import build_context  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


VOL_RATIO_THRESHOLD = 3.0
MAX_MARKET_SCAN = 100


def _build_sector_snapshot(pro, yesterday, auc, df_yzt) -> Dict[str, Dict]:
    sector_open_zt: Dict[str, Dict] = {}
    df_cpt = pro.limit_cpt_list(trade_date=yesterday)
    if df_cpt is None or df_cpt.empty:
        return sector_open_zt
    yester_zt_set = set(df_yzt["ts_code"]) if df_yzt is not None and not df_yzt.empty else set()
    for _, sector in df_cpt.iterrows():
        df_members = pro.ths_member(ts_code=sector["ts_code"], fields="con_code")
        if df_members is None or df_members.empty:
            continue
        codes = df_members["con_code"].tolist()
        df_sec = auc[auc["ts_code"].isin(codes)]
        if df_sec.empty:
            continue
        sector_open_zt[sector["name"]] = {
            "open_pct": df_sec["pct_chg"].mean(),
            "zt_count": sum(1 for c in codes if c in yester_zt_set),
            "codes": codes,
        }
    return sector_open_zt


def _build_sector_map(sector_open_zt: Dict[str, Dict]) -> Dict[str, List[str]]:
    sector_map: Dict[str, List[str]] = defaultdict(list)
    for name, info in sector_open_zt.items():
        for code in info.get("codes", []):
            sector_map[code].append(name)
    return sector_map


def _append_reason_tag(stock, *, category, emotion, sector_open_zt, sectors, reason, circ_mv, turnover_rate):
    sector_name = sectors[0] if sectors and sectors[0] != "无" else None
    sector_info = sector_open_zt.get(sector_name, {}) if sector_name else {}
    flags = TrapFlags(
        small_cap_trap=is_small_cap_trap(circ_mv, turnover_rate),
        broken_ladder_next_day=emotion.is_forced_empty(),
    )
    return build_reason_tag(
        StockInfo(
            code=stock["code"],
            name=stock["name"],
            pct_chg=stock.get("today_pct") or stock.get("pct_chg"),
            circ_mv_yi=circ_mv,
            turnover_rate=turnover_rate,
        ),
        TagContext(
            emotion_node=emotion.node,
            category=category,
            sector_name=sector_name,
            sector_open_pct=sector_info.get("open_pct"),
            sector_zt_count=sector_info.get("zt_count"),
            reason=reason,
            flags=flags,
        ),
    ), flags


def run() -> int:
    start = time.time()
    options = parse_notify_args()

    cfg, pro, pro_min = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    logger.info("今日: %s 昨日交易日: %s", ctx.today, ctx.yesterday)

    wait_for_complete_auction(pro_min, ctx.today, ctx.yesterday)
    pool = build_pool(pro, yesterday=ctx.yesterday)

    # 连板天梯
    logger.info("步骤1: 获取昨日连板天梯...")
    df_ladder = pro.limit_step(trade_date=ctx.yesterday)
    if df_ladder is None or df_ladder.empty:
        logger.error("✗ 连板天梯数据为空")
        return 1
    df_ladder["nums"] = df_ladder["nums"].astype(int)
    df_ladder = df_ladder[df_ladder["ts_code"].isin(pool.stock_pool) & (df_ladder["nums"] < 7)]
    logger.info("✓ 昨日连板天梯: %d只", len(df_ladder))

    # 爆量
    logger.info("步骤2: 计算爆量股票...")
    past_3 = ctx.past_n_dates(3)  # 前3日 (ending day-before-yesterday)
    if not past_3:
        logger.error("✗ 交易日窗口不足")
        return 1
    ladder_codes = df_ladder["ts_code"].tolist()
    df_yday = pro.daily(trade_date=ctx.yesterday, ts_code=",".join(ladder_codes)) if ladder_codes else None
    yday_vol_map = dict(zip(df_yday["ts_code"], df_yday["vol"])) if df_yday is not None else {}

    # Fix HIGH #5: batch fetch historical volume for all ladder codes instead of N+1 queries
    explode_stocks = []
    if ladder_codes and past_3:
        df_hist_all_parts = []
        for i in range(0, len(ladder_codes), 50):
            batch = ladder_codes[i : i + 50]
            df_batch = pro.daily(ts_code=",".join(batch), start_date=past_3[0], end_date=past_3[-1])
            if df_batch is not None and not df_batch.empty:
                df_hist_all_parts.append(df_batch)
        df_hist_all = pd.concat(df_hist_all_parts, ignore_index=True) if df_hist_all_parts else pd.DataFrame()

        for _, row in df_ladder.iterrows():
            code = row["ts_code"]
            if df_hist_all.empty:
                continue
            code_hist = df_hist_all[df_hist_all["ts_code"] == code]
            if code_hist is None or len(code_hist) < 3:
                continue
            avg_vol = code_hist["vol"].mean()
            yday_vol = yday_vol_map.get(code, 0)
            if avg_vol > 0 and yday_vol >= avg_vol * VOL_RATIO_THRESHOLD:
                explode_stocks.append(
                    {
                        "code": code,
                        "name": pool.name_of(code),
                        "nums": int(row["nums"]),
                        "yesterday_vol": yday_vol,
                        "avg_vol_3d": avg_vol,
                        "vol_ratio": yday_vol / avg_vol,
                    }
                )

    # 今日竞价
    logger.info("步骤3: 获取今日竞价数据...")
    df_auc_raw = fetch_auction(pro_min, ctx.today)
    if df_auc_raw is None:
        logger.error("✗ 竞价数据为空")
        return 1
    auc = enrich_auction(df_auc_raw, stock_name_map=pool.name_map)
    auc["circ_mv_yi"] = auc["ts_code"].map(pool.circ_mv_map).fillna(0)

    # 爆量高开 (0-8%)
    explode_high_open = []
    for s in explode_stocks:
        sub = auc[auc["ts_code"] == s["code"]]
        if sub.empty:
            continue
        pct = sub["pct_chg"].iloc[0]
        if 0 < pct <= 8:
            s["today_pct"] = pct
            s["turnover_rate"] = sub["turnover_rate"].iloc[0]
            s["circ_mv"] = pool.circ_mv_map.get(s["code"], 0)
            explode_high_open.append(s)

    # 板块信息
    logger.info("步骤4: 获取板块信息...")
    df_yzt = pro.limit_list_d(trade_date=ctx.yesterday, limit_type="U")
    sector_open_zt = _build_sector_snapshot(pro, ctx.yesterday, auc, df_yzt)
    sector_map = _build_sector_map(sector_open_zt)
    for s in explode_high_open:
        s["sectors"] = sector_map.get(s["code"], ["无"])

    # 一红定江山
    logger.info("步骤5: 一红定江山...")
    yihong_candidates = []
    df_high_open = auc[
        (auc["ts_code"].isin(pool.stock_pool)) & (auc["pct_chg"] > 0) & (auc["pct_chg"] <= 4)
    ]
    batch_codes = df_high_open["ts_code"].tolist()
    past_120 = ctx.past_n_dates(121, end_inclusive=False)

    df_yester_all_for_market = pd.DataFrame()
    if batch_codes and past_120:
        df_yday_parts = []
        for i in range(0, len(batch_codes), 800):
            batch = batch_codes[i : i + 800]
            df_batch = pro.daily(trade_date=ctx.yesterday, ts_code=",".join(batch))
            if df_batch is not None and not df_batch.empty:
                df_yday_parts.append(df_batch)
        if df_yday_parts:
            df_yday_all = pd.concat(df_yday_parts, ignore_index=True).set_index("ts_code")
            df_yester_all_for_market = df_yday_all.copy()
            for i in range(0, len(batch_codes), 50):
                chunk = batch_codes[i : i + 50]
                df_hist = pro.daily(
                    ts_code=",".join(chunk),
                    start_date=past_120[0],
                    end_date=past_120[-1],
                )
                if df_hist is None or df_hist.empty:
                    continue
                for code in chunk:
                    if code not in df_yday_all.index:
                        continue
                    code_hist = df_hist[df_hist["ts_code"] == code]
                    if code_hist.empty:
                        continue
                    high_120 = code_hist["high"].max()
                    limit_up_count = (code_hist["pct_chg"] >= 9.9).sum()
                    yester = df_yday_all.loc[code]
                    auc_price = df_high_open[df_high_open["ts_code"] == code]["price"].iloc[0]
                    if (
                        yester["open"] <= high_120
                        and auc_price > high_120
                        and yester["high"] < high_120
                        and (yester["close"] - high_120) / high_120 > -0.03
                        and limit_up_count > 1
                    ):
                        sub = auc[auc["ts_code"] == code]
                        yihong_candidates.append(
                            {
                                "code": code,
                                "name": pool.name_of(code),
                                "pct_chg": sub["pct_chg"].iloc[0],
                                "today_pct": sub["pct_chg"].iloc[0],
                                "turnover_rate": sub["turnover_rate"].iloc[0],
                                "circ_mv": pool.circ_mv_map.get(code, 0),
                                "sectors": sector_map.get(code, ["无"]),
                            }
                        )

    # 大盘爆量高开 (排除连板)
    logger.info("步骤5.5: 大盘爆量高开 (排除连板)...")
    market_explode_stocks = []
    df_market_high_open = auc[
        (auc["ts_code"].isin(pool.stock_pool))
        & (~auc["ts_code"].isin(ladder_codes))
        & (auc["pct_chg"] > 0)
        & (auc["pct_chg"] <= 8)
    ]
    market_codes_to_check = df_market_high_open["ts_code"].tolist()[:MAX_MARKET_SCAN]
    if past_3:
        # Fix HIGH #5: batch fetch 3-day history for all market codes to avoid N+1 queries
        mkt_codes_missing = [c for c in market_codes_to_check if c not in df_yester_all_for_market.index]
        if mkt_codes_missing:
            df_mkt_missing_parts = []
            for i in range(0, len(mkt_codes_missing), 50):
                batch = mkt_codes_missing[i : i + 50]
                df_mb = pro.daily(ts_code=",".join(batch), trade_date=ctx.yesterday)
                if df_mb is not None and not df_mb.empty:
                    df_mkt_missing_parts.append(df_mb.set_index("ts_code"))
            if df_mkt_missing_parts:
                df_mkt_extra = pd.concat(df_mkt_missing_parts)
                df_yester_all_for_market = pd.concat([df_yester_all_for_market, df_mkt_extra])

        df_mkt_hist_parts = []
        for i in range(0, len(market_codes_to_check), 50):
            batch = market_codes_to_check[i : i + 50]
            df_mh = pro.daily(ts_code=",".join(batch), start_date=past_3[0], end_date=past_3[-1])
            if df_mh is not None and not df_mh.empty:
                df_mkt_hist_parts.append(df_mh)
        df_mkt_hist_all = pd.concat(df_mkt_hist_parts, ignore_index=True) if df_mkt_hist_parts else pd.DataFrame()

        for code in market_codes_to_check:
            if code in df_yester_all_for_market.index:
                yday_vol = df_yester_all_for_market.loc[code, "vol"]
            else:
                continue
            if df_mkt_hist_all.empty:
                continue
            df_hist_3d = df_mkt_hist_all[df_mkt_hist_all["ts_code"] == code]
            if df_hist_3d is None or len(df_hist_3d) < 3:
                continue
            avg_vol = df_hist_3d["vol"].mean()
            if avg_vol > 0 and yday_vol >= avg_vol * VOL_RATIO_THRESHOLD:
                sub = auc[auc["ts_code"] == code]
                market_explode_stocks.append(
                    {
                        "code": code,
                        "name": pool.name_of(code),
                        "yesterday_vol": yday_vol,
                        "avg_vol_3d": avg_vol,
                        "vol_ratio": yday_vol / avg_vol,
                        "today_pct": sub["pct_chg"].iloc[0],
                        "turnover_rate": sub["turnover_rate"].iloc[0],
                        "circ_mv": pool.circ_mv_map.get(code, 0),
                        "sectors": sector_map.get(code, ["无"]),
                    }
                )
    market_explode_stocks = sorted(market_explode_stocks, key=lambda x: x["vol_ratio"], reverse=True)[:5]

    # 涨停原因
    logger.info("步骤6: 获取涨停原因...")
    all_codes = list(
        set(
            [s["code"] for s in explode_high_open]
            + [s["code"] for s in yihong_candidates]
            + [s["code"] for s in market_explode_stocks]
        )
    )
    zt_reason: Dict[str, str] = {}
    if all_codes:
        past_15_start = (datetime.strptime(ctx.yesterday, "%Y%m%d") - timedelta(days=15)).strftime("%Y%m%d")
        df_kpl = pro.kpl_list(
            ts_code=",".join(all_codes), start_date=past_15_start, end_date=ctx.yesterday, list_type="limit_up"
        )
        if df_kpl is not None and not df_kpl.empty:
            for code in all_codes:
                sub = df_kpl[df_kpl["ts_code"] == code]
                if not sub.empty:
                    zt_reason[code] = sub.sort_values("trade_date").iloc[-1].get("lu_desc", "未知")

    # 情绪节点
    emotion = judge_emotion_node(pro, ctx.yesterday, ctx.day_before_yesterday)

    # 构建报告
    lines = [f"📊 {ctx.today} 连板天梯+爆量+一红\n"]
    if emotion.is_forced_empty():
        lines.append("⚠️ 今日情绪=0分, 铁律强制空仓, 以下仅作研究参考。\n")
    lines.append(f"【情绪节点】{emotion.node}({emotion.score}分) — {emotion.evidence}\n")

    def _render_stock(s: dict, *, category: str, extra: str = ""):
        tag, flags = _append_reason_tag(
            s,
            category=category,
            emotion=emotion,
            sector_open_zt=sector_open_zt,
            sectors=s.get("sectors", ["无"]),
            reason=zt_reason.get(s["code"], "未知"),
            circ_mv=s.get("circ_mv"),
            turnover_rate=s.get("turnover_rate"),
        )
        sector_name = s["sectors"][0] if s["sectors"] and s["sectors"][0] != "无" else None
        info = sector_open_zt.get(sector_name, {}) if sector_name else {}
        open_str = f"{info['open_pct']:+.2f}%" if info.get("open_pct") is not None else "-"
        zt_str = f"{info['zt_count']}只" if info.get("zt_count") is not None else "-"
        lines.append(f"  {s['name']}({s['code']})")
        lines.append(f"  所属概念: {'、'.join(s['sectors'][:3])}")
        lines.append(f"  板块今日高开: {open_str}  板块内涨停: {zt_str}")
        lines.append(f"  涨停原因: {zt_reason.get(s['code'], '未知')}")
        lines.append(f"  竞价: {s.get('today_pct', 0):+.2f}%{extra}")
        lines.append(f"  🏷 {tag}")
        if flags.any():
            lines.append(f"  {flags.tags()}")

    if explode_high_open:
        lines.append(f"\n【连板爆量+高开】共{len(explode_high_open)}只")
        nums_groups: Dict[int, List[dict]] = defaultdict(list)
        for s in explode_high_open:
            nums_groups[s["nums"]].append(s)
        for nums in sorted(nums_groups.keys(), reverse=True):
            stocks = sorted(nums_groups[nums], key=lambda x: x["today_pct"], reverse=True)
            lines.append(f"\n🔥 {nums}连板 ({len(stocks)}只)")
            for s in stocks:
                _render_stock(s, category=f"{nums}连板爆量", extra=f" | 爆量 {s['vol_ratio']:.1f}倍")
    else:
        lines.append("\n【连板爆量+高开】今日无")

    if yihong_candidates:
        lines.append(f"\n\n【一红定江山】共{len(yihong_candidates)}只")
        for s in sorted(yihong_candidates, key=lambda x: x["pct_chg"], reverse=True):
            _render_stock(s, category="一红定江山")
    else:
        lines.append("\n\n【一红定江山】今日无")

    if market_explode_stocks:
        lines.append(f"\n\n【大盘爆量高开】(排除连板) 前{len(market_explode_stocks)}只")
        for s in market_explode_stocks:
            _render_stock(s, category="大盘爆量", extra=f" | 爆量 {s['vol_ratio']:.1f}倍")
    else:
        lines.append("\n\n【大盘爆量高开】今日无")

    lines.append(f"\n\n⏱️ 总耗时: {time.time() - start:.1f}秒")
    lines.append("(研究参考, 不构成投资建议)")

    content = "\n".join(lines)
    dispatch(content, title=f"连板爆量+一红 {ctx.today}", token=cfg.pushplus_token, options=options)
    logger.info("✅ 推送完成! 耗时: %.1f秒", time.time() - start)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
