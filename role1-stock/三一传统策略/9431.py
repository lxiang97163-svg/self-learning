import chinadata.ca_data as ts
import chinamindata.min as tss
import pandas as pd
from datetime import datetime, timedelta
import requests
import sys
from collections import Counter

TOKEN, TOKEN_MIN = 'e95696cde1bc72c2839d1c9cc510ab2cf33', 'ne34e6697159de73c228e34379b510ec554'
ts.set_token(TOKEN); tss.set_token(TOKEN_MIN)
pro, pro_min = ts.pro_api(), tss.pro_api()


def _safe_ths_member(pro_api, ts_code, fields='con_code'):
    """ths_member 在部分板块上返回异常结构时，chinadata 内部 DataFrame 构造会抛 ValueError，需跳过该板块。"""
    if ts_code is None or (isinstance(ts_code, float) and pd.isna(ts_code)):
        return None
    try:
        df = pro_api.ths_member(ts_code=ts_code, fields=fields)
    except (ValueError, Exception):
        return None
    if df is None or df.empty or 'con_code' not in df.columns:
        return None
    return df


# 获取交易日
today = datetime.now().strftime('%Y%m%d')
try:
    df_index_recent = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=15)).strftime('%Y%m%d'), end_date=today)
except pd.errors.EmptyDataError:
    ts.set_token(TOKEN); tss.set_token(TOKEN_MIN)
    pro, pro_min = ts.pro_api(), tss.pro_api()
    df_index_recent = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=15)).strftime('%Y%m%d'), end_date=today)
trading_dates_recent = df_index_recent.sort_values('trade_date', ascending=False)['trade_date'].tolist()
yesterday = trading_dates_recent[1]

print(f"今日: {today}\n昨日: {yesterday}\n")

# 获取今日竞价数据
df_today_auc = pro_min.stk_auction(trade_date=today)
if df_today_auc is None or df_today_auc.empty:
    exit("⚠️ 无法获取今日竞价数据")

df_today_auc['pct_chg'] = (df_today_auc['price'] - df_today_auc['pre_close']) / df_today_auc['pre_close'] * 100
df_today_auc['amount_wan'] = df_today_auc['amount'] / 10000
df_today_auc['turnover_rate'] = df_today_auc.get('turnover_rate', pd.Series([0]*len(df_today_auc))).fillna(0)

# 获取市值数据（用于加权计算）
df_basic = pro.daily_basic(trade_date=yesterday, fields='ts_code,float_share,close')
if df_basic is not None:
    df_basic['float_mv'] = df_basic['float_share'] * df_basic['close'] / 10000
    df_today_auc = df_today_auc.merge(df_basic[['ts_code', 'float_mv']], on='ts_code', how='left')

# 获取股票名称
df_stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
stock_name_map = dict(zip(df_stocks['ts_code'], df_stocks['name']))

# 获取人气榜
df_hot = pro.dc_hot(market='A股市场', hot_type='人气榜', trade_date=yesterday, fields='ts_code,rank')
hot_rank_map = dict(zip(df_hot['ts_code'], df_hot['rank'])) if df_hot is not None else {}

# 获取热股榜
df_hot_stocks = pro.ths_hot(trade_date=yesterday, market='热股', is_new='Y')
ths_hot_rank_map = dict(zip(df_hot_stocks['ts_code'], df_hot_stocks['rank'])) if isinstance(df_hot_stocks, pd.DataFrame) else {}

# 获取所有同花顺概念板块
df_all_concepts = pro.ths_index(exchange='A', type='N')  # type='N'表示概念板块
if df_all_concepts is None or df_all_concepts.empty:
    exit("⚠️ 无法获取板块数据")

print(f"共有 {len(df_all_concepts)} 个概念板块\n")
print("正在计算各板块高开幅度及三一股票...\n")

