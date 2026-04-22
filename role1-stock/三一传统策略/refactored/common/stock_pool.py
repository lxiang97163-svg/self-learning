# -*- coding: utf-8 -*-
"""Stock-pool builder shared across strategies.

* ``build_pool`` returns a frozen :class:`StockPool` containing:
    - ``stock_pool``: 主池（过滤 ST/北交所/688/300/301）
    - ``market_pool``: 全市场池（过滤 ST/北交所/688）—— 市场三一使用
    - ``name_map``: ts_code -> name
    - ``circ_mv_map``: ts_code -> 流通市值(亿)
    - ``total_mv_map``: ts_code -> 总市值(亿)
    - ``float_mv_map``: ts_code -> 流通市值(亿，close*float_share 口径)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, Optional

import pandas as pd


@dataclass(frozen=True)
class StockPool:
    stock_pool: FrozenSet[str]
    market_pool: FrozenSet[str]
    name_map: Dict[str, str] = field(default_factory=dict)
    circ_mv_map: Dict[str, float] = field(default_factory=dict)
    total_mv_map: Dict[str, float] = field(default_factory=dict)
    float_mv_map: Dict[str, float] = field(default_factory=dict)

    def name_of(self, ts_code: str) -> str:
        return self.name_map.get(ts_code, "未知")


_EXCLUDE_MAIN_PREFIXES = ("688", "300", "301")
_EXCLUDE_MARKET_PREFIXES = ("688",)


def _filter_base(df_stocks: pd.DataFrame, extra_prefixes: Iterable[str]) -> FrozenSet[str]:
    mask = (
        (~df_stocks["name"].str.contains("ST", na=False))
        & (~df_stocks["ts_code"].str.endswith(".BJ"))
        & (~df_stocks["ts_code"].str.startswith(tuple(extra_prefixes)))
    )
    return frozenset(df_stocks.loc[mask, "ts_code"].tolist())


def build_pool(
    pro,
    *,
    yesterday: Optional[str] = None,
    exclude_cyb: bool = True,
) -> StockPool:
    """Fetch ``stock_basic`` + optional ``daily_basic`` and build the pool.

    ``exclude_cyb=True`` mirrors the original 竞价三一 behaviour (drop 300/301).
    """

    df_stocks = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    if df_stocks is None or df_stocks.empty:
        raise RuntimeError("⚠️ 无法获取 stock_basic 数据")

    main_prefixes = _EXCLUDE_MAIN_PREFIXES if exclude_cyb else _EXCLUDE_MARKET_PREFIXES
    stock_pool = _filter_base(df_stocks, main_prefixes)
    market_pool = _filter_base(df_stocks, _EXCLUDE_MARKET_PREFIXES)
    name_map = dict(zip(df_stocks["ts_code"], df_stocks["name"]))

    circ_mv_map: Dict[str, float] = {}
    total_mv_map: Dict[str, float] = {}
    float_mv_map: Dict[str, float] = {}

    if yesterday is not None:
        df_basic = pro.daily_basic(
            trade_date=yesterday,
            fields="ts_code,circ_mv,total_mv,float_share,close",
        )
        if df_basic is not None and not df_basic.empty:
            df_basic = df_basic.copy()
            df_basic["circ_mv_yi"] = (df_basic["circ_mv"] / 10000).fillna(0)
            df_basic["total_mv_yi"] = (df_basic["total_mv"] / 10000).fillna(0)
            df_basic["float_mv_yi"] = (
                df_basic["float_share"] * df_basic["close"] / 10000
            ).fillna(0)
            circ_mv_map = dict(zip(df_basic["ts_code"], df_basic["circ_mv_yi"]))
            total_mv_map = dict(zip(df_basic["ts_code"], df_basic["total_mv_yi"]))
            float_mv_map = dict(zip(df_basic["ts_code"], df_basic["float_mv_yi"]))

    return StockPool(
        stock_pool=stock_pool,
        market_pool=market_pool,
        name_map=name_map,
        circ_mv_map=circ_mv_map,
        total_mv_map=total_mv_map,
        float_mv_map=float_mv_map,
    )


if __name__ == "__main__":
    from .config import init_tushare_clients  # type: ignore
    from .trading_calendar import build_context  # type: ignore

    cfg, pro, _ = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    pool = build_pool(pro, yesterday=ctx.yesterday)
    print(f"main pool={len(pool.stock_pool)}, market pool={len(pool.market_pool)}")
    print(f"circ_mv_map sample: {list(pool.circ_mv_map.items())[:3]}")
