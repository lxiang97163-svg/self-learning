# -*- coding: utf-8 -*-
"""Trap filters and emotion-aware position-size weights — v2.

Rule sources (knowledge base):

* 05_操作模式.md L67-71: 流通 <20亿 且 换手 >20% → 小盘陷阱 (v1).
* 05_操作模式.md L69:    盘子 <10亿 时 "换手极高→容易成三一"（v2 补超小盘）.
*                        进一步：流通 <15亿 无论换手 → ⚠️超小盘（用户校准）.
* 05_操作模式.md L73-76: 分歧/退潮期 + 三一 → 不参与.
* 05_操作模式.md L78-83: 高位多次三一, 买点价值递减 (B点)
    - 第1次 B点：满仓
    - 第2次 B点：半仓
    - 第3次及以后：轻仓或放弃
* 03_情绪系统.md L184-186: 断板次日铁律 → 强制空仓.

All thresholds live here as module constants so strategy scripts don't
scatter magic numbers. Changing a constant only touches one file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)


# ========== 常量阈值（v2 校准，引用知识库）==========
SMALL_CAP_THRESHOLD_YI = 20.0        # 05_操作模式.md L71
HIGH_TURNOVER_THRESHOLD = 20.0       # 05_操作模式.md L71
ULTRA_SMALL_CAP_THRESHOLD_YI = 15.0  # 用户校准: 流通<15亿 无论换手 → 超小盘
# Fix LOW #17: 断板次日已有铁律路径独立处理，从 DANGEROUS_NODES 移除以避免双重标注
DANGEROUS_NODES = frozenset({"分歧", "退潮"})  # 05_操作模式.md L73-76
HIGH_B_POINT_FULL = 1                # 第1次 B点 -> 满仓
HIGH_B_POINT_HALF = 2                # 第2次 B点 -> 半仓
HIGH_B_POINT_LIGHT_MIN = 3           # 第3次及以后 -> 轻仓/放弃


@dataclass(frozen=True)
class TrapFlags:
    """Flags attached to每条推荐; 多个可同时 True.

    v2 adds: ultra_small_cap / dangerous_node_31 / high_b_point_n / zhemao (砸毛).
    Legacy callers reading .any()/.tags() continue to work unchanged.
    """
    small_cap_trap: bool = False
    big_amount_reversal: bool = False
    broken_ladder_next_day: bool = False
    # v2 new
    ultra_small_cap: bool = False
    dangerous_node_31: bool = False
    high_b_point_n: int = 0           # 0 表示非高位三一; 2/3/... 标 N 次 B 点
    zhemao: bool = False               # 砸毛票 (顺位=8), 强制过滤后仍可展示作警告

    def any(self) -> bool:
        return (
            self.small_cap_trap
            or self.big_amount_reversal
            or self.broken_ladder_next_day
            or self.ultra_small_cap
            or self.dangerous_node_31
            or self.high_b_point_n >= 2
            or self.zhemao
        )

    def is_blocking(self) -> bool:
        """是否应从推荐列表硬过滤（而不仅是标记警告）.

        规则：砸毛 + 断板次日 属硬过滤；其他仅警告。
        """
        return self.zhemao or self.broken_ladder_next_day

    def tags(self) -> str:
        parts = []
        if self.broken_ladder_next_day:
            parts.append("⚠️断板次日")
        if self.dangerous_node_31:
            parts.append("⚠️高位三一,赔率低")
        if self.high_b_point_n >= HIGH_B_POINT_LIGHT_MIN:
            parts.append(f"⚠️第{self.high_b_point_n}次B点,轻仓或放弃")
        elif self.high_b_point_n == HIGH_B_POINT_HALF:
            parts.append(f"⚠️第{self.high_b_point_n}次B点,赔率递减")
        if self.ultra_small_cap:
            parts.append("⚠️超小盘")
        if self.small_cap_trap:
            parts.append("⚠️小盘陷阱")
        if self.big_amount_reversal:
            parts.append("⚠️爆量反核")
        if self.zhemao:
            parts.append("⚠️砸毛,不碰")
        return " ".join(parts)


def is_small_cap_trap(circ_mv_yi: Optional[float], turnover_rate: Optional[float]) -> bool:
    """05_操作模式.md L71 默认规则."""
    if circ_mv_yi is None or turnover_rate is None:
        return False
    try:
        return (
            float(circ_mv_yi) > 0
            and float(circ_mv_yi) < SMALL_CAP_THRESHOLD_YI
            and float(turnover_rate) > HIGH_TURNOVER_THRESHOLD
        )
    except (TypeError, ValueError):
        return False


def is_ultra_small_cap(circ_mv_yi: Optional[float]) -> bool:
    """流通 < 15 亿 即视为超小盘 (用户校准规则, 不再看换手)."""
    if circ_mv_yi is None:
        return False
    try:
        return 0 < float(circ_mv_yi) < ULTRA_SMALL_CAP_THRESHOLD_YI
    except (TypeError, ValueError):
        return False


def is_dangerous_node_31(emotion_node: Optional[str]) -> bool:
    """分歧/退潮/断板次日 出现三一 → 危险 (05_操作模式.md L73-76)."""
    if not emotion_node:
        return False
    return emotion_node in DANGEROUS_NODES


def classify_b_point(b_point_count: Optional[int] = None) -> int:
    """Return the high-B-point count to stamp on reason_tag.

    ``b_point_count`` is the N-th time this 题材/个股 hits 三一 recently.
    Values 0 or 1 are treated as 不打标签（首次满仓）.
    Fix MEDIUM #12: parameter type changed to Optional[int] to match actual call sites.
    """
    if b_point_count is None or b_point_count <= 1:
        return 0
    try:
        return int(b_point_count)
    except (TypeError, ValueError):
        return 0


def count_recent_31_hits(
    topic: Optional[str],
    topic_31_history: Optional[Dict[str, int]] = None,
) -> int:
    """Best-effort counter: how many times has this topic seen 三一 in窗口.

    ``topic_31_history`` should be a mapping topic_name -> count (callers
    typically persist this to disk across trading days). If missing, returns 0.
    """
    if not topic or not topic_31_history:
        return 0
    return int(topic_31_history.get(topic, 0))


def is_bigamount_reversal(
    *,
    amount_wan: Optional[float] = None,
    auction_ratio: Optional[float] = None,
    pct_chg: Optional[float] = None,
    amount_wan_threshold: float = 80000.0,
    auction_ratio_threshold: float = 3.0,
    pct_chg_min: float = -5.0,
    pct_chg_max: float = 2.0,
) -> bool:
    """Heuristic "绿三一反核" 留位 (v1 不变)."""
    if amount_wan is None or auction_ratio is None or pct_chg is None:
        return False
    try:
        return (
            float(amount_wan) >= amount_wan_threshold
            and float(auction_ratio) >= auction_ratio_threshold
            and pct_chg_min <= float(pct_chg) <= pct_chg_max
        )
    except (TypeError, ValueError):
        return False


def build_trap_flags(
    *,
    circ_mv_yi: Optional[float],
    turnover_rate: Optional[float],
    emotion_node: Optional[str],
    is_31_candidate: bool = False,
    b_point_count: int = 0,
    rank_label: Optional[str] = None,
    broken_ladder_next_day: bool = False,
    big_amount_reversal: bool = False,
) -> TrapFlags:
    """One-stop builder producing immutable :class:`TrapFlags`.

    Use from strategy scripts instead of hand-building TrapFlags(...) so
    rule changes propagate cleanly.
    """
    return TrapFlags(
        small_cap_trap=is_small_cap_trap(circ_mv_yi, turnover_rate),
        ultra_small_cap=is_ultra_small_cap(circ_mv_yi),
        dangerous_node_31=bool(is_31_candidate and is_dangerous_node_31(emotion_node)),
        high_b_point_n=classify_b_point(b_point_count),
        zhemao=(rank_label == "后排砸毛"),
        broken_ladder_next_day=broken_ladder_next_day,
        big_amount_reversal=big_amount_reversal,
    )


# Emotion-node -> position weight (0.0 = 空仓, 1.0 = 满仓)
_NODE_WEIGHT = {
    "启动": 1.0,
    "发酵": 0.9,        # v2 新加 (发酵=上升加仓)
    "上升": 0.8,
    "高潮": 0.4,
    "分歧": 0.3,
    "退潮": 0.0,
    "断板次日": 0.0,
    "混沌": 0.1,
}


def weight_by_node(node: str) -> float:
    """Position-size weight [0,1] for a given emotion-node label."""
    return _NODE_WEIGHT.get(node, 0.2)


if __name__ == "__main__":
    cases = [(15.0, 25.0), (50.0, 25.0), (15.0, 5.0), (None, None), (12.0, 5.0)]
    for mv, turnover in cases:
        print(
            f"circ_mv={mv} turnover={turnover} -> "
            f"small={is_small_cap_trap(mv, turnover)} ultra={is_ultra_small_cap(mv)}"
        )
    for node in ("启动", "发酵", "上升", "高潮", "分歧", "退潮", "断板次日", "混沌"):
        print(f"node={node} weight={weight_by_node(node)} dangerous={is_dangerous_node_31(node)}")
    print(
        "flags demo:",
        build_trap_flags(
            circ_mv_yi=12.0,
            turnover_rate=10.0,
            emotion_node="分歧",
            is_31_candidate=True,
            b_point_count=3,
            rank_label="后排砸毛",
        ).tags(),
    )
