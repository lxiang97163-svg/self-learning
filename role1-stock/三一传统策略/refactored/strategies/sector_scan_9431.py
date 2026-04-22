# -*- coding: utf-8 -*-
"""所有题材高开板块前三（重构版，9431 的并发化实现）。

改进:
* 并行扫描 ths_index 所有概念 (默认 12 worker)，不再串行。
* JSON 缓存板块结果 (当日内同参数几乎秒出)。
* ``--quick`` 只扫「昨日有涨停股」的概念，大幅提速。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.auction import enrich_auction, fetch_auction  # noqa: E402
from common.config import init_tushare_clients  # noqa: E402
from common.notifier import NotifyOptions, dispatch, parse_notify_args  # noqa: E402
from common.stock_pool import build_pool  # noqa: E402
from common.trading_calendar import build_context  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "jjlive_data"


def _safe_ths_member(pro, ts_code: str):
    if not ts_code or pd.isna(ts_code):
        return None
    try:
        df = pro.ths_member(ts_code=ts_code, fields="con_code")
    except Exception:
        return None
    if df is None or df.empty or "con_code" not in df.columns:
        return None
    return df


def _compute_one_sector(pro, row, auc: pd.DataFrame, hot_rank_map, name_map) -> Optional[Dict]:
    df_members = _safe_ths_member(pro, row["ts_code"])
    if df_members is None:
        return None
    member_codes = df_members["con_code"].tolist()
    df_sector = auc[auc["ts_code"].isin(member_codes)]
    if df_sector.empty:
        return None

    # Float-MV weighted
    if "float_mv" in df_sector.columns and df_sector["float_mv"].sum() > 0:
        valid = df_sector.dropna(subset=["float_mv"])
        weighted = (valid["pct_chg"] * valid["float_mv"]).sum() / valid["float_mv"].sum()
    else:
        weighted = df_sector["pct_chg"].mean()

    amt_top3 = []
    for _, r in df_sector.nlargest(3, "amount_wan").iterrows():
        code = r["ts_code"]
        amt_top3.append(
            {
                "code": code,
                "name": name_map.get(code, "未知"),
                "pct_chg": r["pct_chg"],
                "rank": hot_rank_map.get(code, 9999),
                "amount_wan": int(r["amount_wan"]),
            }
        )
    hs_top3 = []
    for _, r in df_sector.nlargest(3, "turnover_rate").iterrows():
        code = r["ts_code"]
        hs_top3.append(
            {
                "code": code,
                "name": name_map.get(code, "未知"),
                "pct_chg": r["pct_chg"],
                "rank": hot_rank_map.get(code, 9999),
                "turnover_rate": float(r["turnover_rate"]),
            }
        )

    hot_top1 = None
    df_ranked = df_sector[df_sector["ts_code"].isin(hot_rank_map.keys())].copy()
    if not df_ranked.empty:
        df_ranked["hot_rank"] = df_ranked["ts_code"].map(hot_rank_map)
        top_row = df_ranked.nsmallest(1, "hot_rank")
        if not top_row.empty:
            code = top_row["ts_code"].iloc[0]
            hot_top1 = {
                "code": code,
                "name": name_map.get(code, "未知"),
                "pct_chg": float(top_row["pct_chg"].iloc[0]),
                "rank": int(hot_rank_map.get(code, 9999)),
            }

    return {
        "ts_code": row["ts_code"],
        "name": row["name"],
        "weighted_pct": float(weighted),
        "member_count": int(len(df_sector)),
        "amt_top3_stocks": amt_top3,
        "hs_top3_stocks": hs_top3,
        "hot_top1_stock": hot_top1,
    }


def _load_cache(cache_file: Path, today: str, quick: bool) -> Optional[List[Dict]]:
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("date") != today or data.get("quick") != quick:
        return None
    return data.get("results") or None


def _save_cache(cache_file: Path, today: str, quick: bool, results: List[Dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(
            json.dumps({"date": today, "quick": quick, "results": results}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def run() -> int:
    # Fix HIGH #8: single argparse pass — parse all flags once using parse_known_args
    import argparse as _argparse
    _parser = _argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--no-push", action="store_true")
    _parser.add_argument("--output-file", type=str, default=None)
    _parser.add_argument("--quick", action="store_true", help="只扫昨日含涨停股的概念")
    _parser.add_argument("--workers", type=int, default=12, help="并行 worker 数")
    _parser.add_argument("--no-cache", action="store_true", help="忽略当日缓存")
    extra_args, _ = _parser.parse_known_args()
    options = NotifyOptions(no_push=extra_args.no_push, output_file=extra_args.output_file)

    start = time.time()
    cfg, pro, pro_min = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    logger.info("今日: %s 昨日: %s", ctx.today, ctx.yesterday)

    pool = build_pool(pro, yesterday=ctx.yesterday)

    df_auc_raw = fetch_auction(pro_min, ctx.today)
    if df_auc_raw is None:
        logger.warning("⚠️ 无法获取今日竞价数据")
        return 1
    auc = enrich_auction(df_auc_raw, stock_name_map=pool.name_map)
    auc["float_mv"] = auc["ts_code"].map(pool.float_mv_map).fillna(0)

    df_hot = pro.dc_hot(market="A股市场", hot_type="人气榜", trade_date=ctx.yesterday, fields="ts_code,rank")
    hot_rank_map: Dict[str, int] = dict(zip(df_hot["ts_code"], df_hot["rank"])) if df_hot is not None else {}

    df_concepts = pro.ths_index(exchange="A", type="N")
    if df_concepts is None or df_concepts.empty:
        logger.warning("⚠️ 无法获取概念板块数据")
        return 1

    quick = bool(extra_args.quick)
    if quick:
        df_yzt = pro.limit_list_d(trade_date=ctx.yesterday, limit_type="U")
        zt_codes = set(df_yzt["ts_code"]) if df_yzt is not None and not df_yzt.empty else set()
        if zt_codes:
            # Keep concepts containing >=1 昨日涨停股 (smaller universe)
            zt_concepts: List[str] = []
            for _, row in df_concepts.iterrows():
                df_members = _safe_ths_member(pro, row["ts_code"])
                if df_members is None:
                    continue
                if set(df_members["con_code"].tolist()) & zt_codes:
                    zt_concepts.append(row["ts_code"])
            df_concepts = df_concepts[df_concepts["ts_code"].isin(zt_concepts)]
            logger.info("⚡ --quick 模式：剪裁到 %d 个含涨停股的概念", len(df_concepts))

    total = len(df_concepts)
    logger.info("共扫描 %d 个概念板块, workers=%d", total, extra_args.workers)

    cache_file = CACHE_DIR / f"sector_scan_{ctx.today}.json"
    use_cache = not extra_args.no_cache
    cached = _load_cache(cache_file, ctx.today, quick) if use_cache else None

    if cached is not None:
        logger.info("    使用板块扫描本地缓存")
        results = cached
    else:
        results: List[Dict] = []
        done = 0
        with ThreadPoolExecutor(max_workers=extra_args.workers) as pool_exec:
            futures = {
                pool_exec.submit(_compute_one_sector, pro, row, auc, hot_rank_map, pool.name_map): i
                for i, row in df_concepts.iterrows()
            }
            for future in as_completed(futures):
                done += 1
                if done % 80 == 0:
                    logger.info("    已扫描 %d/%d 个概念...", done, total)
                res = future.result()
                if res is not None:
                    results.append(res)

        if use_cache:
            _save_cache(cache_file, ctx.today, quick, results)

    if not results:
        logger.warning("⚠️ 未得到任何有效板块数据")
        return 1

    top3 = sorted(results, key=lambda x: x["weighted_pct"], reverse=True)[:3]

    lines = [f"📊 {ctx.today} 所有题材高开板块前三", "=" * 70, ""]
    for i, sector in enumerate(top3, 1):
        lines.append(f"{i}. {sector['name']} 高开 {sector['weighted_pct']:+.2f}%")
        lines.append(f"   成分股数: {sector['member_count']}只")
        if sector["amt_top3_stocks"]:
            for idx, s in enumerate(sector["amt_top3_stocks"], 1):
                rank_text = f"rank{s['rank']}" if s["rank"] < 9999 else "无rank"
                lines.append(
                    f"   竞价金额第{idx}: {s['name']}({s['code']}) {rank_text} 金额{s['amount_wan']}万 竞价{s['pct_chg']:+.2f}%"
                )
        else:
            lines.append("   竞价金额前三: 无")
        if sector["hs_top3_stocks"]:
            for idx, s in enumerate(sector["hs_top3_stocks"], 1):
                rank_text = f"rank{s['rank']}" if s["rank"] < 9999 else "无rank"
                lines.append(
                    f"   竞价换手第{idx}: {s['name']}({s['code']}) {rank_text} 换手{s['turnover_rate']:.4f}% 竞价{s['pct_chg']:+.2f}%"
                )
        else:
            lines.append("   竞价换手前三: 无")
        if sector["hot_top1_stock"]:
            s = sector["hot_top1_stock"]
            lines.append(f"   人气值第一: {s['name']}({s['code']}) rank{s['rank']} 竞价{s['pct_chg']:+.2f}%")
        else:
            lines.append("   人气值第一: 无")
        lines.append("")

    lines.append(f"⏱️ 耗时: {time.time() - start:.1f}秒")
    lines.append("(研究参考, 不构成投资建议)")

    content = "\n".join(lines)
    dispatch(content, title=f"题材高开前三 {ctx.today}", token=cfg.pushplus_token, options=options)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
