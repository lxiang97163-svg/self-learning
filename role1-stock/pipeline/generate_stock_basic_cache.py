#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性生成 stock_basic 缓存文件"""

import pandas as pd
import chinadata.ca_data as ts

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"

ts.set_token(TOKEN)
pro = ts.pro_api()

print("正在获取 stock_basic...")
df_stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')

cache_file = "stock_basic_cache.csv"
df_stocks.to_csv(cache_file, index=False)

print(f"✅ 缓存已生成: {cache_file}")
print(f"   包含 {len(df_stocks)} 只股票")
