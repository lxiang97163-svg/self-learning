# -*- coding: utf-8 -*-
"""Reason-tag builder — v2.

Additions relative to v1:

* ``judge_rank(stock_info, hot_rank, ladder_info, sector_info)`` returns the
  stock's 顺位 label per 06_专项技术.md L7-16
  (妖股 > 市场龙头 > 题材龙头 > 核心票 > 人气中军 > 趋势票 > 前排跟风 > 后排砸毛).
* Multi-topic共振: 若一只票同时命中 ≥2 个主流题材 → reason_tag 追加 ``💎双主线共振``.
* Backwards compatible: TagContext accepts optional ``rank_label`` / ``topics_matched``.

Example output::

    题材启动期+核心票+题材内三一+在储能(+2.30%)+板内涨停4只+流通25亿+rank8+💎双主线共振
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .filters import TrapFlags


# ========== 顺位常量（06_专项技术.md L7-16）==========
RANK_YAOGU = "妖股"              # 完成两次爆量高开转移制
RANK_MARKET_LEADER = "市场龙头"   # 最强市场代表
RANK_TOPIC_LEADER = "题材龙头"    # 题材内连板最高
RANK_CORE = "核心票"              # 高辨识度
RANK_RENQI = "人气中军"           # 日成交 30-80 亿
RANK_TREND = "趋势票"             # 缓慢均线向上
RANK_FOLLOW = "前排跟风"          # 二、三线跟随
RANK_ZHEMAO = "后排砸毛"          # 最低顺位

RANK_PRIORITY: tuple = (
    RANK_YAOGU, RANK_MARKET_LEADER, RANK_TOPIC_LEADER, RANK_CORE,
    RANK_RENQI, RANK_TREND, RANK_FOLLOW, RANK_ZHEMAO,
)

# 多题材共振阈值（用户规范）
RESONANCE_MIN_TOPICS = 2
RESONANCE_TAG = "💎双主线共振"

# 人气中军门槛
RENQI_AMOUNT_YI_MIN = 30.0
RENQI_AMOUNT_YI_MAX = 80.0


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str
    pct_chg: Optional[float] = None
    circ_mv_yi: Optional[float] = None
    turnover_rate: Optional[float] = None
    hot_rank: Optional[int] = None
    auction_ratio: Optional[float] = None
    limit_order_yi: Optional[float] = None  # 封单额(亿)
    amount_yi: Optional[float] = None       # 昨日成交额(亿) — 用于 人气中军 判定
    bao_count: int = 0                      # 历史爆量次数 — 用于 妖股 判定
    consecutive_limit_days: int = 0         # 当前连板天数 — 用于 题材龙头/市场龙头 判定


@dataclass(frozen=True)
class TagContext:
    emotion_node: str = "未知"
    category: Optional[str] = None
    sector_name: Optional[str] = None
    sector_open_pct: Optional[float] = None
    sector_zt_count: Optional[int] = None
    reason: Optional[str] = None
    flags: TrapFlags = TrapFlags()
    extras: Iterable[str] = ()
    # v2 new
    rank_label: Optional[str] = None
    topics_matched: Sequence[str] = ()


def _fmt_pct(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Optional[float], suffix: str, fmt: str = "{:.1f}") -> Optional[str]:
    if value is None:
        return None
    try:
        if float(value) <= 0:
            return None
        return fmt.format(float(value)) + suffix
    except (TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# 顺位分级
# -----------------------------------------------------------------------------

def judge_rank(
    stock_info: StockInfo,
    hot_rank: Optional[int] = None,
    ladder_info: Optional[Dict[str, Any]] = None,
    sector_info: Optional[Dict[str, Any]] = None,
) -> str:
    """Assign a 顺位 label per 06_专项技术.md (L7-16).

    Precedence (most specific wins):
      1. 妖股      — ``stock_info.bao_count >= 2``
      2. 市场龙头   — ``ladder_info.is_market_leader`` (最高板且唯一 / 情绪代表)
      3. 题材龙头   — ``ladder_info.is_topic_leader``  (板块内连板最高)
      4. 核心票    — ``hot_rank <= 30`` 且 所属主流板块
      5. 人气中军   — 日成交额 30-80 亿
      6. 趋势票    — ``ladder_info.is_trend``
      7. 前排跟风   — 题材内跟随 (在 sector 前 30% 但非龙头)
      8. 后排砸毛   — hot_rank > 300 且 不在主流板块 / 板块内排名垫底

    All inputs are tolerantly optional. Returns RANK_FOLLOW when nothing matches.
    """
    ladder_info = ladder_info or {}
    sector_info = sector_info or {}

    # 1) 妖股
    if (stock_info.bao_count or 0) >= 2:
        return RANK_YAOGU

    # 2) 市场龙头
    if ladder_info.get("is_market_leader"):
        return RANK_MARKET_LEADER

    # 3) 题材龙头
    if ladder_info.get("is_topic_leader") or (stock_info.consecutive_limit_days or 0) >= 3:
        # 3连板以上 + 位于主流题材 → 题材龙头 (近似)
        if sector_info.get("is_mainstream"):
            return RANK_TOPIC_LEADER

    # 4) 核心票
    if hot_rank is not None and hot_rank <= 30 and sector_info.get("is_mainstream"):
        return RANK_CORE

    # 5) 人气中军 (日成交 30-80 亿)
    amount_yi = stock_info.amount_yi
    if amount_yi is not None:
        try:
            a = float(amount_yi)
            if RENQI_AMOUNT_YI_MIN <= a <= RENQI_AMOUNT_YI_MAX:
                return RANK_RENQI
        except (TypeError, ValueError):
            pass

    # 6) 趋势票
    if ladder_info.get("is_trend"):
        return RANK_TREND

    # 7) 前排跟风 / 8) 后排砸毛
    if (hot_rank is None or hot_rank > 300) and not sector_info.get("is_mainstream"):
        return RANK_ZHEMAO
    # 板块内排名垫底的，即使 rank 较靠前，也视为砸毛
    if sector_info.get("is_bottom_of_sector"):
        return RANK_ZHEMAO

    return RANK_FOLLOW


# -----------------------------------------------------------------------------
# Tag builder
# -----------------------------------------------------------------------------

def build_reason_tag(stock: StockInfo, ctx: TagContext) -> str:
    """Build a compact one-line reason tag."""

    parts = [f"题材{ctx.emotion_node}期"]

    # 顺位 (v2 新增)
    if ctx.rank_label:
        parts.append(ctx.rank_label)

    if ctx.category:
        parts.append(ctx.category)
    if ctx.sector_name:
        sector_bit = f"在{ctx.sector_name}"
        sector_pct = _fmt_pct(ctx.sector_open_pct)
        if sector_pct:
            sector_bit += f"({sector_pct})"
        parts.append(sector_bit)
    if ctx.sector_zt_count:
        parts.append(f"板内涨停{ctx.sector_zt_count}只")

    mv_bit = _fmt_num(stock.circ_mv_yi, "亿流通")
    if mv_bit:
        parts.append(mv_bit)
    limit_bit = _fmt_num(stock.limit_order_yi, "亿封单")
    if limit_bit:
        parts.append(limit_bit)
    if stock.auction_ratio is not None:
        try:
            ratio = float(stock.auction_ratio)
            if ratio > 0:
                parts.append(f"量比{ratio:.1f}")
        except (TypeError, ValueError):
            pass
    if stock.hot_rank is not None and stock.hot_rank < 9999:
        parts.append(f"rank{stock.hot_rank}")
    if ctx.reason and ctx.reason != "未知":
        parts.append(f"因{ctx.reason}")

    # 多题材共振 (v2 新增)
    topics = [t for t in (ctx.topics_matched or ()) if t]
    if len(topics) >= RESONANCE_MIN_TOPICS:
        parts.append(f"{RESONANCE_TAG}({'/'.join(topics[:3])})")

    if ctx.flags and ctx.flags.any():
        parts.append(ctx.flags.tags())
    for extra in ctx.extras:
        if extra:
            parts.append(str(extra))

    return "+".join(p for p in parts if p)


def build_reason_tag_from_dict(stock_info: Dict[str, Any], context: Dict[str, Any]) -> str:
    """Dict-friendly wrapper so legacy dict-based callers can opt in easily."""

    stock = StockInfo(
        code=str(stock_info.get("code", "")),
        name=str(stock_info.get("name", "")),
        pct_chg=stock_info.get("pct_chg"),
        circ_mv_yi=stock_info.get("circ_mv") or stock_info.get("circ_mv_yi"),
        turnover_rate=stock_info.get("turnover_rate"),
        hot_rank=stock_info.get("hot_rank") or stock_info.get("rank"),
        auction_ratio=stock_info.get("auction_ratio"),
        limit_order_yi=stock_info.get("limit_order_yi"),
        amount_yi=stock_info.get("amount_yi"),
        bao_count=int(stock_info.get("bao_count", 0) or 0),
        consecutive_limit_days=int(stock_info.get("consecutive_limit_days", 0) or 0),
    )
    flags = context.get("flags") or TrapFlags()
    ctx = TagContext(
        emotion_node=str(context.get("emotion_node", "未知")),
        category=context.get("category"),
        sector_name=context.get("sector_name"),
        sector_open_pct=context.get("sector_open_pct"),
        sector_zt_count=context.get("sector_zt_count"),
        reason=context.get("reason"),
        flags=flags if isinstance(flags, TrapFlags) else TrapFlags(),
        extras=tuple(context.get("extras", ())),
        rank_label=context.get("rank_label"),
        topics_matched=tuple(context.get("topics_matched", ())),
    )
    return build_reason_tag(stock, ctx)


if __name__ == "__main__":
    stock = StockInfo(
        code="300750.SZ",
        name="宁德时代",
        circ_mv_yi=25.3,
        hot_rank=8,
        limit_order_yi=1.2,
        amount_yi=55.0,
        consecutive_limit_days=3,
    )
    ctx = TagContext(
        emotion_node="启动",
        category="题材内三一",
        sector_name="储能",
        sector_open_pct=2.3,
        sector_zt_count=4,
        reason="储能",
        rank_label=judge_rank(
            stock,
            hot_rank=stock.hot_rank,
            ladder_info={"is_topic_leader": True},
            sector_info={"is_mainstream": True},
        ),
        topics_matched=("储能", "固态电池"),
    )
    print(build_reason_tag(stock, ctx))
