# 连板天梯+爆量+一红融合
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import chinadata.ca_data as ts
import chinamindata.min as tss
import pandas as pd
from datetime import datetime, timedelta
import requests
import time

start_time = time.time()

TOKEN = 'e95696cde1bc72c2839d1c9cc510ab2cf33'
TOKEN_MIN = 'ne34e6697159de73c228e34379b510ec554'
ts.set_token(TOKEN)
tss.set_token(TOKEN_MIN)
pro, pro_min = ts.pro_api(), tss.pro_api()


def _pro_index_daily_with_retry():
    """首次请求若因 chinadata token 文件被并发写空而报 EmptyDataError，则重设 token 再试一次。"""
    global pro, pro_min
    start = (datetime.now() - timedelta(days=15)).strftime('%Y%m%d')
    try:
        return pro.index_daily(ts_code='000001.SH', start_date=start, end_date=today)
    except pd.errors.EmptyDataError:
        ts.set_token(TOKEN)
        tss.set_token(TOKEN_MIN)
        pro, pro_min = ts.pro_api(), tss.pro_api()
        return pro.index_daily(ts_code='000001.SH', start_date=start, end_date=today)


# ============================================================================
# 获取真实的A股交易日
# ============================================================================
today = datetime.now().strftime('%Y%m%d')

# 使用上证指数获取最近的交易日
df_index_recent = _pro_index_daily_with_retry()

if df_index_recent is None or df_index_recent.empty:
    print("⚠️ 无法获取交易日数据，退出")
    exit()

# 按日期降序排列，获取最新的交易日
df_index_recent = df_index_recent.sort_values('trade_date', ascending=False)
trading_dates_recent = df_index_recent['trade_date'].tolist()

if len(trading_dates_recent) < 2:
    print("⚠️ 交易日数据不足，退出")
    exit()

yesterday = trading_dates_recent[0]  # 最新的交易日

print(f"今日: {today}")
print(f"昨日交易日: {yesterday}")

# 获取120个交易日用于后续计算
df_index_120 = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=200)).strftime('%Y%m%d'), end_date=yesterday)
if df_index_120 is not None and not df_index_120.empty:
    trading_dates = df_index_120.sort_values('trade_date')['trade_date'].tolist()
else:
    print("⚠️ 无法获取120日交易日数据，退出")
    exit()

if len(trading_dates) < 122:
    print(f"⚠️ 交易日数据不足122天，当前只有{len(trading_dates)}天")
    exit()

past_120_days = trading_dates[-122:-1]
past_3_days = trading_dates[-4:-1]  # 前3日

# ============================================================================
# 数据完整性检测：确保竞价数据已完全回刷
# ============================================================================
print("="*70)
print(f"📊 开始数据完整性检测...")
print("="*70)

check_interval = 10   # 检查间隔：10秒
wait_start_time = time.time()
check_count = 0

# 计算截止时间：9:28:00
current_date = datetime.now()
deadline_time = datetime(current_date.year, current_date.month, current_date.day, 9, 28, 0)

