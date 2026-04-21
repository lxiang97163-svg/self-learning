import requests
import datetime
import json

HDR = {"User-Agent": "Mozilla/5.0"}

def get_json(url, params):
    try:
        r = requests.get(url, params=params, headers=HDR, timeout=10)
        return r.json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def run():
    today = datetime.date.today().strftime("%Y%m%d")
    # 1. 实时行情
    d1 = get_json("https://push2.eastmoney.com/api/qt/ulist.np/get", {
        "secids": "1.000001,0.399001,0.399006",
        "fields": "f2,f3,f6,f12,f14,f17,f18",
        "fltt": 2, "invt": 2
    })
    print("--- MARKET ---")
    if d1 and "data" in d1:
        for it in d1["data"]["diff"]:
            print(f"{it['f14']}: 现价={it.get('f2')} 开={it.get('f17')} 昨收={it.get('f18')} 额={it.get('f6',0)/1e8:.0f}亿")

    # 2. 今日5分钟线
    d2 = get_json("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": "1.000001", "klt": 5, "beg": today, "end": today,
        "fields2": "f51,f52,f53,f54,f55,f56,f57"
    })
    print("\n--- TODAY 5MIN ---")
    if d2 and "data" in d2 and d2["data"]:
        for k in d2["data"]["klines"][:5]:
            print(k)

    # 3. 昨日5分钟线 (3月26日)
    d3 = get_json("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": "1.000001", "klt": 5, "beg": "20260326", "end": "20260326",
        "fields2": "f51,f52,f53,f54,f55,f56,f57"
    })
    print("\n--- YEST 5MIN ---")
    if d3 and "data" in d3 and d3["data"]:
        for k in d3["data"]["klines"][:5]:
            print(k)

    # 4. 板块
    d4 = get_json("https://push2.eastmoney.com/api/qt/clist/get", {
        "fid": "f3", "po": 1, "pz": 5, "pn": 1, "fs": "m:90+t:3", "fields": "f14,f3"
    })
    print("\n--- CONCEPTS ---")
    if d4 and "data" in d4 and d4["data"]:
        for it in d4["data"]["diff"]:
            print(f"{it['f14']}: {it['f3']}%")

if __name__ == "__main__":
    run()
