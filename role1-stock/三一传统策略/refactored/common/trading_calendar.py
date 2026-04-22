# -*- coding: utf-8 -*-
"""Trading calendar helpers.

Wraps ``pro.index_daily('000001.SH', ...)`` with an in-memory cache so
every strategy script can ask for 今日/昨日/前日/过去 N 日 without
re-hitting the API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


_INDEX_CODE = "000001.SH"


@dataclass(frozen=True)
class TradingContext:
    """Immutable snapshot of trading-day information."""

    today: str
    yesterday: Optional[str]           # None when only 1 trading day available
    day_before_yesterday: Optional[str]  # None when fewer than 3 trading days available
    recent_dates: tuple  # desc: newest first
    long_window_dates: tuple  # asc: oldest first (last ~200 days)

    def past_n_dates(self, n: int, end_inclusive: bool = False) -> List[str]:
        """Return the most recent N trading dates relative to yesterday.

        With ``end_inclusive=False`` (default) the window ends the day
        before yesterday — matching the "前 N 日" semantics in 一红+爆量.py.
        """
        if not self.long_window_dates:
            return []
        if end_inclusive:
            return list(self.long_window_dates[-n:])
        return list(self.long_window_dates[-(n + 1):-1])


class _CalendarCache:
    def __init__(self) -> None:
        self._ctx: Optional[TradingContext] = None

    def get(self) -> Optional[TradingContext]:
        return self._ctx

    def set(self, ctx: TradingContext) -> None:
        self._ctx = ctx

    def clear(self) -> None:
        self._ctx = None


_CACHE = _CalendarCache()


def _fetch_with_retry(pro, start_date: str, end_date: str, ts, tss, cfg) -> pd.DataFrame:
    """Fetch index daily with one retry on EmptyDataError."""
    try:
        return pro.index_daily(ts_code=_INDEX_CODE, start_date=start_date, end_date=end_date)
    except pd.errors.EmptyDataError:
        if ts is not None and tss is not None and cfg is not None:
            ts.set_token(cfg.tushare_token)
            tss.set_token(cfg.tushare_min_token)
        return pro.index_daily(ts_code=_INDEX_CODE, start_date=start_date, end_date=end_date)


def build_context(
    pro,
    *,
    today: Optional[str] = None,
    long_days: int = 200,
    recent_days: int = 15,
    ts=None,
    tss=None,
    cfg=None,
    use_cache: bool = True,
) -> TradingContext:
    """Build a :class:`TradingContext`.

    The resulting context is cached; pass ``use_cache=False`` to force refresh.
    """

    if use_cache and _CACHE.get() is not None:
        cached = _CACHE.get()
        if today is None or cached.today == today:
            return cached

    today = today or datetime.now().strftime("%Y%m%d")
    recent_start = (datetime.now() - timedelta(days=recent_days)).strftime("%Y%m%d")

    df_recent = _fetch_with_retry(pro, recent_start, today, ts, tss, cfg)
    if df_recent is None or df_recent.empty:
        raise RuntimeError("⚠️ 无法获取交易日数据")

    recent_sorted = df_recent.sort_values("trade_date", ascending=False)
    recent_dates = recent_sorted["trade_date"].tolist()
    if len(recent_dates) < 1:
        raise RuntimeError("⚠️ 交易日数据不足")
    # Fix MEDIUM #13: warn instead of raise when fewer than 3 dates; callers guard None
    if len(recent_dates) < 3:
        logger.warning("⚠️ 交易日数据少于3个 (%d 个)，day_before_yesterday 可能为 None", len(recent_dates))

    # Fix MEDIUM #13: handle edge cases of fewer than 3 trading days gracefully
    # If today already has index row use it; otherwise shift by one
    if recent_dates[0] == today:
        yesterday = recent_dates[1] if len(recent_dates) >= 2 else None
        day_before_yesterday = recent_dates[2] if len(recent_dates) >= 3 else None
    else:
        yesterday = recent_dates[0]
        day_before_yesterday = recent_dates[1] if len(recent_dates) >= 2 else None

    # Long window ending at yesterday (skip if yesterday is None due to edge case)
    long_start = (datetime.now() - timedelta(days=long_days)).strftime("%Y%m%d")
    if yesterday is not None:
        df_long = _fetch_with_retry(pro, long_start, yesterday, ts, tss, cfg)
        if df_long is None or df_long.empty:
            long_dates: tuple = tuple()
        else:
            long_dates = tuple(df_long.sort_values("trade_date")["trade_date"].tolist())
    else:
        long_dates = tuple()

    ctx = TradingContext(
        today=today,
        yesterday=yesterday,
        day_before_yesterday=day_before_yesterday,
        recent_dates=tuple(recent_dates),
        long_window_dates=long_dates,
    )
    _CACHE.set(ctx)
    return ctx


def clear_cache() -> None:
    """Drop the cached trading context (useful for tests)."""
    _CACHE.clear()


if __name__ == "__main__":
    from .config import init_tushare_clients  # type: ignore

    cfg, pro, _ = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    print(f"today={ctx.today}")
    print(f"yesterday={ctx.yesterday}")
    print(f"day_before_yesterday={ctx.day_before_yesterday}")
    print(f"recent_dates[:3]={ctx.recent_dates[:3]}")
    print(f"long_window len={len(ctx.long_window_dates)}")