while True:
    check_count += 1
    check_time = time.time()
    current_datetime = datetime.now()
    
    # 检查是否超过9:28:00
    if current_datetime >= deadline_time:
        print(f"⚠️ 已到达9:28:00截止时间，强制开始运行")
        break
    
    # 获取今日和昨日竞价数据
    df_today_auc_check = pro_min.stk_auction(trade_date=today)
    df_yester_auc_check = pro_min.stk_auction(trade_date=yesterday)
    
    if df_today_auc_check is None or df_today_auc_check.empty:
        remaining_time = (deadline_time - current_datetime).total_seconds()
        print(f"⚠️ 检测 #{check_count}: 今日竞价数据为空，等待{check_interval}秒后重试... (距离9:28还有{int(remaining_time)}秒)")
        time.sleep(check_interval)
        continue
    
    if df_yester_auc_check is None or df_yester_auc_check.empty:
        print(f"⚠️ 检测 #{check_count}: 昨日竞价数据为空，跳过检测直接运行")
        break
    
    # 计算行数差异
    today_count = len(df_today_auc_check)
    yesterday_count = len(df_yester_auc_check)
    diff_pct = abs(today_count - yesterday_count) / yesterday_count * 100
    
    elapsed_time = time.time() - wait_start_time
    remaining_time = (deadline_time - current_datetime).total_seconds()
    
    print(f"✓ 检测 #{check_count} (耗时 {elapsed_time:.1f}s, 距离9:28还有{int(remaining_time)}秒):")
    print(f"  今日竞价数据: {today_count} 条")
    print(f"  昨日竞价数据: {yesterday_count} 条")
    print(f"  差异率: {diff_pct:.2f}%")
    
    # 检查是否满足条件
    if diff_pct < 2.0:
        print(f"✅ 数据完整性检测通过！差异率 {diff_pct:.2f}% < 2%")
        print(f"   总等待时间: {elapsed_time:.1f}秒")
        break
    
    # 继续等待
    print(f"⏳ 差异率 {diff_pct:.2f}% ≥ 2%，等待{check_interval}秒后重试...")
    time.sleep(check_interval)

print("="*70)
print(f"开始正式运行分析...\n")

# ============================================================================
# 原有代码从这里开始
# ============================================================================

print("="*70)
print(f"📊 {today} 连板天梯+爆量+一红")
print("="*70)

# 股票池
df_stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
stock_pool = set(df_stocks[(~df_stocks['name'].str.contains('ST', na=False)) & 
                           (~df_stocks['ts_code'].str.endswith('.BJ')) &
                           (~df_stocks['ts_code'].str.startswith(('688', '300', '301')))]['ts_code'])
stock_name_map = dict(zip(df_stocks['ts_code'], df_stocks['name']))

print(f"\n步骤1: 获取昨日连板天梯...")
t1 = time.time()
# 获取昨日连板天梯（这些股票是昨天的连板）
df_ladder = pro.limit_step(trade_date=yesterday)
if df_ladder is None or df_ladder.empty:
    print("✗ 连板天梯数据为空")
    exit()

# 过滤掉ST、北交所、7连板及以上
df_ladder['nums'] = df_ladder['nums'].astype(int)  # 转换为整数
df_ladder = df_ladder[df_ladder['ts_code'].isin(stock_pool) & (df_ladder['nums'] < 7)]
print(f"✓ 昨日连板天梯（过滤7连板以上）: {len(df_ladder)}只股票")
print(f"  连板分布: {df_ladder['nums'].value_counts().to_dict()}")
print(f"  耗时: {time.time()-t1:.1f}s")

print(f"\n步骤2: 计算爆量股票（昨日成交量 vs 前3日均量）...")
t2 = time.time()
# 获取昨日成交量数据
ladder_codes = df_ladder['ts_code'].tolist()
df_yesterday_daily = pro.daily(trade_date=yesterday, ts_code=','.join(ladder_codes))
if df_yesterday_daily is None or df_yesterday_daily.empty:
    print("✗ 昨日日线数据为空")
    exit()

yesterday_vol_map = dict(zip(df_yesterday_daily['ts_code'], df_yesterday_daily['vol']))

