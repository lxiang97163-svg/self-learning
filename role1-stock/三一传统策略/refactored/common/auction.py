# -*- coding: utf-8 -*-
"""Auction (集合竞价) data helpers.

* ``wait_for_complete_auction`` -- the 9:28 data completeness gate used by
  竞价三一 and 一红+爆量.
* ``fetch_auction`` -- cached auction snapshot per date.
* ``enrich_auction`` -- pct_chg / amount_wan / auction_ratio / turnover_rate
  derived columns.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


_AUCTION_CACHE: Dict[str, pd.DataFrame] = {}


def fetch_auction(pro_min, trade_date: str, *, use_cache: bool = True) -> Optional[pd.DataFrame]:
    """Fetch ``stk_auction`` for ``trade_date``. Returns ``None`` on empty."""

    if use_cache and trade_date in _AUCTION_CACHE:
        return _AUCTION_CACHE[trade_date].copy()

    df = pro_min.stk_auction(trade_date=trade_date)
    if df is None or df.empty:
        return None

    if use_cache:
        _AUCTION_CACHE[trade_date] = df.copy()
    return df


def clear_cache() -> None:
    _AUCTION_CACHE.clear()


def wait_for_complete_auction(
    pro_min,
    today: str,
    yesterday: str,
    *,
    deadline_hour: int = 9,
    deadline_minute: int = 28,
    check_interval: int = 10,
    tolerance_pct: float = 2.0,
    verbose: bool = True,
) -> None:
    """Block until auction data is stable or deadline reached.

    Matches the data-completeness logic in original 竞价三一/一红+爆量.
    Caches whichever snapshot wins the race so subsequent callers reuse it.
    """

    now = datetime.now()
    deadline = now.replace(hour=deadline_hour, minute=deadline_minute, second=0, microsecond=0)

    last_known_df: Optional[pd.DataFrame] = None

    while datetime.now() < deadline:
        try:
            df_today = pro_min.stk_auction(trade_date=today)
        except Exception as exc:  # noqa: BLE001 — API 不稳定时重试
            if verbose:
                remaining = int((deadline - datetime.now()).total_seconds())
                logger.warning("⚠️ 获取今日竞价异常: %s，%d 秒后重试", exc, 5)
            time.sleep(5)
            continue

        try:
            df_yester = pro_min.stk_auction(trade_date=yesterday)
        except Exception as exc:  # noqa: BLE001
            if verbose:
                logger.warning("⚠️ 获取昨日竞价异常: %s，%d 秒后重试", exc, 5)
            time.sleep(5)
            continue

        if df_today is None or df_today.empty:
            if verbose:
                remaining = int((deadline - datetime.now()).total_seconds())
                logger.info("⚠️ 等待今日竞价数据... 距 %02d:%02d 还有 %d 秒", deadline_hour, deadline_minute, remaining)
            time.sleep(check_interval)
            continue

        last_known_df = df_today

        if df_yester is None or df_yester.empty:
            if verbose:
                logger.info("⚠️ 昨日竞价数据为空，跳过完整性检测")
            _AUCTION_CACHE[today] = df_today.copy()
            return

        diff_pct = abs(len(df_today) - len(df_yester)) / max(len(df_yester), 1) * 100
        if verbose:
            logger.info("✓ 今:%d 昨:%d 差异:%.2f%%", len(df_today), len(df_yester), diff_pct)

        if diff_pct < tolerance_pct:
            if verbose:
                logger.info("✅ 数据完整性检测通过 (<%.1f%%)", tolerance_pct)
            _AUCTION_CACHE[today] = df_today.copy()
            _AUCTION_CACHE[yesterday] = df_yester.copy()
            return

        time.sleep(check_interval)

    # Fix MEDIUM #9: cache last known data on timeout exit
    if last_known_df is not None and today not in _AUCTION_CACHE:
        _AUCTION_CACHE[today] = last_known_df.copy()
        if verbose:
            logger.warning("⚠️ 已到达截止时间，使用最后读取的竞价数据 (%d 行) 写入缓存。", len(last_known_df))
    elif verbose:
        logger.warning("⚠️ 已到达截止时间，强制继续。")


def enrich_auction(
    df_today_auc: pd.DataFrame,
    *,
    yester_amt_map: Optional[Dict[str, float]] = None,
    stock_name_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """Add derived columns to an auction snapshot.

    * ``name`` — Chinese name (if ``stock_name_map`` provided)
    * ``amount_wan`` — amount / 10000
    * ``pct_chg`` — (price - pre_close) / pre_close * 100
    * ``auction_ratio`` — today.amount / yesterday.amount (``yester_amt_map``)
    * ``turnover_rate`` — NA-filled copy of existing turnover_rate
    """

    df = df_today_auc.copy()
    if stock_name_map is not None:
        df["name"] = df["ts_code"].map(stock_name_map)

    df["amount_wan"] = df["amount"] / 10000
    # Fix HIGH #6: guard against pre_close == 0 to avoid inf/NaN
    safe_pre_close = df["pre_close"].replace(0, float("nan"))
    df["pct_chg"] = (df["price"] - df["pre_close"]) / safe_pre_close * 100

    if yester_amt_map is not None:
        yester_series = df["ts_code"].map(yester_amt_map).fillna(0)
        df["auction_ratio"] = df["amount"] / yester_series.replace(0, 1)
        df.loc[yester_series <= 0, "auction_ratio"] = 0

    if "turnover_rate" in df.columns:
        df["turnover_rate"] = df["turnover_rate"].fillna(0)
    else:
        df["turnover_rate"] = 0.0

    return df


if __name__ == "__main__":
    from .config import init_tushare_clients  # type: ignore
    from .trading_calendar import build_context  # type: ignore

    cfg, pro, pro_min = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    df = fetch_auction(pro_min, ctx.today)
    if df is None:
        print("今日暂无竞价数据")
    else:
        enriched = enrich_auction(df)
        print(f"竞价数据行数: {len(enriched)}")
        print(enriched[["ts_code", "pct_chg", "amount_wan", "turnover_rate"]].head())
