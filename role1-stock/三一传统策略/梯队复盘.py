import re
import chinadata.ca_data as ts
import pandas as pd
from datetime import datetime, timedelta

TOKEN = 'e95696cde1bc72c2839d1c9cc510ab2cf33'
ts.set_token(TOKEN)
pro = ts.pro_api()

# ============================================================================
# 获取真实的A股交易日
# ============================================================================
today = datetime.now().strftime('%Y%m%d')

# 使用上证指数获取最近的交易日
df_index_recent = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=15)).strftime('%Y%m%d'), end_date=today)

if df_index_recent is None or df_index_recent.empty:
    print("⚠️ 无法获取交易日数据，退出")
    exit()

# 按日期降序排列，获取最新的交易日
df_index_recent = df_index_recent.sort_values('trade_date', ascending=False)
trading_dates_recent = df_index_recent['trade_date'].tolist()

if len(trading_dates_recent) < 1:
    print("⚠️ 交易日数据不足，退出")
    exit()

yesterday = trading_dates_recent[0]  # 最新的交易日

print(f"今日: {today}")
print(f"昨日交易日: {yesterday}")

# ============================================================================
# 获取涨停数据
# ============================================================================
df_limit = pro.kpl_list(trade_date=yesterday, list_type='limit_up')

if df_limit is None or df_limit.empty:
    print(f"{yesterday} 无涨停数据")
    exit()

# 过滤ST股票（先确保name是字符串类型）
df_limit['name'] = df_limit['name'].astype(str)
df_limit = df_limit[~df_limit['name'].str.contains('ST', na=False)]

if df_limit.empty:
    print(f"{yesterday} 过滤ST后无涨停数据")
    exit()

# 提取需要的字段
df_limit['板块'] = df_limit['theme'].fillna('未知')
df_limit['涨停原因'] = df_limit['lu_desc'].fillna('未知')
df_limit['连板情况'] = df_limit['status'].fillna('首板').astype(str)
df_limit['涨停时间'] = df_limit['lu_time'].fillna('未知')
df_limit['封单额亿'] = df_limit['limit_order'].fillna(0) / 100000000  # 转换为亿元

# 获取流通市值
df_basic = pro.daily_basic(trade_date=yesterday, fields='ts_code,circ_mv')
if df_basic is not None and not df_basic.empty:
    mv_map = dict(zip(df_basic['ts_code'], df_basic['circ_mv']))
    df_limit['流通市值亿'] = df_limit['ts_code'].map(mv_map).fillna(0) / 10000  # 转换为亿
else:
    df_limit['流通市值亿'] = 0

# 新增：计算封单占比
df_limit['封单占比'] = df_limit.apply(
    lambda x: (x['封单额亿'] / x['流通市值亿'] * 100) if x['流通市值亿'] > 0 else 0, 
    axis=1
)

# 按板块分类
theme_groups = df_limit.groupby('板块')

print(f"\n📊 {yesterday} 涨停分析\n")
print("="*70)

# ========== 1. 市场最大封单额前两名 ==========
top2_fengdan = df_limit.nlargest(2, '封单额亿')

print("\n🏆 市场最大封单额前两名\n")

for rank, (_, row) in enumerate(top2_fengdan.iterrows(), 1):
    print(f"{rank}. {row['name']}({row['ts_code']})")
    print(f"   封单额: {row['封单额亿']:.2f}亿 封单占比: {row['封单占比']:.2f}%")
    print(f"   连板情况: {row['连板情况']}")
    print(f"   涨停原因: {row['涨停原因']}")
    print()

print("="*70)

# ========== 2. 封单前两名对应涨停原因的所有个股 ==========
for rank, (_, top_stock) in enumerate(top2_fengdan.iterrows(), 1):
    zt_reason = top_stock['涨停原因']
    
    print(f"\n【第{rank}名涨停原因: {zt_reason}】\n")
    
    # 找出相同涨停原因的所有股票
    same_reason_stocks = df_limit[df_limit['涨停原因'] == zt_reason].copy()
    
    if same_reason_stocks.empty:
        print("无相同涨停原因的股票\n")
        continue
    
    # 按连板情况倒序、涨停时间升序排列
    same_reason_stocks = same_reason_stocks.sort_values(
        ['连板情况', '涨停时间','封单占比'], 
        ascending=[False, True, False]
    )
    
    # 表格形式输出
    print(f"{'股票名称':<12} {'连板情况':<12} {'涨停时间':<12} {'流通市值(亿)':<12} {'封单额(亿)':<12} {'封单占比(%)':<12}")
    print("-" * 90)
    
    for _, stock in same_reason_stocks.iterrows():
        print(f"{stock['name']:<10} {stock['连板情况']:<10} {stock['涨停时间']:<10} "
              f"{stock['流通市值亿']:>10.2f} {stock['封单额亿']:>12.2f} {stock['封单占比']:>12.2f}")
    
    print()

