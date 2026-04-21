import requests, datetime

HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
UT = "b2884a393a59ad64002292a3e90d46a5"

def get_5min(date_str):
    r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params={
        "secid": "1.000001",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 5, "fqt": 0, "beg": date_str, "end": date_str, "ut": UT,
    }, headers=HDR, timeout=10)
    return r.json().get("data", {}).get("klines", [])

today = datetime.date.today().strftime("%Y%m%d")
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y%m%d")

k_today = get_5min(today)
k_yest  = get_5min(yesterday)

now = datetime.datetime.now()
market_open = now.replace(hour=9, minute=35, second=0, microsecond=0)
elapsed_bars = max(0, int((now - market_open).total_seconds() / 300))

print(f"当前时间: {now.strftime('%H:%M')}，开市后约第{elapsed_bars}根5分钟K线")
print()

def sum_amt(klines, n):
    total = 0
    for k in klines[:n]:
        p = k.split(",")
        total += float(p[6])
    return total

n = min(elapsed_bars, len(k_today), len(k_yest))
amt_today = sum_amt(k_today, n)
amt_yest  = sum_amt(k_yest, n)

print(f"同时段（前{n}根5分钟K线）累计成交额对比：")
print(f"  今日:  {amt_today/1e8:.0f}亿")
print(f"  昨日:  {amt_yest/1e8:.0f}亿")
if amt_yest > 0:
    ratio = amt_today / amt_yest
    if ratio > 1.5:   label = "爆量"
    elif ratio > 1.1: label = "增量"
    elif ratio > 0.9: label = "平量"
    elif ratio > 0.6: label = "缩量"
    else:             label = "量窒息"
    print(f"  比值:  {ratio:.2f}x → {label}")

print()
print("今日各5分钟K线成交额：")
for k in k_today:
    p = k.split(",")
    print(f"  {p[0]}  额={float(p[6])/1e8:.1f}亿")

print()
print(f"昨日各5分钟K线成交额（同时段前{n}根参考）：")
for k in k_yest[:n+2]:
    p = k.split(",")
    print(f"  {p[0]}  额={float(p[6])/1e8:.1f}亿")
