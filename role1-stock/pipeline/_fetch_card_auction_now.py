# -*- coding: utf-8 -*-
"""一次性：拉取指定速查卡标的的 stk_auction + 腾讯现价。"""
import re
import sys
import time
from pathlib import Path

import requests

from _paths import REVIEW_DIR

BASE = REVIEW_DIR
CARD = BASE / "速查_2026-03-28.md"
TRADE_DATE = "20260330"


def main():
    if not CARD.exists():
        print("未找到:", CARD, file=sys.stderr)
        sys.exit(1)
    text = CARD.read_text(encoding="utf-8")
    stocks = re.findall(r"\*\*(.*?)\*\*\(([\w.]+)\)", text)
    seen = {}
    for n, c in stocks:
        c = c.strip()
        if c not in seen:
            seen[c] = n.strip()
    codes = list(seen.keys())

    import chinamindata.min as tss

    pro_min = tss.pro_api()
    try:
        auc = pro_min.stk_auction(trade_date=TRADE_DATE)
    except Exception as e:
        print("stk_auction ERROR:", e)
        auc = None

    print("速查卡文件:", CARD.name, "| 标的数:", len(codes))
    print("竞价交易日:", TRADE_DATE)
    if auc is None or auc.empty:
        print("竞价数据为空或不可用")
        return

    auc_map = {}
    for _, r in auc.iterrows():
        tc = r["ts_code"]
        pre = float(r.get("pre_close") or 0)
        price = float(r.get("price") or 0)
        pct = (price - pre) / pre * 100 if pre > 0 else 0
        auc_map[tc] = {
            "amount_bn": float(r.get("amount") or 0) / 1e8,
            "price": price,
            "pct": pct,
            "vol_ratio": float(r.get("volume_ratio") or 0),
        }

    print("\n=== 9:25 竞价（速查卡标的）")
    for c in sorted(codes):
        if c in auc_map:
            d = auc_map[c]
            print(
                f"  {seen[c]:12} {c}: 竞价额 {d['amount_bn']:.2f}亿 "
                f"开盘模拟 {d['pct']:+.2f}% 量比 {d['vol_ratio']:.2f}"
            )
        else:
            print(f"  {seen[c]:12} {c}: 无竞价记录")

    def qq_part(c):
        n = c.split(".")[0]
        return "sh" + n if n.startswith("6") else "sz" + n

    url = "http://qt.gtimg.cn/q=" + ",".join(qq_part(c) for c in codes)

    def parse_line(line):
        if "~" not in line or '="' not in line:
            return None
        inner = line.split('="', 1)[1].split('"', 1)[0]
        p = inner.split("~")
        if len(p) < 6:
            return None
        name, code = p[1], p[2]
        cur = float(p[3])
        pre = float(p[4])  # 昨收；p[5] 为今开
        pct = (cur / pre - 1.0) * 100 if pre else 0.0
        return name, code, cur, pct

    r = requests.get(url, timeout=15, proxies={"http": None, "https": None})
    ts = time.strftime("%H:%M:%S")
    print(f"\n=== 当前快照（腾讯） {ts}")
    for line in r.text.split(";"):
        x = parse_line(line)
        if x:
            print(f"  {x[0]:12} {x[1]}: {x[3]:+.2f}%")

    def parse_index_line(line):
        if "~" not in line or '="' not in line:
            return None
        inner = line.split('="', 1)[1].split('"', 1)[0]
        p = inner.split("~")
        if len(p) < 6:
            return None
        try:
            name, code = p[1], p[2]
            price = float(p[3])
            pct = float(p[5])
        except (ValueError, IndexError):
            return None
        return name, code, price, pct

    idx_url = "http://qt.gtimg.cn/q=s_sh000001,s_sz399001,s_sz399006"
    ri = requests.get(idx_url, timeout=12, proxies={"http": None, "https": None})
    print(f"\n=== 指数 {ts}")
    for line in ri.text.split(";"):
        x = parse_index_line(line)
        if x:
            print(f"  {x[0]:12} {x[1]}: {x[3]:+.2f}%")


if __name__ == "__main__":
    main()
