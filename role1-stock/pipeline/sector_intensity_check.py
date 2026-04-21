# -*- coding: utf-8 -*-
import chinamindata.min as tss
import pandas as pd
import re
import os
from datetime import datetime
from pathlib import Path

from _paths import REVIEW_DIR as _OUTPUTS_DIR

def parse_quick_check_card(date_str):
    """解析速查卡 Markdown 文件，提取题材和票池"""
    file_path = _OUTPUTS_DIR / f"速查_{date_str}.md"
    if not os.path.exists(file_path):
        print(f"错误：未找到 {date_str} 的速查卡文件。")
        return None
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    sector_pools = {}
    # 匹配题材标题，如 ### ✅ 第一优先（绿色电力/风电）
    sector_matches = re.finditer(r"### ✅ (?:第一|第二)优先（(.*?)）\n(.*?)(?=\n###|$)", content, re.S)
    
    for match in sector_matches:
        sector_name = match.group(1)
        table_content = match.group(2)
        
        stocks = []
        threshold_pct = 2.5 # 默认值
        leader = None
        
        # 匹配表格行中的代码和涨幅要求，如 **华电辽能**(600396.SH) | 龙一 | ...涨幅≥3.5%
        row_matches = re.finditer(r"\*\*(.*?)\*\*\((.*?)\) \| (.*?) \|.*?涨幅≥([\d\.]+)%", table_content)
        for r_match in row_matches:
            name, code, role, pct = r_match.groups()
            stocks.append(code)
            threshold_pct = float(pct) # 取最后一只票的涨幅作为题材参考
            if "龙一" in role or "风标" in role:
                leader = code
        
        if stocks:
            sector_pools[sector_name] = {
                "stocks": stocks,
                "threshold_pct": threshold_pct,
                "leader": leader or stocks[0]
            }
    return sector_pools

def check_intensity(date_str=None):
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. 动态解析速查卡
    sector_pools = parse_quick_check_card(date_str)
    if not sector_pools:
        return

    # 2. 获取实时数据
    pro_min = tss.pro_api()
    all_codes = [s for p in sector_pools.values() for s in p["stocks"]]
    
    # 将 YYYY-MM-DD 转为 YYYYMMDD 供接口使用
    api_date = date_str.replace("-", "")
    try:
        auc = pro_min.stk_auction(trade_date=api_date)
    except:
        print("接口调用失败，请检查 Tushare Token。")
        return

    if auc.empty:
        print(f"提示：{date_str} 尚未产生竞价数据或非交易日。")
        return

    res = auc[auc['ts_code'].isin(all_codes)][['ts_code', 'amount', 'price', 'pre_close']]
    res['pct'] = (res['price'] - res['pre_close']) / res['pre_close'] * 100
    
    print(f"=== {date_str} 题材竞价强度监控 (动态联动版) ===")
    print("{:<15}{:>10}{:>10}{:>10}".format("题材板块", "核心池均涨", "达标只数", "联动信号"))
    print("-" * 50)

    for name, info in sector_pools.items():
        data = res[res['ts_code'].isin(info["stocks"])]
        if data.empty:
            continue
            
        avg_pct = data['pct'].mean()
        hit_count = len(data[data['pct'] >= info["threshold_pct"]])
        total_count = len(info["stocks"])
        
        # 联动逻辑：均涨 > 2% 且 达标只数 >= 2
        signal = "STRONG" if avg_pct > 2.0 and hit_count >= 2 else ("WEAK" if avg_pct > 0 else "NONE")
        
        print("{:<15}{:>10.2f}%{:>10}{:>10}".format(name, avg_pct, f"{hit_count}/{total_count}", signal))
        
        for _, row in data.iterrows():
            is_leader = " (LEADER)" if row['ts_code'] == info["leader"] else ""
            status = "HIT" if row['pct'] >= info["threshold_pct"] else "MISS"
            print(f"  {status} {row['ts_code']}{is_leader}: {row['pct']:.2f}%")
        print()

if __name__ == "__main__":
    # 默认检查 03-26
    check_intensity("2026-03-26")
