# -*- coding: utf-8 -*-
"""Emotion-node classifier (情绪节点) — v2 校准版.

User-confirmed thresholds (strategy layer v2). All rules reference
``outputs/knowledge/structured/03_情绪系统.md`` (行号附注).

| 节点         | 触发条件                                                                                      | score |
|--------------|-----------------------------------------------------------------------------------------------|-------|
| 启动         | 无明显龙头且今日竞价涨停>=20只 且 跌停<=5只 且 主流题材识别出                                  | 3     |
| 发酵         | 龙头连续封板 >= 2 日 且 今日竞价龙头高开 > +2%                                                  | 2     |
| 高潮         | (v1 规则) 最高板 >= 4 且 涨跌比 >= 1                                                           | 1     |
| 分歧         | 龙头高开但未断 且 9-4-3-1 梯队至少 1 档空缺                                                     | 1     |
| 退潮         | 龙头首次断板                                                                                    | 0     |
| 断板次日     | 昨日最高连板 >= 3 且 该票今日竞价 pct < 0                                                       | 0 (铁律1) |
| 混沌         | 默认                                                                                            | 0     |

知识库对照（行号来自 03_情绪系统.md）:
* L22 启动判据 / L23 发酵 / L24 高潮 / L25 分歧 / L27 退潮
* L132 断板次日 0 分 0 层  (铁律 1)
* 05_操作模式.md L76 ``龙头断板 OR 分歧明显`` → 三一不参与
* 06_专项技术.md L18 顺位表 / L150 梯队 9-4-3-1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


# ========== 阈值常量（v2 校准；可由配置覆盖）==========
# 知识库行号注释
DUANBAN_MIN_HIGH_LADDER = 3          # 03_情绪系统.md L132 断板次日判据
DUANBAN_CUR_PCT_MAX = 0.0            # 竞价 pct < 0 视为断板（用户校准）
FAJIAO_MIN_CONSECUTIVE_DAYS = 2      # 03_情绪系统.md L23 连续封板 ≥2 日
FAJIAO_LEADER_OPEN_MIN = 2.0         # 竞价高开 > +2%
QIDONG_MIN_UP_COUNT = 20             # 03_情绪系统.md L22 今日涨停 ≥20
QIDONG_MAX_DOWN_COUNT = 5            # 跌停 ≤5
GAOCHAO_MIN_HIGH_LADDER = 4          # 最高 >=4 板
GAOCHAO_MIN_RATIO = 1.0              # 涨跌比 >= 1
TUICHAO_RATIO_MAX = 0.5              # 涨跌比 < 0.5 视为退潮迹象
# 9-4-3-1 梯队缺口判据
LADDER_CHECKPOINTS: Tuple[int, ...] = (9, 4, 3, 1)


@dataclass(frozen=True)
class EmotionJudgement:
    """Immutable outcome of the emotion-node classifier."""

    node: str
    score: int
    evidence: str
    # v2 新增字段（不破坏旧调用方；旧代码只读 node/score/evidence）
    leader_broken: bool = False
    ladder_missing: Tuple[int, ...] = field(default_factory=tuple)
    main_topic: Optional[str] = None

    def is_forced_empty(self) -> bool:
        """铁律1：断板次日=强制空仓 (RULE 4 @ L184-186)."""
        return self.node == "断板次日"


# ---------- 内部工具 ----------

def _safe_df(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def _highest_ladder(df_zt: Optional[pd.DataFrame]) -> int:
    df = _safe_df(df_zt)
    if df.empty or "limit_times" not in df.columns:
        return 0
    try:
        return int(pd.to_numeric(df["limit_times"], errors="coerce").max() or 0)
    except (ValueError, TypeError):
        return 0


def _ladder_distribution(df_zt: Optional[pd.DataFrame]) -> Dict[int, int]:
    df = _safe_df(df_zt)
    if df.empty or "limit_times" not in df.columns:
        return {}
    series = pd.to_numeric(df["limit_times"], errors="coerce").dropna().astype(int)
    return series.value_counts().to_dict()


def _find_ladder_gaps(dist: Dict[int, int]) -> Tuple[int, ...]:
    """Return 9-4-3-1 checkpoints that are empty (缺口)."""
    return tuple(lv for lv in LADDER_CHECKPOINTS if dist.get(lv, 0) == 0)


def _leader_codes(df_zt: Optional[pd.DataFrame], high: int) -> List[str]:
    df = _safe_df(df_zt)
    if df.empty or high <= 0 or "limit_times" not in df.columns:
        return []
    return df.loc[df["limit_times"] == high, "ts_code"].tolist()


def _leader_open_pct(leader_codes: List[str], df_auction: Optional[pd.DataFrame]) -> Optional[float]:
    """Return the max竞价 pct_chg over leader codes (None if unavailable)."""
    if not leader_codes or df_auction is None or df_auction.empty:
        return None
    if "ts_code" not in df_auction.columns or "pct_chg" not in df_auction.columns:
        return None
    sub = df_auction[df_auction["ts_code"].isin(leader_codes)]
    if sub.empty:
        return None
    try:
        return float(sub["pct_chg"].max())
    except (TypeError, ValueError):
        return None


def _leader_consecutive_days(
    pro, leader_codes: List[str], lookback_dates: List[str]
) -> int:
    """Best-effort: count how many of the recent `lookback_dates` the leader
    was still among涨停 list. Returns max streak among the given codes.

    ``lookback_dates`` should be ASC (oldest→newest). If lookup fails for any
    date the function degrades gracefully to 0.
    """
    if not leader_codes or not lookback_dates:
        return 0
    best = 0
    for code in leader_codes:
        streak = 0
        # Walk newest → oldest
        for date in reversed(lookback_dates):
            try:
                df = pro.limit_list_d(trade_date=date, limit_type="U")
            except Exception:  # noqa: BLE001 — API 不稳定时降级
                break
            codes = set(df["ts_code"].tolist()) if df is not None and not df.empty else set()
            if code in codes:
                streak += 1
            else:
                break
        best = max(best, streak)
    return best


# ---------- 主判据 ----------

def judge_emotion_node(
    pro,
    yesterday: str,
    day_before_yesterday: str,
    *,
    today: Optional[str] = None,
    df_auction_today: Optional[pd.DataFrame] = None,
    lookback_dates: Optional[List[str]] = None,
    main_topic: Optional[str] = None,
) -> EmotionJudgement:
    """Classify the emotion node using the v2 calibrated thresholds.

    Parameters
    ----------
    pro : tushare pro client
    yesterday, day_before_yesterday : str (YYYYMMDD)
    today : str, optional — needed for "启动/发酵" which examines 今日竞价数据.
    df_auction_today : DataFrame, optional — already-enriched auction snapshot
        (must contain ``ts_code`` + ``pct_chg``). Passing in avoids a second
        ``stk_auction`` call from callers that already have it.
    lookback_dates : List[str], ASC — used for 发酵 连续封板 check.
    main_topic : str, optional — if provided, allows 启动 to succeed
        (启动 rule requires "主流题材识别出").
    """

    df_prev = pro.limit_list_d(trade_date=day_before_yesterday, limit_type="U")
    df_cur = pro.limit_list_d(trade_date=yesterday, limit_type="U")
    df_down = pro.limit_list_d(trade_date=yesterday, limit_type="D")

    prev_high = _highest_ladder(df_prev)
    cur_high = _highest_ladder(df_cur)
    prev_leaders = _leader_codes(df_prev, prev_high)
    cur_leaders = _leader_codes(df_cur, cur_high)

    up_count = len(df_cur) if df_cur is not None else 0
    down_count = len(df_down) if df_down is not None else 0
    ratio = (up_count / max(down_count, 1)) if down_count else up_count

    ladder_dist = _ladder_distribution(df_cur)
    ladder_gaps = _find_ladder_gaps(ladder_dist)

    # Leader-today 高开幅度
    leader_open = _leader_open_pct(prev_leaders, df_auction_today)

    # ============ 0) 断板次日（最高优先级，铁律1）============
    # 前日最高连板票 + 今日竞价 < 0  →  断板次日
    if prev_high >= DUANBAN_MIN_HIGH_LADDER and leader_open is not None and leader_open < DUANBAN_CUR_PCT_MAX:
        return EmotionJudgement(
            node="断板次日",
            score=0,
            evidence=(
                f"前日最高{prev_high}板 今日竞价{leader_open:+.2f}% < 0 "
                f"(铁律1 强制空仓)"
            ),
            leader_broken=True,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # Fix CRITICAL #2: 退化路径仅应在完全无法获取今日竞价数据时触发。
    # 若竞价数据存在但龙头不在竞价列表中（leader_open is None），
    # 不应触发退化路径，以免将昨日断板误判为今日断板次日。
    if prev_high >= DUANBAN_MIN_HIGH_LADDER and leader_open is None and (df_auction_today is None or df_auction_today.empty):
        cur_codes = set(df_cur["ts_code"].tolist()) if df_cur is not None and not df_cur.empty else set()
        highest_broken = bool(prev_leaders) and not (set(prev_leaders) & cur_codes)
        if highest_broken:
            return EmotionJudgement(
                node="断板次日",
                score=0,
                evidence=f"前日最高{prev_high}板今日未涨停 (完全无竞价数据, 退化判断，可信度低)",
                leader_broken=True,
                ladder_missing=ladder_gaps,
                main_topic=main_topic,
            )

    # ============ 1) 退潮：龙头首次断板 ============
    cur_codes = set(df_cur["ts_code"].tolist()) if df_cur is not None and not df_cur.empty else set()
    leader_broken_today = bool(prev_leaders) and not (set(prev_leaders) & cur_codes)
    if leader_broken_today and prev_high >= 2:
        return EmotionJudgement(
            node="退潮",
            score=0,
            evidence=f"龙头首次断板: 前日{prev_high}板今日断, 涨跌比{ratio:.2f}",
            leader_broken=True,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # ============ 2) 发酵：龙头连续封板 ≥2 日 且 今日竞价高开 > +2% ============
    streak = 0
    if cur_leaders and lookback_dates:
        streak = _leader_consecutive_days(pro, cur_leaders, lookback_dates)
    if streak >= FAJIAO_MIN_CONSECUTIVE_DAYS and leader_open is not None and leader_open > FAJIAO_LEADER_OPEN_MIN:
        return EmotionJudgement(
            node="发酵",
            score=2,
            evidence=f"龙头连续封板{streak}日+今日竞价高开{leader_open:+.2f}%",
            leader_broken=False,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # ============ 3) 分歧：龙头高开但未断 + 梯队缺口 ============
    # 昨日龙头今日仍在涨停池 + 9-4-3-1 至少 1 档空
    leader_holds = bool(set(cur_leaders or []) & set(prev_leaders or [])) or (
        cur_high >= prev_high and cur_high >= 2
    )
    if leader_holds and ladder_gaps and leader_open is not None and leader_open > 0:
        return EmotionJudgement(
            node="分歧",
            score=1,
            evidence=f"龙头高开{leader_open:+.2f}%未断+梯队缺{ladder_gaps}",
            leader_broken=False,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # ============ 4) 启动：今日竞价涨停>=20 跌停<=5 主流题材识别 ============
    # 注意：这里的"今日涨停家数"是昨日竞价无法得到的。用 df_auction_today 中 pct_chg>=9.9 的数目作为代理。
    today_aspiring_zt = 0
    today_aspiring_dt = 0
    if df_auction_today is not None and not df_auction_today.empty:
        try:
            today_aspiring_zt = int((df_auction_today["pct_chg"] >= 9.9).sum())
            today_aspiring_dt = int((df_auction_today["pct_chg"] <= -9.9).sum())
        except Exception:  # noqa: BLE001
            pass

    if (
        (prev_high <= 1 or not prev_leaders)
        and today_aspiring_zt >= QIDONG_MIN_UP_COUNT
        and today_aspiring_dt <= QIDONG_MAX_DOWN_COUNT
        and main_topic
    ):
        return EmotionJudgement(
            node="启动",
            score=3,
            evidence=f"今日竞价涨停{today_aspiring_zt}只跌停{today_aspiring_dt}只+主题{main_topic}",
            leader_broken=False,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # Fix HIGH #7: 上升 score=2 高于高潮 score=1，上升应优先匹配
    # ============ 5) 上升（保留 v1 规则作兜底）============
    if cur_high >= prev_high and cur_high >= 2 and ratio >= 3:
        return EmotionJudgement(
            node="上升",
            score=2,
            evidence=f"连板高度{cur_high}>={prev_high}, 涨跌比{ratio:.1f}",
            leader_broken=False,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # ============ 6) 高潮（保留 v1 规则作兜底）============
    if cur_high >= GAOCHAO_MIN_HIGH_LADDER and ratio >= GAOCHAO_MIN_RATIO:
        return EmotionJudgement(
            node="高潮",
            score=1,
            evidence=f"最高{cur_high}板, 涨跌比{ratio:.1f}",
            leader_broken=False,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # ============ 7) 退潮（兜底：涨跌比偏弱或高度回落）============
    if ratio < TUICHAO_RATIO_MAX or (cur_high < prev_high and cur_high <= 2):
        return EmotionJudgement(
            node="退潮",
            score=0,
            evidence=f"高度回落 {prev_high}->{cur_high}, 涨跌比{ratio:.2f}",
            leader_broken=leader_broken_today,
            ladder_missing=ladder_gaps,
            main_topic=main_topic,
        )

    # ============ 8) 默认：混沌 ============
    return EmotionJudgement(
        node="混沌",
        score=0,
        evidence=f"未识别主线, 最高{cur_high}板, 涨停{up_count}跌停{down_count}",
        leader_broken=False,
        ladder_missing=ladder_gaps,
        main_topic=main_topic,
    )


if __name__ == "__main__":
    from .config import init_tushare_clients  # type: ignore
    from .trading_calendar import build_context  # type: ignore

    cfg, pro, _ = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    result = judge_emotion_node(pro, ctx.yesterday, ctx.day_before_yesterday)
    print(f"节点={result.node} score={result.score}")
    print(f"证据: {result.evidence}")
    print(f"强制空仓: {result.is_forced_empty()}")
    print(f"leader_broken: {result.leader_broken} 梯队缺口: {result.ladder_missing}")