# 计算爆量：昨日成交量 vs 前3日均量
explode_stocks = []
for _, row in df_ladder.iterrows():
    code = row['ts_code']
    nums = row['nums']
    
    # 获取前3日数据（不包括昨天）- 使用真实交易日
    if len(trading_dates) >= 5:
        past_3_for_this = trading_dates[-5:-2]  # 往前推
    else:
        continue
        
    df_hist = pro.daily(ts_code=code, start_date=past_3_for_this[0], end_date=past_3_for_this[-1])
    if df_hist is None or len(df_hist) < 3:
        continue
    
    # 前3日均量
    avg_vol_3d = df_hist['vol'].mean()
    
    # 昨日成交量
    yesterday_vol = yesterday_vol_map.get(code, 0)
    
    # 判断爆量：昨日成交量 >= 前3日均量的3倍
    if avg_vol_3d > 0 and yesterday_vol >= avg_vol_3d * 3:
        explode_stocks.append({
            'code': code,
            'name': stock_name_map.get(code, '未知'),
            'nums': nums,
            'yesterday_vol': yesterday_vol,
            'avg_vol_3d': avg_vol_3d,
            'vol_ratio': yesterday_vol / avg_vol_3d
        })

print(f"✓ 爆量股票: {len(explode_stocks)}只")
if explode_stocks:
    for s in sorted(explode_stocks, key=lambda x: x['nums'], reverse=True)[:10]:
        print(f"  {s['name']}({s['code']}) {s['nums']}连板 爆量{s['vol_ratio']:.1f}倍")
print(f"  耗时: {time.time()-t2:.1f}s")

print(f"\n步骤3: 获取今日竞价数据...")
t3 = time.time()
df_today_auc = pro_min.stk_auction(trade_date=today)
if df_today_auc is None or df_today_auc.empty:
    print("✗ 竞价数据为空")
    exit()

df_today_auc['pct_chg'] = (df_today_auc['price'] - df_today_auc['pre_close']) / df_today_auc['pre_close'] * 100
print(f"✓ 竞价数据: {len(df_today_auc)}只股票")
print(f"  耗时: {time.time()-t3:.1f}s")

print(f"\n步骤4: 筛选爆量股票中高开的（剔除竞价>8%）...")
t4 = time.time()
explode_high_open = []
for s in explode_stocks:
    auc_data = df_today_auc[df_today_auc['ts_code'] == s['code']]
    if not auc_data.empty:
        pct_chg = auc_data['pct_chg'].iloc[0]
        if 0 < pct_chg <= 8:  # 高开且不超过8%
            s['today_pct'] = pct_chg
            explode_high_open.append(s)

print(f"✓ 爆量且高开(0-8%): {len(explode_high_open)}只")
print(f"  耗时: {time.time()-t4:.1f}s")

print(f"\n步骤5: 获取板块信息...")
t5 = time.time()
# 获取涨停概念榜（昨日）
sector_map = {}
df_cpt = pro.limit_cpt_list(trade_date=yesterday)
if df_cpt is not None and not df_cpt.empty:
    for _, sector in df_cpt.iterrows():
        df_members = pro.ths_member(ts_code=sector['ts_code'], fields='con_code')
        if df_members is not None and not df_members.empty:
            for code in df_members['con_code'].tolist():
                if code not in sector_map:
                    sector_map[code] = []
                sector_map[code].append(sector['name'])

# 添加板块信息
for s in explode_high_open:
    s['sectors'] = sector_map.get(s['code'], ['无'])

# 板块今日高开、板块内涨停（用于每只推荐股展示）
sector_open_zt = {}  # sector_name -> {'open_pct': float, 'zt_count': int}
df_yesterday_zt = pro.limit_list_d(trade_date=yesterday, limit_type='U')
yesterday_zt_set = set(df_yesterday_zt['ts_code']) if df_yesterday_zt is not None and not df_yesterday_zt.empty else set()
if df_cpt is not None and not df_cpt.empty:
    for _, sector in df_cpt.iterrows():
        df_members = pro.ths_member(ts_code=sector['ts_code'], fields='con_code')
        if df_members is None or df_members.empty:
            continue
        codes = df_members['con_code'].tolist()
        df_sector_auc = df_today_auc[df_today_auc['ts_code'].isin(codes)]
        if df_sector_auc.empty:
            continue
        weighted_pct = df_sector_auc['pct_chg'].mean()
        zt_count = sum(1 for c in codes if c in yesterday_zt_set)
        sector_open_zt[sector['name']] = {'open_pct': weighted_pct, 'zt_count': zt_count}
    