print("="*70)

# 保存到Excel - 封单前两名对应的涨停原因个股
excel_sheets = {}

for rank, (_, top_stock) in enumerate(top2_fengdan.iterrows(), 1):
    zt_reason = top_stock['涨停原因']
    
    # 找出相同涨停原因的所有股票
    same_reason_stocks = df_limit[df_limit['涨停原因'] == zt_reason].copy()
    
    if not same_reason_stocks.empty:
        # 按连板情况倒序、涨停时间升序排列
        same_reason_stocks = same_reason_stocks.sort_values(
            ['连板情况', '涨停时间'], 
            ascending=[False, True]
        )
        
        # 准备Excel数据
        excel_data = []
        for _, row in same_reason_stocks.iterrows():
            excel_data.append({
                '股票名称': row['name'],
                '连板情况': row['连板情况'],
                '涨停时间': row['涨停时间'],
                '板块': row['板块'],
                '涨停原因': row['涨停原因'],
                '流通市值亿': row['流通市值亿'],
                '封单额亿': row['封单额亿'],
                '封单占比%': row['封单占比']
            })
        
        df_sheet = pd.DataFrame(excel_data)
        # Excel工作表名称不能含 \ / * ? : [ ]，限制31字符
        safe_name = re.sub(r'[\\/*?:\[\]]', '_', f"第{rank}名_{zt_reason}")
        sheet_name = safe_name[:31]
        excel_sheets[sheet_name] = df_sheet

# 保存到Excel（多个sheet）
excel_filename = f'涨停分析_{yesterday}.xlsx'
with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
    for sheet_name, df_sheet in excel_sheets.items():
        df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)

print(f"\n✅ 数据已保存: {excel_filename}")
print(f"   包含 {len(excel_sheets)} 个工作表")

# ========== 推送到微信 ==========
print("\n推送到微信...")

# 构建推送内容
push_content = f"📊 {yesterday} 涨停分析\n\n"
push_content += "="*70 + "\n\n"
push_content += "🏆 市场最大封单额前两名\n\n"

for rank, (_, row) in enumerate(top2_fengdan.iterrows(), 1):
    push_content += f"{rank}. {row['name']}({row['ts_code']})\n"
    push_content += f"   封单额: {row['封单额亿']:.2f}亿 占比: {row['封单占比']:.2f}%\n"
    push_content += f"   连板情况: {row['连板情况']}\n"
    push_content += f"   涨停原因: {row['涨停原因']}\n\n"

push_content += "="*70 + "\n\n"

# 封单前两名对应涨停原因的所有个股
for rank, (_, top_stock) in enumerate(top2_fengdan.iterrows(), 1):
    zt_reason = top_stock['涨停原因']
    
    push_content += f"【第{rank}名涨停原因: {zt_reason}】\n\n"
    
    same_reason_stocks = df_limit[df_limit['涨停原因'] == zt_reason].copy()
    
    if same_reason_stocks.empty:
        push_content += "无相同涨停原因的股票\n\n"
        continue
    
    same_reason_stocks = same_reason_stocks.sort_values(
        ['连板情况', '涨停时间'], 
        ascending=[False, True]
    )
    
    for _, stock in same_reason_stocks.iterrows():
        push_content += f"{stock['name']} {stock['连板情况']}\n"
        push_content += f"  时间: {stock['涨停时间']} | 市值: {stock['流通市值亿']:.1f}亿 | 封单: {stock['封单额亿']:.1f}亿 | 占比: {stock['封单占比']:.1f}%\n\n"
    
    push_content += "-"*70 + "\n\n"

# 推送到微信
import requests

token = "66c0490b50c34e74b5cc000232b1d23c"
response = requests.post(
    "http://www.pushplus.plus/send",
    json={
        "token": token,
        "title": f"涨停分析 {yesterday}",
        "content": push_content,
        "template": "txt",
        "channel": "wechat"
    }
)

if response.status_code == 200:
    result = response.json()
    if result.get('code') == 200:
        print("✅ 已推送到微信")
    else:
        print(f"❌ 推送失败: {result.get('msg')}")
else:
    print(f"❌ 推送请求失败: {response.status_code}")