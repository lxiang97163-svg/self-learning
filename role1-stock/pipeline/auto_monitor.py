# -*- coding: utf-8 -*-
import requests
import time
import os

from _paths import LOGS_DIR

def get_data():
    targets = {"600396": "华电辽能", "600666": "奥瑞德", "601869": "长飞光纤", "603358": "华达科技"}
    secids = ",".join([f"{'1' if c.startswith('6') else '0'}.{c}" for c in targets.keys()])
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"secids": secids, "fields": "f2,f3,f6,f12,f14", "fltt": 2, "invt": 2, "ut": "b2884a393a59ad64002292a3e90d46a5"}
    try:
        r = requests.get(url, params=params, timeout=10)
        return r.json().get("data", {}).get("diff", []), targets
    except:
        return [], {}

log_file = str(LOGS_DIR / "monitor_log.txt")
if os.path.exists(log_file): os.remove(log_file)

while True:
    items, targets = get_data()
    if items:
        timestamp = time.strftime('%H:%M:%S')
        summary = []
        for it in items:
            name = targets.get(it['f12'], it['f14'])
            pct = it['f3']
            summary.append(f"{name}:{pct}%")
        log_entry = f"[{timestamp}] " + " | ".join(summary)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    time.sleep(300) # 每5分钟记录一次