print(f"✓ 板块映射: {len(sector_map)}只股票有板块信息")
print(f"  耗时: {time.time()-t5:.1f}s")

print(f"\n步骤6: 一红定江山...")
t6 = time.time()
yihong_candidates = []
df_high_open = df_today_auc[(df_today_auc['ts_code'].isin(stock_pool)) & 
                            (df_today_auc['pct_chg'] > 0) & 
                            (df_today_auc['pct_chg'] <= 4)]
batch_codes = df_high_open['ts_code'].tolist()

# 保存已获取的昨日数据，后续用于大盘爆量筛选
df_yesterday_all_for_market = pd.DataFrame()

if batch_codes:
    df_yesterday_list = []
    for i in range(0, len(batch_codes), 800):
        batch = batch_codes[i:i+800]
        df_batch = pro.daily(trade_date=yesterday, ts_code=','.join(batch))
        if df_batch is not None and not df_batch.empty:
            df_yesterday_list.append(df_batch)
    
    df_yesterday_all = pd.concat(df_yesterday_list, ignore_index=True).set_index('ts_code') if df_yesterday_list else pd.DataFrame()
    df_yesterday_all_for_market = df_yesterday_all.copy()  # 保存副本用于大盘筛选
    
    for i in range(0, len(batch_codes), 50):
        df_hist = pro.daily(ts_code=','.join(batch_codes[i:i+50]), start_date=past_120_days[0], end_date=past_120_days[-1])
        if df_hist is not None:
            for code in batch_codes[i:i+50]:
                if code not in df_yesterday_all.index: continue
                code_hist = df_hist[df_hist['ts_code'] == code]
                if code_hist.empty: continue
                high_120 = code_hist['high'].max()
                limit_up_count = (code_hist['pct_chg'] >= 9.9).sum()
                yester = df_yesterday_all.loc[code]
                auction_price = df_high_open[df_high_open['ts_code'] == code]['price'].iloc[0]
                if yester['open'] <= high_120 and auction_price > high_120 and yester['high'] < high_120 and (yester['close'] - high_120) / high_120 > -0.03 and limit_up_count > 1:
                    yihong_candidates.append({
                        'code': code, 
                        'name': stock_name_map.get(code, '未知'), 
                        'pct_chg': df_high_open[df_high_open['ts_code'] == code]['pct_chg'].iloc[0],
                        'sectors': sector_map.get(code, ['无'])
                    })

print(f"✓ 一红定江山: {len(yihong_candidates)}只")
print(f"  耗时: {time.time()-t6:.1f}s")

print(f"\n步骤6.5: 大盘爆量高开（排除连板天梯）...")
t6_5 = time.time()
# 排除连板天梯的股票
ladder_codes = df_ladder['ts_code'].tolist()
market_explode_stocks = []

# 只处理高开0-8%的股票（排除连板天梯）
df_market_high_open = df_today_auc[(df_today_auc['ts_code'].isin(stock_pool)) & 
                                   (~df_today_auc['ts_code'].isin(ladder_codes)) &  # 排除连板天梯
                                   (df_today_auc['pct_chg'] > 0) & 
                                   (df_today_auc['pct_chg'] <= 8)]

market_codes_to_check = df_market_high_open['ts_code'].tolist()[:100]  # 只检查前100只，避免太慢

