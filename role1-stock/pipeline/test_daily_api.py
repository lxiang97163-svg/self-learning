#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 daily 数据获取的函数通路"""

import time
import pandas as pd

print("[测试] AKShare 市场行情函数")

try:
    import akshare as ak

    # 先尝试列出可用函数（仅用于诊断）
    print("  尝试 stock_zt_pool_em()...")
    t1 = time.time()
    df_daily = ak.stock_zt_pool_em(date="20260407")  # 今天的涨停池
    elapsed = time.time() - t1
    print(f"  ✅ stock_zt_pool_em() 成功 ({elapsed:.2f}秒), 返回 {len(df_daily)} 只")

    print(f"  ✅ 成功 ({elapsed:.2f}秒)")
    print(f"     返回行数: {len(df_daily)}")
    print(f"     列名: {list(df_daily.columns)[:10]}")

    if "percent" in df_daily.columns:
        df_daily["pct_chg"] = df_daily["percent"]
        print(f"     ✅ pct_chg 字段已添加")

    # 测试统计
    if "pct_chg" in df_daily.columns:
        pct_chg = pd.to_numeric(df_daily.get("pct_chg", pd.Series(dtype=float)), errors="coerce").fillna(0)
        red_cnt = int((pct_chg > 0).sum())
        green_cnt = int((pct_chg < 0).sum())
        print(f"     涨跌统计: 上涨={red_cnt}只, 下跌={green_cnt}只")

except Exception as e:
    print(f"  ❌ 失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n[测试完成]")
