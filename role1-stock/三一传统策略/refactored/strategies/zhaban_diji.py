# -*- coding: utf-8 -*-
"""炸板低阶（炸板六原则落地）— v2 新增策略。

知识库依据: outputs/knowledge/structured/06_专项技术.md L287-307.

| 原则 | 评估维度 | 强信号 | 弱信号 |
|------|----------|--------|--------|
| 1 | 炸板时间 | 晚炸 (>=10点) | 早炸 (<10点) |
| 2 | 炸板前封单 | >5亿 | <1亿 |
| 3 | 炸板性质 | 被动 (指数同跌) | 主动 (指数正常) |
| 4 | 放量速度 | 缓慢放量 | 光速放量 (接口暂无) |
| 5 | 盘口变化 | 主力净额向上 | 急速下行 (接口暂无) |
| 6 | 回风情况 | 当日收盘 >= -3% | 长时间回不来 |

原则 4、5 受 tushare 日级接口限制无法精确实现，这里以"昨日收盘 pct"代替
"回风情况"并降权。输出 3 档评级：强 / 中 / 弱。

使用:

    python strategies/zhaban_diji.py              # 正常推送
    python strategies/zhaban_diji.py --no-push    # 只打印
    python strategies/zhaban_diji.py --output-file out.txt

在 ``run_all.py`` 的 ``--only`` 里可指定。
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import init_tushare_clients  # noqa: E402
from common.notifier import dispatch, parse_notify_args  # noqa: E402
from common.stock_pool import build_pool  # noqa: E402
from common.trading_calendar import build_context  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ========== 阈值常量（06_专项技术.md L287-307）==========
ZHA_TIME_LATE_HHMMSS = 100000           # 10:00:00 之后视为晚炸
ZHA_SEAL_STRONG_YI = 5.0                # 炸板前封单 > 5亿 强
ZHA_SEAL_WEAK_YI = 1.0                  # 炸板前封单 < 1亿 弱
INDEX_DROP_THRESHOLD_PCT = -0.5         # 上证下跌 < -0.5% 视为指数同跌 → 被动炸板
HUIFENG_STRONG_PCT = -3.0               # 昨日收盘 >= -3% 视为有效回封
HUIFENG_WEAK_PCT = -7.0                 # 昨日收盘 <= -7% 视为弱
INDEX_CODE = "000001.SH"


@dataclass(frozen=True)
class ZhabanRating:
    code: str
    name: str
    grade: str            # 强 / 中 / 弱
    score: int            # 0-6
    evidence: List[str]


def _read_seal_amount_yi(row: pd.Series) -> Optional[float]:
    """尝试从 ``pro.limit_list_d`` 行里提取封单金额(亿)."""
    for key in ("fd_amount", "seal_amount", "ffd_amount", "lu_limit_order"):
        if key in row and pd.notna(row[key]):
            try:
                return float(row[key]) / 1e8
            except (TypeError, ValueError):
                continue
    return None


def _parse_time_int(value: Any) -> Optional[int]:
    try:
        t = int(value)
        if 0 <= t <= 240000:
            return t
    except (TypeError, ValueError):
        pass
    return None


def _rate_time(time_int: Optional[int]) -> int:
    if time_int is None:
        return 1
    return 2 if time_int >= ZHA_TIME_LATE_HHMMSS else 0


def _rate_seal(seal_yi: Optional[float]) -> int:
    if seal_yi is None:
        return 1
    if seal_yi >= ZHA_SEAL_STRONG_YI:
        return 2
    if seal_yi <= ZHA_SEAL_WEAK_YI:
        return 0
    return 1


def _rate_passive(index_pct: Optional[float]) -> int:
    if index_pct is None:
        return 1
    return 2 if index_pct <= INDEX_DROP_THRESHOLD_PCT else 0


def _rate_huifeng(close_pct: Optional[float]) -> int:
    if close_pct is None:
        return 1
    if close_pct >= HUIFENG_STRONG_PCT:
        return 2
    if close_pct <= HUIFENG_WEAK_PCT:
        return 0
    return 1


def _grade_from_score(score: int) -> str:
    # max=8 (2*4 维度)
    if score >= 6:
        return "强"
    if score >= 3:
        return "中"
    return "弱"


def run() -> int:
    start = time.time()
    options = parse_notify_args()

    cfg, pro, _pro_min = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    logger.info("炸板低阶 | 今日=%s 昨日=%s", ctx.today, ctx.yesterday)

    pool = build_pool(pro, yesterday=ctx.yesterday)

    # 1) 昨日炸板清单
    df_zha = pro.limit_list_d(trade_date=ctx.yesterday, limit_type="Z")
    if df_zha is None or df_zha.empty:
        content = f"📊 {ctx.today} 炸板低阶\n\n昨日无炸板票, 无低阶机会。\n(研究参考, 不构成投资建议)"
        dispatch(content, title=f"炸板低阶 {ctx.today}", token=cfg.pushplus_token, options=options)
        return 0

    # 只保留主池票（排除 ST/688，含 300）
    df_zha = df_zha[df_zha["ts_code"].isin(pool.market_pool)].copy()
    if df_zha.empty:
        content = f"📊 {ctx.today} 炸板低阶\n\n昨日炸板票均不在主池。\n(研究参考, 不构成投资建议)"
        dispatch(content, title=f"炸板低阶 {ctx.today}", token=cfg.pushplus_token, options=options)
        return 0

    codes = df_zha["ts_code"].tolist()

    # 2) 昨日上证指数 (判断被动 vs 主动)
    df_idx = pro.index_daily(ts_code=INDEX_CODE, start_date=ctx.yesterday, end_date=ctx.yesterday)
    index_pct: Optional[float] = None
    if df_idx is not None and not df_idx.empty:
        try:
            index_pct = float(df_idx.iloc[0]["pct_chg"])
        except (TypeError, ValueError, KeyError):
            index_pct = None

    # 3) 昨日个股日线（收盘回风情况）
    df_daily = pro.daily(trade_date=ctx.yesterday, ts_code=",".join(codes))
    pct_map: Dict[str, float] = {}
    if df_daily is not None and not df_daily.empty:
        for _, row in df_daily.iterrows():
            try:
                pct_map[row["ts_code"]] = float(row["pct_chg"])
            except (TypeError, ValueError, KeyError):
                continue

    # 4) 评级每一只
    # Fix MEDIUM #15: validate that key time fields are present in at least one column;
    # if all are absent, raise KeyError with field names instead of silently scoring 0.
    _TIME_FIELD_CANDIDATES = ("first_time", "open_time", "last_time")
    _has_any_time_field = any(f in df_zha.columns for f in _TIME_FIELD_CANDIDATES)
    if not _has_any_time_field:
        raise KeyError(
            f"炸板清单缺少必需的炸板时间字段，期望其中之一: {_TIME_FIELD_CANDIDATES}，"
            f"实际字段: {list(df_zha.columns)}"
        )

    ratings: List[ZhabanRating] = []
    for _, row in df_zha.iterrows():
        code = row["ts_code"]
        name = pool.name_of(code)

        time_int = _parse_time_int(row.get("first_time") or row.get("open_time") or row.get("last_time"))
        seal_yi = _read_seal_amount_yi(row)
        close_pct = pct_map.get(code)

        rates = {
            "时间": _rate_time(time_int),
            "封单": _rate_seal(seal_yi),
            "性质": _rate_passive(index_pct),
            "回封": _rate_huifeng(close_pct),
        }
        score = sum(rates.values())
        grade = _grade_from_score(score)

        # 弱: 跳过
        if grade == "弱":
            continue

        evidence = [
            f"炸板时间={str(time_int).zfill(6) if time_int else '未知'} ({'晚炸' if rates['时间']==2 else '早炸/未知'})",
            f"封单={seal_yi:.2f}亿" if seal_yi is not None else "封单=未知",
            f"指数={index_pct:+.2f}% ({'被动' if rates['性质']==2 else '主动/未知'})",
            f"昨收={close_pct:+.2f}% ({'已回封' if rates['回封']==2 else '偏弱/未知'})",
        ]
        ratings.append(
            ZhabanRating(code=code, name=name, grade=grade, score=score, evidence=evidence)
        )

    ratings.sort(key=lambda r: (-r.score, r.code))

    # 5) 报告
    lines = [f"📊 {ctx.today} 炸板低阶（炸板六原则）\n"]
    lines.append(f"指数{INDEX_CODE} 昨日涨跌={index_pct:+.2f}%" if index_pct is not None else "指数 昨日涨跌=未知")
    lines.append(f"昨日炸板票(主池) {len(df_zha)}只, 入选={len(ratings)}只 (仅保留强/中)\n")

    strong = [r for r in ratings if r.grade == "强"]
    medium = [r for r in ratings if r.grade == "中"]

    if strong:
        lines.append(f"🔥 强: {len(strong)}只 (可关注低阶)")
        for r in strong:
            lines.append(f"  {r.name}({r.code}) score={r.score}/8")
            for ev in r.evidence:
                lines.append(f"    · {ev}")
        lines.append("")
    if medium:
        lines.append(f"⚙️ 中: {len(medium)}只 (观察, 不主动买)")
        for r in medium:
            lines.append(f"  {r.name}({r.code}) score={r.score}/8")
            for ev in r.evidence:
                lines.append(f"    · {ev}")
        lines.append("")

    if not strong and not medium:
        lines.append("今日无强/中评级炸板票。\n")

    lines.append(f"⏱️ 耗时: {time.time() - start:.1f}秒")
    lines.append("(研究参考, 不构成投资建议)")

    dispatch("\n".join(lines), title=f"炸板低阶 {ctx.today}", token=cfg.pushplus_token, options=options)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