for code in market_codes_to_check:
    # 先看是否在已获取的昨日数据中
    if code in df_yesterday_all_for_market.index:
        yesterday_vol = df_yesterday_all_for_market.loc[code, 'vol']
    else:
        # 如果没有，单独获取
        df_single = pro.daily(ts_code=code, trade_date=yesterday)
        if df_single is None or df_single.empty:
            continue
        yesterday_vol = df_single.iloc[0]['vol']
    
    # 获取前3日数据 - 使用真实交易日
    if len(trading_dates) >= 5:
        past_3_for_this = trading_dates[-5:-2]
    else:
        continue
        
    df_hist_3d = pro.daily(ts_code=code, start_date=past_3_for_this[0], end_date=past_3_for_this[-1])
    if df_hist_3d is None or len(df_hist_3d) < 3:
        continue
    
    avg_vol_3d = df_hist_3d['vol'].mean()
    
    # 判断爆量
    if avg_vol_3d > 0 and yesterday_vol >= avg_vol_3d * 3:
        auc_pct = df_market_high_open[df_market_high_open['ts_code'] == code]['pct_chg'].iloc[0]
        market_explode_stocks.append({
            'code': code,
            'name': stock_name_map.get(code, '未知'),
            'yesterday_vol': yesterday_vol,
            'avg_vol_3d': avg_vol_3d,
            'vol_ratio': yesterday_vol / avg_vol_3d,
            'today_pct': auc_pct,
            'sectors': sector_map.get(code, ['无'])
        })

# 按爆量倍数排序，取前5
market_explode_stocks = sorted(market_explode_stocks, key=lambda x: x['vol_ratio'], reverse=True)[:5]
print(f"✓ 大盘爆量高开（排除连板）: {len(market_explode_stocks)}只")
print(f"  耗时: {time.time()-t6_5:.1f}s")

print(f"\n步骤7: 获取涨停原因...")
t7 = time.time()
# 获取涨停原因（所有相关股票）
all_codes = list(set([s['code'] for s in explode_high_open] + 
                     [s['code'] for s in yihong_candidates] + 
                     [s['code'] for s in market_explode_stocks]))  # 加上大盘爆量股票
zt_reason_dict = {}
if all_codes:
    past_15_start = (datetime.strptime(yesterday, '%Y%m%d') - timedelta(days=15)).strftime('%Y%m%d')
    df_kpl_all = pro.kpl_list(ts_code=','.join(all_codes), start_date=past_15_start, end_date=yesterday, list_type='limit_up')
    if df_kpl_all is not None and not df_kpl_all.empty:
        for code in all_codes:
            code_kpl = df_kpl_all[df_kpl_all['ts_code'] == code]
            if not code_kpl.empty:
                zt_reason_dict[code] = code_kpl.sort_values('trade_date').iloc[-1].get('lu_desc', '未知')

print(f"✓ 涨停原因: {len(zt_reason_dict)}只股票")
print(f"  耗时: {time.time()-t7:.1f}s")

# ============================================================================
# 构建融合报告
# ============================================================================
print(f"\n步骤8: 构建融合报告...")
content_lines = [f"📊 {today} 连板天梯+爆量+一红\n"]

# 1. 连板爆量+高开
if explode_high_open:
    content_lines.extend(["\n【连板爆量+高开】", 
                         f"共{len(explode_high_open)}只股票\n"])
    
    # 按连板数分组
    from collections import defaultdict
    nums_groups = defaultdict(list)
    for s in explode_high_open:
        nums_groups[s['nums']].append(s)
    
    for nums in sorted(nums_groups.keys(), reverse=True):
        stocks = sorted(nums_groups[nums], key=lambda x: x['today_pct'], reverse=True)
        content_lines.append(f"\n🔥 {nums}连板 ({len(stocks)}只)")
        for s in stocks:
            sectors_str = '、'.join(s['sectors'][:3])
            zt_reason = zt_reason_dict.get(s['code'], '未知')
            info = sector_open_zt.get(s['sectors'][0], {}) if s['sectors'] and s['sectors'][0] != '无' else {}
            open_str = f"{info['open_pct']:+.2f}%" if info.get('open_pct') is not None else "-"
            zt_str = f"{info['zt_count']}只" if info.get('zt_count') is not None else "-"
            content_lines.extend([
                f"  {s['name']}({s['code']})",
                f"  所属概念: {sectors_str}",
                f"  板块今日高开: {open_str}  板块内涨停: {zt_str}",
                f"  涨停原因: {zt_reason}",
                f"  竞价: {s['today_pct']:+.2f}% | 爆量: {s['vol_ratio']:.1f}倍"
            ])
