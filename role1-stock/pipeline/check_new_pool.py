# -*- coding: utf-8 -*-
import requests

stocks = {
    "华电辽能": "1.600396",
    "辽宁能源": "1.600758",
    "节能风电": "1.601016",
    "通鼎互联": "0.002491",
    "奥瑞德":   "1.600666",
    "长飞光纤": "1.601869",
    "阿莱德":   "0.301419",
    "立讯精密": "0.002475",
    "中利集团": "0.002309",
    "大胜达":   "1.603687",
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
if isinstance(raw, dict):
    items_list = list(raw.values())
else:
    items_list = raw

print("{:<10}{:<10}{:>8}{:>8}{:>12}{:>6}".format(
    "代码", "名称", "现价", "涨跌%", "成交额(亿)", "状态"))
print("-" * 56)

for item in items_list:
    code  = str(item.get("f12", ""))
    name  = item.get("f14", code)
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
