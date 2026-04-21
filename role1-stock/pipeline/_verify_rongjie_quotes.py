# -*- coding: utf-8 -*-
"""多源交叉验证 002192 融捷股份：现价 vs 昨收，纠正腾讯解析字段。"""
import json
import sys

import requests

CODE = "002192"
proxies = {"http": None, "https": None}
HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def main():
    # 1) 腾讯 raw + 字段枚举
    u1 = "http://qt.gtimg.cn/q=sz" + CODE
    r1 = requests.get(u1, timeout=12, proxies=proxies)
    print("=== 腾讯 qt.gtimg.cn 原始行（截断）===")
    t = r1.text.strip()
    print(t[:300])
    inner = None
    if '="' in t:
        inner = t.split('="', 1)[1].split('"', 1)[0]
    parts = inner.split("~") if inner else []
    print("\n=== 腾讯 ~ 分段 index:value（前25段）===")
    for i, v in enumerate(parts[:25]):
        print(f"  [{i}] {v!r}")

    # 腾讯文档常见：3=现价 4=昨收 5=今开（部分接口）；realtime_engine 用 5=昨收 可能是错的
    cur = pre_y = None
    if len(parts) > 5:
        try:
            cur = float(parts[3])
            pre4 = float(parts[4])
            pre5 = float(parts[5])
            print("\n=== 腾讯 涨跌试算 ===")
            print(f"  parts[3]现价={cur} parts[4]={pre4} parts[5]={pre5}")
            print(f"  若昨收=parts[4]: 涨跌幅%={(cur/pre4-1)*100:.4f}")
            print(f"  若昨收=parts[5]: 涨跌幅%={(cur/pre5-1)*100:.4f}  (与 realtime_engine 当前逻辑一致)")
        except (ValueError, TypeError) as e:
            print("腾讯数值解析失败:", e)

    # 2) 东财 push2delay
    secid = "0." + CODE
    url2 = "http://push2delay.eastmoney.com/api/qt/ulist.np/get"
    p2 = {
        "secids": secid,
        "fields": "f2,f3,f4,f12,f14,f18",
        "fltt": 2,
        "invt": 2,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    try:
        j2 = requests.get(url2, params=p2, headers=HDR, timeout=12, proxies=proxies).json()
    except Exception as e:
        j2 = {"error": str(e)}
    print("\n=== 东财 push2delay ulist (f3=涨跌幅%%) ===")
    print(json.dumps(j2, ensure_ascii=False, indent=2)[:2000])

    # 3) 新浪
    u3 = "https://hq.sinajs.cn/list=sz" + CODE
    r3 = requests.get(u3, timeout=12, proxies=proxies)
    print("\n=== 新浪 hq.sinajs.cn ===")
    print(r3.text[:500])

    # 新浪格式: var hq_str_sz002192="name,open,pre,price,high,low,bid,ask,volume,amount,...";
    raw = r3.text
    if '="' in raw:
        s = raw.split('="', 1)[1].split('"', 1)[0]
        sina_fields = s.split(",")
        if len(sina_fields) >= 4:
            try:
                name = sina_fields[0]
                open_ = float(sina_fields[1])
                pre = float(sina_fields[2])
                price = float(sina_fields[3])
                pct_sina = (price / pre - 1) * 100 if pre else 0
                print("\n=== 新浪解析（字段1=今开 2=昨收 3=现价）===")
                print(f"  {name} 昨收={pre} 现价={price} 涨跌幅={pct_sina:.4f}%")
            except Exception as e:
                print("新浪解析失败", e)


if __name__ == "__main__":
    main()