# 计算每个板块的加权涨幅和三一股票
sector_results = []
for idx, sector in df_all_concepts.iterrows():
    # 获取板块成分股（单板块接口异常时跳过，避免整脚本崩溃）
    df_members = _safe_ths_member(pro, sector['ts_code'])
    if df_members is None:
        continue
    
    # 获取成分股今日竞价数据
    member_codes = df_members['con_code'].tolist()
    df_sector = df_today_auc[df_today_auc['ts_code'].isin(member_codes)]
    
    if df_sector.empty:
        continue
    
    # 计算加权涨幅（流通市值加权）
    if 'float_mv' in df_sector.columns:
        df_sector_valid = df_sector.dropna(subset=['float_mv'])
        if not df_sector_valid.empty and df_sector_valid['float_mv'].sum() > 0:
            weighted_pct = (df_sector_valid['pct_chg'] * df_sector_valid['float_mv']).sum() / df_sector_valid['float_mv'].sum()
        else:
            weighted_pct = df_sector['pct_chg'].mean()
    else:
        weighted_pct = df_sector['pct_chg'].mean()
    
    # 计算三一股票（竞价金额前三、竞价换手前三、人气值第一）
    amt_top3_stocks = []
    hs_top3_stocks = []
    hot_top1_stock = None
    
    if not df_sector.empty:
        # 竞价金额前三
        amt_top3 = df_sector.nlargest(3, 'amount_wan')
        for _, row in amt_top3.iterrows():
            code = row['ts_code']
            amt_top3_stocks.append({
                'code': code,
                'name': stock_name_map.get(code, '未知'),
                'pct_chg': row['pct_chg'],
                'rank': hot_rank_map.get(code, 9999),
                'amount_wan': int(row['amount_wan'])
            })
        
        # 竞价换手前三
        hs_top3 = df_sector.nlargest(3, 'turnover_rate')
        for _, row in hs_top3.iterrows():
            code = row['ts_code']
            hs_top3_stocks.append({
                'code': code,
                'name': stock_name_map.get(code, '未知'),
                'pct_chg': row['pct_chg'],
                'rank': hot_rank_map.get(code, 9999),
                'turnover_rate': row['turnover_rate']
            })
        
        # 人气值第一（rank最小）
        df_sector_with_rank = df_sector[df_sector['ts_code'].isin([c for c in member_codes if hot_rank_map.get(c, 9999) < 9999])].copy()
        if not df_sector_with_rank.empty:
            df_sector_with_rank['hot_rank'] = df_sector_with_rank['ts_code'].map(hot_rank_map)
            hot_top1_row = df_sector_with_rank.nsmallest(1, 'hot_rank')
            if not hot_top1_row.empty:
                code = hot_top1_row['ts_code'].iloc[0]
                hot_top1_stock = {
                    'code': code,
                    'name': stock_name_map.get(code, '未知'),
                    'pct_chg': hot_top1_row['pct_chg'].iloc[0],
                    'rank': hot_rank_map.get(code, 9999)
                }
    
    sector_results.append({
        'ts_code': sector['ts_code'],
        'name': sector['name'],
        'weighted_pct': weighted_pct,
        'member_count': len(df_sector),
        'amt_top3_stocks': amt_top3_stocks,
        'hs_top3_stocks': hs_top3_stocks,
        'hot_top1_stock': hot_top1_stock
    })
    
    # 显示进度
    if (idx + 1) % 50 == 0:
        print(f"已处理 {idx + 1}/{len(df_all_concepts)} 个板块...")

if not sector_results:
    print("⚠️ 未能得到任何有效板块数据（成分接口失败或当日无交集），退出")
    sys.exit(1)

# 按加权涨幅降序排列，取前3
top3_sectors = sorted(sector_results, key=lambda x: x['weighted_pct'], reverse=True)[:3]

# 构建推送内容
lines = []
lines.append(f"📊 {today} 所有题材高开板块前三\n")
lines.append("="*70)
lines.append("")

for i, sector in enumerate(top3_sectors, 1):
    lines.append(f"{i}. {sector['name']} 高开 {sector['weighted_pct']:+.2f}%")
    lines.append(f"   成分股数: {sector['member_count']}只")
    
    # 竞价金额前三
    if sector['amt_top3_stocks']:
        for idx, s in enumerate(sector['amt_top3_stocks'], 1):
            rank_text = f"rank{s['rank']}" if s['rank'] < 9999 else "无rank"
            lines.append(f"   竞价金额第{idx}: {s['name']}({s['code']}) {rank_text} 金额{s['amount_wan']}万 竞价{s['pct_chg']:+.2f}%")
    else:
        lines.append(f"   竞价金额前三: 无")
    
    # 竞价换手前三
    if sector['hs_top3_stocks']:
        for idx, s in enumerate(sector['hs_top3_stocks'], 1):
            rank_text = f"rank{s['rank']}" if s['rank'] < 9999 else "无rank"
            lines.append(f"   竞价换手第{idx}: {s['name']}({s['code']}) {rank_text} 换手{s['turnover_rate']:.4f}% 竞价{s['pct_chg']:+.2f}%")
    else:
        lines.append(f"   竞价换手前三: 无")
    
    # 人气值第一
    if sector['hot_top1_stock']:
        s = sector['hot_top1_stock']
        lines.append(f"   人气值第一: {s['name']}({s['code']}) rank{s['rank']} 竞价{s['pct_chg']:+.2f}%")
    else:
        lines.append(f"   人气值第一: 无")
    
    lines.append("")

content = '\n'.join(lines)

# 支持 --no-push --output-file=xxx 供统一入口调用（先写文件再 print，避免 Windows GBK 下 print emoji 报错）
do_push = True
out_file = None
for i, a in enumerate(sys.argv):
    if a == '--no-push': do_push = False
    if a == '--output-file' and i + 1 < len(sys.argv): out_file = sys.argv[i + 1]
if out_file:
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)
    sys.exit(0)
if not do_push:
    print("\n✅ (未推送)")
    sys.exit(0)
try:
    print(content)
except UnicodeEncodeError:
    print(content.encode('utf-8', errors='replace').decode('utf-8'))

# 推送到pushplus
requests.post("http://www.pushplus.plus/send", json={
    "token": "66c0490b50c34e74b5cc000232b1d23c", 
    "title": f"题材高开前三 {today}", 
    "content": content, 
    "template": "txt", 
    "channel": "wechat"
})

print("\n✅ 推送完成！")