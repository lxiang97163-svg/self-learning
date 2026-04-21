# -*- coding: utf-8 -*-
"""
按复盘板块拉取实时行情：
绿色电力/电力、光伏概念、储能、充电桩、光通信、算力/退潮低吸
"""
import requests

def get_quotes(secid_list):
    secids = ",".join(secid_list)
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "secids": secids,
        "fields": "f2,f3,f6,f12,f14",
        "fltt": 2, "invt": 2,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    r = requests.get(url, params=params, headers=headers, timeout=10)
    items = r.json().get("data", {}).get("diff", [])
    return {str(it.get("f12","")): it for it in items}

# ── 按复盘板块分组 ──────────────────────────────────────────────
sectors = {
    "绿色电力/电力链": [
        ("600396","华电辽能","6板"),
        ("002310","东方新能","3板"),
        ("300428","立新能源","1板"),
        ("000601","韶能股份","3板退潮"),
    ],
    "光伏概念": [
        ("603687","大胜达","4板"),
        ("002218","拓日新能","1板"),
        ("300345","华民股份","1板"),
    ],
    "充电桩/多题材": [
        ("002309","中利集团","2板"),
        ("002150","正泰电源","2板"),
    ],
    "储能": [
        ("000601","韶能股份","3板退潮"),
        ("002310","东方新能","3板"),
    ],
    "光通信（观察）": [
        ("300308","中际旭创","今日新方向"),
        ("300502","新易盛","今日新方向"),
    ],
    "算力退潮低吸候选": [
        ("000815","美利云","2板峰值"),
        ("002565","顺灏股份","算力退潮"),
    ],
    "炸板/弱转强观察": [
        ("000020","深华发A","昨日炸板"),
    ],
}

# 去重收集所有代码
all_codes = {}
for sec, stocks in sectors.items():
    for code, name, role in stocks:
        prefix = "1" if code.startswith("6") else "0"
        all_codes[code] = f"{prefix}.{code}"

quotes = get_quotes(list(all_codes.values()))

# ── 输出 ──────────────────────────────────────────────────────
for sec, stocks in sectors.items():
    print(f"\n【{sec}】")
    print("{:<8}{:<10}{:<12}{:>7}{:>10}{:>6}".format(
        "代码","名称","角色","现价","涨跌%","状态"))
    print("-" * 55)
    seen = set()
    for code, name, role in stocks:
        if code in seen:
            continue
        seen.add(code)
        it = quotes.get(code, {})
        price = it.get("f2", "--")
        pct   = it.get("f3", "--")
        amt   = it.get("f6", 0)
        if isinstance(pct, (int, float)):
            flag = "涨停" if pct >= 9.9 else ("跌停" if pct <= -9.9 else "")
        else:
            flag = ""
        print("{:<8}{:<10}{:<12}{:>7}{:>10}{:>6}".format(
            code, name, role, str(price), str(pct), flag))
