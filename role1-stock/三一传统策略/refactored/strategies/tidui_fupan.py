# -*- coding: utf-8 -*-
"""梯队复盘（重构版）：昨日涨停分析 + Excel 导出 + 推送。

与原脚本相比主要差异:
* token / pushplus 从 config 读取。
* 使用 common.trading_calendar。
* 写文件路径可通过 ``--output-excel`` 覆盖; 默认在当前工作目录。
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import init_tushare_clients  # noqa: E402
from common.notifier import dispatch, parse_notify_args  # noqa: E402
from common.trading_calendar import build_context  # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run() -> int:
    options = parse_notify_args(
        extra_args=[
            (("--output-excel",), {"type": str, "default": None, "help": "Excel 输出路径"}),
        ]
    )
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-excel", type=str, default=None)
    extra, _ = parser.parse_known_args()

    cfg, pro, _ = init_tushare_clients()
    ctx = build_context(pro, cfg=cfg)
    yesterday = ctx.yesterday
    logger.info("今日: %s 昨日交易日: %s", ctx.today, yesterday)

    df_limit = pro.kpl_list(trade_date=yesterday, list_type="limit_up")
    if df_limit is None or df_limit.empty:
        logger.warning("%s 无涨停数据", yesterday)
        return 1

    df = df_limit.copy()
    df["name"] = df["name"].astype(str)
    df = df[~df["name"].str.contains("ST", na=False)]
    if df.empty:
        logger.warning("%s 过滤 ST 后无数据", yesterday)
        return 1

    df["板块"] = df["theme"].fillna("未知")
    df["涨停原因"] = df["lu_desc"].fillna("未知")
    df["连板情况"] = df["status"].fillna("首板").astype(str)
    df["涨停时间"] = df["lu_time"].fillna("未知")
    df["封单额亿"] = df["limit_order"].fillna(0) / 100_000_000.0

    df_basic = pro.daily_basic(trade_date=yesterday, fields="ts_code,circ_mv")
    if df_basic is not None and not df_basic.empty:
        mv_map: Dict[str, float] = dict(zip(df_basic["ts_code"], df_basic["circ_mv"]))
        df["流通市值亿"] = df["ts_code"].map(mv_map).fillna(0) / 10000
    else:
        df["流通市值亿"] = 0.0

    df["封单占比"] = df.apply(
        lambda r: (r["封单额亿"] / r["流通市值亿"] * 100) if r["流通市值亿"] > 0 else 0.0,
        axis=1,
    )

    logger.info("📊 %s 涨停分析", yesterday)

    top2 = df.nlargest(2, "封单额亿")

    # 市场最大封单前两
    push_lines = [f"📊 {yesterday} 涨停分析", "", "=" * 70, "", "🏆 市场最大封单额前两名", ""]
    for rank, (_, row) in enumerate(top2.iterrows(), 1):
        push_lines.append(f"{rank}. {row['name']}({row['ts_code']})")
        push_lines.append(f"   封单额: {row['封单额亿']:.2f}亿 占比: {row['封单占比']:.2f}%")
        push_lines.append(f"   连板情况: {row['连板情况']}")
        push_lines.append(f"   涨停原因: {row['涨停原因']}")
        push_lines.append("")

    push_lines.append("=" * 70)
    push_lines.append("")

    excel_sheets: Dict[str, pd.DataFrame] = {}
    for rank, (_, top_stock) in enumerate(top2.iterrows(), 1):
        reason = top_stock["涨停原因"]
        push_lines.append(f"【第{rank}名涨停原因: {reason}】")
        push_lines.append("")

        sub = df[df["涨停原因"] == reason].copy()
        if sub.empty:
            push_lines.append("无相同涨停原因的股票")
            push_lines.append("")
            continue

        # Fix MEDIUM #11: 连板情况是中文字符串，按 Unicode 排序不等于按连板天数排序
        # 从 limit_times 字段提取数值辅助列做数值排序
        sub = sub.copy()
        sub["_limit_times_num"] = pd.to_numeric(
            sub["limit_times"] if "limit_times" in sub.columns else sub["连板情况"].str.extract(r"(\d+)")[0],
            errors="coerce"
        ).fillna(0).astype(int)
        sub = sub.sort_values(["_limit_times_num", "涨停时间", "封单占比"], ascending=[False, True, False])
        sub = sub.drop(columns=["_limit_times_num"])
        for _, stock in sub.iterrows():
            push_lines.append(f"{stock['name']} {stock['连板情况']}")
            push_lines.append(
                f"  时间: {stock['涨停时间']} | 市值: {stock['流通市值亿']:.1f}亿 | 封单: {stock['封单额亿']:.1f}亿 | 占比: {stock['封单占比']:.1f}%"
            )
            push_lines.append("")

        excel_data = []
        for _, r in sub.iterrows():
            excel_data.append(
                {
                    "股票名称": r["name"],
                    "连板情况": r["连板情况"],
                    "涨停时间": r["涨停时间"],
                    "板块": r["板块"],
                    "涨停原因": r["涨停原因"],
                    "流通市值亿": r["流通市值亿"],
                    "封单额亿": r["封单额亿"],
                    "封单占比%": r["封单占比"],
                }
            )
        safe_name = re.sub(r"[\\/*?:\[\]]", "_", f"第{rank}名_{reason}")[:31]
        excel_sheets[safe_name] = pd.DataFrame(excel_data)
        push_lines.append("-" * 70)
        push_lines.append("")

    push_lines.append("(研究参考, 不构成投资建议)")

    excel_path = Path(extra.output_excel) if extra.output_excel else Path.cwd() / f"涨停分析_{yesterday}.xlsx"
    if excel_sheets:
        with pd.ExcelWriter(str(excel_path), engine="openpyxl") as writer:
            for sheet, df_sheet in excel_sheets.items():
                df_sheet.to_excel(writer, sheet_name=sheet, index=False)
        logger.info("✅ 已保存: %s", excel_path)

    content = "\n".join(push_lines)
    dispatch(content, title=f"涨停分析 {yesterday}", token=cfg.pushplus_token, options=options)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
