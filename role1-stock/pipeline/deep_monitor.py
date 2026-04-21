# -*- coding: utf-8 -*-
import requests
import time

def monitor_deep_dive():
    # 监控目标：空间龙、卡位龙、中军、空头风标
    targets = {
        "600396": "华电辽能 (空间龙)",
        "600666": "奥瑞德 (卡位龙)",
        "601869": "长飞光纤 (中军)",
        "603358": "华达科技 (空头风标)"
    }
    
    secids = ",".join([f"{'1' if c.startswith('6') else '0'}.{c}" for c in targets.keys()])
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "secids": secids,
        "fields": "f2,f3,f5,f6,f12,f14,f15,f16,f17,f18", # 现价,涨跌,成交量,成交额,最高,最低,开盘,昨收
        "fltt": 2, "invt": 2,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    
    r = requests.get(url, params=params, timeout=10)
    items = r.json().get("data", {}).get("diff", [])
    
    print(f"=== {time.strftime('%H:%M:%S')} 核心标的深度监控报告 ===")
    print("{:<15}{:>8}{:>10}{:>12}{:>10}".format("标的名称", "现价", "涨跌%", "成交额(亿)", "振幅%"))
    print("-" * 60)
    
    for it in items:
        name = targets.get(it['f12'], it['f14'])
        price = it['f2']
        pct = it['f3']
        amt = it['f6'] / 1e8
        high = it['f15']
        low = it['f16']
        amplitude = (high - low) / it['f18'] * 100 if it['f18'] > 0 else 0
        
        status = "STRONG" if pct > 7 else ("WEAK" if pct < -7 else "STABLE")
        print("{:<15}{:>10}{:>10.2f}%{:>12.2f}{:>10.2f}%  {}".format(
            name, price, pct, amt, amplitude, status))

if __name__ == "__main__":
    monitor_deep_dive()
