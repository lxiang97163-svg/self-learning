# -*- coding: utf-8 -*-
import requests

stocks = {
    "华电辽能": "1.600396",
    "大胜达":   "1.603687",
    "东方新能": "0.002310",
    "中利集团": "0.002309",
    "深华发A":  "0.000020",
    "正泰电源": "0.002150",
    "拓日新能": "0.002218",
    "华民股份": "0.300345",
    "中际旭创": "0.300308",
    "新易盛":   "0.300502",
    "韶能股份": "0.000601",
    "立新能源": "0.300428",
}

secids = ",".join(stocks.values())
url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
params = {
    "secids": secids,
    "fields": "f2,f3,f4,f5,f6,f12,f14",
    "fltt": 2, "invt": 2,
    "ut": "b2884a393a59ad64002292a3e90d46a5",
}
headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://quote.eastmoney.com/",
}

r = requests.get(url, params=params, headers=headers, timeout=10)
data = r.json()
raw = data.get("data", {}).get("diff", [])
# diff 可能是 list 或 dict
if isinstance(raw, dict):
    items_list = list(raw.values())
else:
    items_list = raw  # list of dicts

code_to_name = {v.split(".")[1]: k for k, v in stocks.items()}

print("{:<10}{:<10}{:>8}{:>8}{:>12}{:>6}".format(
    "代码", "名称", "现价", "涨跌%", "成交额(亿)", "状态"))
print("-" * 56)

for item in items_list:
    code  = str(item.get("f12", ""))
    name  = item.get("f14", code_to_name.get(code, code))
    price = item.get("f2", "--")
    pct   = item.get("f3", "--")
    amt   = item.get("f6", 0)
    amt_yi = "{:.2f}".format(amt / 1e8) if isinstance(amt, (int, float)) and amt > 0 else "--"
    if isinstance(pct, (int, float)):
        flag = "涨停" if pct >= 9.9 else ("跌停" if pct <= -9.9 else "")
    else:
        flag = ""
    print("{:<10}{:<10}{:>8}{:>8}{:>12}{:>6}".format(
        code, name, str(price), str(pct), amt_yi, flag))
