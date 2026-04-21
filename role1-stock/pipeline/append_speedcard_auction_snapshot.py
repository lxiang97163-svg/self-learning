# -*- coding: utf-8 -*-
"""
在速查 md 末尾写入「附录：速查标的·竞价快照」表格。

数据含义（与此前复盘/验证脚本一致）：
  - 文件名 `速查_YYYY-MM-DD.md` 中的日期 = **次交易日**（执行日）。
  - **「当日」竞价**：指 **生成速查当日** 的交易日，即 **文件名日期的前一交易日**
   （`fetch_prev_trade_date(文件名日)`，亦即复盘日）。默认拉取该日的 `stk_auction`（9:25），
    供盘中监控与「昨竞价」对齐。

用法：
  python3 append_speedcard_auction_snapshot.py /path/to/速查_2026-04-21.md
  python3 append_speedcard_auction_snapshot.py /path/to/速查_2026-04-21.md --trade-date 20260420   # 指定竞价数据日

重复运行：会替换 <!-- speedcard-auction-snapshot:start/end --> 之间的内容。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _paths import REVIEW_DIR

from verify_daily import fetch_auction, fetch_prev_trade_date

MARK_START = "<!-- speedcard-auction-snapshot:start -->"
MARK_END = "<!-- speedcard-auction-snapshot:end -->"

# 与速查正文一致：**名称**(ts_code)；兼容部分表格仅 (code) 无加粗名
RE_NAME_CODE = re.compile(r"\*\*([^*]+)\*\*\((\d{6}\.(?:SH|SZ|BJ))\)", re.I)
RE_PARENS_CODE = re.compile(r"\((\d{6}\.(?:SH|SZ|BJ))\)")


def parse_speedcard_date(path: Path) -> str | None:
    """速查_YYYY-MM-DD.md -> YYYYMMDD"""
    m = re.match(r"速查_(\d{4})-(\d{2})-(\d{2})\.md$", path.name, re.I)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}{m.group(3)}"


def extract_codes_and_names(text: str) -> list[tuple[str, str]]:
    """
    返回 [(ts_code, name)]，按文中首次出现顺序去重。
    name 缺省时为「—」。
    """
    seen: dict[str, str] = {}
    for m in RE_NAME_CODE.finditer(text):
        name = m.group(1).strip()
        code = m.group(2).upper()
        if code not in seen:
            seen[code] = name
    if not seen:
        for m in RE_PARENS_CODE.finditer(text):
            code = m.group(1).upper()
            if code not in seen:
                seen[code] = "—"
    return list(seen.items())


def fmt_yyyymmdd(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def build_table(rows: list[tuple[int, str, str, str, str, str]], review_date: str, next_day: str) -> str:
    lines = [
        "",
        "---",
        "",
        "## 附录：速查标的·竞价快照（stk_auction）",
        "",
        f"> **竞价数据日期（当日）**：{fmt_yyyymmdd(review_date)} — **生成速查当日** = 本文件名日期的**前一交易日**"
        f"（次交易日/执行日为 **{fmt_yyyymmdd(next_day)}**）。",
        "> **用途**：盘中监控对齐「昨竞价额、竞价涨幅」；金额单位：亿元（与速查正文一致）。",
        "",
        "| 序号 | 股票 | ts_code | 竞价成交额(亿) | 竞价涨幅(%) | 量比 |",
        "|:---:|:---|:---|:---:|:---:|:---:|",
    ]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | `{r[2]}` | {r[3]} | {r[4]} | {r[5]} |")
    lines.append("")
    return "\n".join(lines)


def strip_old_block(text: str) -> str:
    if MARK_START not in text or MARK_END not in text:
        return text
    out = []
    i = 0
    while i < len(text):
        start = text.find(MARK_START, i)
        if start < 0:
            out.append(text[i:])
            break
        out.append(text[i:start])
        end = text.find(MARK_END, start)
        if end < 0:
            out.append(text[start:])
            break
        i = end + len(MARK_END)
        while i < len(text) and text[i] in "\r\n":
            i += 1
    return "".join(out).rstrip()


def main() -> int:
    ap = argparse.ArgumentParser(description="在速查 md 末尾追加竞价快照表")
    ap.add_argument(
        "speedcard",
        type=Path,
        nargs="?",
        default=None,
        help="速查 md 路径，如 outputs/review/速查_2026-04-21.md",
    )
    ap.add_argument(
        "--trade-date",
        metavar="YYYYMMDD",
        default=None,
        help="竞价数据交易日（默认：文件名日期的前一交易日=生成速查当日/复盘日）",
    )
    ap.add_argument(
        "--stdout-only",
        action="store_true",
        help="只打印表格 Markdown 到 stdout，不写回文件",
    )
    args = ap.parse_args()

    path = args.speedcard
    if path is None:
        print("请指定速查 md 路径。", file=sys.stderr)
        return 2

    path = path.resolve()
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    pairs = extract_codes_and_names(text)
    if not pairs:
        print(f"[跳过] 未从 {path.name} 解析到任何 ts_code。", file=sys.stderr)
        return 1

    next_day = parse_speedcard_date(path)
    if not next_day:
        print(f"[错误] 文件名应为 速查_YYYY-MM-DD.md，当前: {path.name}", file=sys.stderr)
        return 2

    review_date = args.trade_date if args.trade_date else fetch_prev_trade_date(next_day)
    if args.trade_date is None:
        print(
            f"[信息] 文件名(次交易日)={fmt_yyyymmdd(next_day)} "
            f"→ 当日竞价(前一交易日/生成速查当日)={fmt_yyyymmdd(review_date)}"
        )

    auc_map = fetch_auction(review_date)
    if not auc_map:
        print(f"[警告] stk_auction 为空（{review_date}），表格将填「—」。", file=sys.stderr)

    table_rows: list[tuple[int, str, str, str, str, str]] = []
    for i, (code, name) in enumerate(pairs, start=1):
        d = auc_map.get(code) if auc_map else None
        if d:
            amt = f"{d['amount_bn']:.4f}".rstrip("0").rstrip(".")
            pct = f"{d['pct']:+.2f}"
            vr = f"{d['vol_ratio']:.2f}"
        else:
            amt, pct, vr = "—", "—", "—"
        table_rows.append((i, name, code, amt, pct, vr))

    block_inner = build_table(table_rows, review_date, next_day)
    wrapped = f"\n{MARK_START}\n{block_inner}\n{MARK_END}\n"

    if args.stdout_only:
        sys.stdout.write(wrapped)
        return 0

    base = strip_old_block(text)
    # 去掉文末多余空行，再接上块
    base = base.rstrip() + wrapped
    path.write_text(base + "\n", encoding="utf-8")
    print(f"[OK] 已写入 {path} ，共 {len(pairs)} 只标的，当日竞价日期 {review_date}（文件名前一交易日）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