else:
    content_lines.append("\n【连板爆量+高开】今日无")

# 2. 一红定江山
if yihong_candidates:
    content_lines.extend(["\n\n【一红定江山】",
                         f"共{len(yihong_candidates)}只股票\n"])
    
    yihong_sorted = sorted(yihong_candidates, key=lambda x: x['pct_chg'], reverse=True)
    for s in yihong_sorted:
        sectors_str = '、'.join(s['sectors'][:3])
        zt_reason = zt_reason_dict.get(s['code'], '未知')
        info = sector_open_zt.get(s['sectors'][0], {}) if s['sectors'] and s['sectors'][0] != '无' else {}
        open_str = f"{info['open_pct']:+.2f}%" if info.get('open_pct') is not None else "-"
        zt_str = f"{info['zt_count']}只" if info.get('zt_count') is not None else "-"
        content_lines.extend([
            f"  {s['name']}({s['code']})",
            f"  所属概念: {sectors_str}",
            f"  板块今日高开: {open_str}  板块内涨停: {zt_str}",
            f"  涨停原因: {zt_reason}",
            f"  竞价: {s['pct_chg']:+.2f}%"
        ])
else:
    content_lines.append("\n\n【一红定江山】今日无")

# 3. 大盘爆量高开（排除连板天梯）
if market_explode_stocks:
    content_lines.extend(["\n\n【大盘爆量高开】（排除连板天梯）",
                         f"前{len(market_explode_stocks)}只（按爆量倍数排序）\n"])
    
    for s in market_explode_stocks:
        sectors_str = '、'.join(s['sectors'][:3])
        zt_reason = zt_reason_dict.get(s['code'], '未知')
        info = sector_open_zt.get(s['sectors'][0], {}) if s['sectors'] and s['sectors'][0] != '无' else {}
        open_str = f"{info['open_pct']:+.2f}%" if info.get('open_pct') is not None else "-"
        zt_str = f"{info['zt_count']}只" if info.get('zt_count') is not None else "-"
        content_lines.extend([
            f"  {s['name']}({s['code']})",
            f"  所属概念: {sectors_str}",
            f"  板块今日高开: {open_str}  板块内涨停: {zt_str}",
            f"  涨停原因: {zt_reason}",
            f"  竞价: {s['today_pct']:+.2f}% | 爆量: {s['vol_ratio']:.1f}倍"
        ])
else:
    content_lines.append("\n\n【大盘爆量高开】今日无")

content_lines.append(f"\n\n⏱️ 总耗时: {time.time()-start_time:.1f}秒")

final_content = '\n'.join(content_lines)

# 支持 --no-push --output-file 供统一入口调用（先写文件再 print，避免 Windows GBK/emoji 报错）
import sys
do_push, out_file = True, None
argv = sys.argv
for i, a in enumerate(argv):
    if a == '--no-push': do_push = False
    if a == '--output-file' and i + 1 < len(argv): out_file = argv[i + 1]
if out_file:
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(final_content)
    sys.exit(0)
if not do_push:
    print("\n(未推送)")
    sys.exit(0)
print("\n" + "="*70)
try:
    print(final_content)
except UnicodeEncodeError:
    print(final_content.encode('utf-8', errors='replace').decode('utf-8'))
print("="*70)

# 推送
requests.post("http://www.pushplus.plus/send", 
             json={"token": "66c0490b50c34e74b5cc000232b1d23c", 
                   "title": f"连板爆量+一红 {today}", 
                   "content": final_content, 
                   "template": "txt", 
                   "channel": "wechat"})

print(f"\n✅ 推送完成！")