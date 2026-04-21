#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐个测试三个 tushare API 函数的耗时"""

import sys
import time
from datetime import datetime, timedelta

import chinadata.ca_data as ts

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"

ts.set_token(TOKEN)
pro = ts.pro_api()

print("[测试开始]")

# 测试 1: index_daily
print("\n[测试1] index_daily (5日+历史)")
today = datetime.now().strftime('%Y%m%d')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
start_date = (datetime.now() - timedelta(days=15)).strftime('%Y%m%d')

try:
    t1 = time.time()
    df_index_recent = pro.index_daily(
        ts_code='000001.SH',
        start_date=start_date,
        end_date=today
    )
    elapsed = time.time() - t1
    print(f"✅ 成功 ({elapsed:.2f}秒)")
    print(f"   返回行数: {len(df_index_recent) if df_index_recent is not None else 0}")
except Exception as e:
    print(f"❌ 失败: {type(e).__name__}: {e}")

# 测试 2: stock_basic
print("\n[测试2] stock_basic (全市场)")
try:
    t2 = time.time()
    df_stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
    elapsed = time.time() - t2
    print(f"✅ 成功 ({elapsed:.2f}秒)")
    print(f"   返回行数: {len(df_stocks) if df_stocks is not None else 0}")
except Exception as e:
    print(f"❌ 失败: {type(e).__name__}: {e}")

# 测试 3: daily
print("\n[测试3] daily (单只股票日行情)")
try:
    t3 = time.time()
    f_yesterday_daily = pro.daily(ts_code='000006.SZ', trade_date=yesterday)
    elapsed = time.time() - t3
    print(f"✅ 成功 ({elapsed:.2f}秒)")
    print(f"   返回行数: {len(f_yesterday_daily) if f_yesterday_daily is not None else 0}")
except Exception as e:
    print(f"❌ 失败: {type(e).__name__}: {e}")

print("\n[测试结束]")
