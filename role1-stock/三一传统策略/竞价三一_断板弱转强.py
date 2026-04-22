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
import requests, json
from collections import Counter
import time

start_time = time.time()
TOKEN, TOKEN_MIN = 'e95696cde1bc72c2839d1c9cc510ab2cf33', 'ne34e6697159de73c228e34379b510ec554'
ts.set_token(TOKEN); tss.set_token(TOKEN_MIN)
pro, pro_min = ts.pro_api(), tss.pro_api()

# 获取交易日
today = datetime.now().strftime('%Y%m%d')
try:
    df_index_recent = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=15)).strftime('%Y%m%d'), end_date=today)
except pd.errors.EmptyDataError:
    ts.set_token(TOKEN); tss.set_token(TOKEN_MIN)
    pro, pro_min = ts.pro_api(), tss.pro_api()
    df_index_recent = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=15)).strftime('%Y%m%d'), end_date=today)
if df_index_recent is None or df_index_recent.empty: exit("⚠️ 无法获取交易日数据")
trading_dates_recent = df_index_recent.sort_values('trade_date', ascending=False)['trade_date'].tolist()
if len(trading_dates_recent) < 2: exit("⚠️ 交易日数据不足")
yesterday, day_before_yesterday = trading_dates_recent[0], trading_dates_recent[1]
print(f"今日: {today}\n昨日: {yesterday}\n前日: {day_before_yesterday}")

df_index_120 = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=200)).strftime('%Y%m%d'), end_date=yesterday)
trading_dates = df_index_120.sort_values('trade_date')['trade_date'].tolist() if df_index_120 is not None else []
if len(trading_dates) < 122: exit("⚠️ 交易日数据不足")

# 数据完整性检测
print("="*70 + "\n📊 数据完整性检测\n" + "="*70)
deadline = datetime.now().replace(hour=9, minute=28, second=0)
while datetime.now() < deadline:
    df_today_check, df_yester_check = pro_min.stk_auction(trade_date=today), pro_min.stk_auction(trade_date=yesterday)
    if df_today_check is None or df_today_check.empty:
        print(f"⚠️ 等待数据... 距9:28还有{int((deadline - datetime.now()).total_seconds())}秒")
        time.sleep(10)
        continue
    if df_yester_check is None or df_yester_check.empty: break
    diff_pct = abs(len(df_today_check) - len(df_yester_check)) / len(df_yester_check) * 100
    print(f"✓ 今:{len(df_today_check)} 昨:{len(df_yester_check)} 差异:{diff_pct:.2f}%")
    if diff_pct < 2.0:
        print(f"✅ 检测通过")
        break
    time.sleep(10)
print("="*70 + "\n")

# 股票池
df_stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
stock_pool = set(df_stocks[(~df_stocks['name'].str.contains('ST', na=False)) & (~df_stocks['ts_code'].str.endswith('.BJ')) & (~df_stocks['ts_code'].str.startswith(('688', '300', '301')))]['ts_code'])
market_pool = set(df_stocks[(~df_stocks['name'].str.contains('ST', na=False)) & (~df_stocks['ts_code'].str.endswith('.BJ')) & (~df_stocks['ts_code'].str.startswith('688'))]['ts_code'])
stock_name_map = dict(zip(df_stocks['ts_code'], df_stocks['name']))

# 竞价数据
df_today_auc = pro_min.stk_auction(trade_date=today)
if df_today_auc is None or df_today_auc.empty: exit()
df_yester_auc = pro_min.stk_auction(trade_date=yesterday)
yester_amt_map = dict(zip(df_yester_auc['ts_code'], df_yester_auc['amount'])) if df_yester_auc is not None else {}

df_today_auc['name'] = df_today_auc['ts_code'].map(stock_name_map)
df_today_auc['amount_wan'] = df_today_auc['amount'] / 10000
df_today_auc['pct_chg'] = (df_today_auc['price'] - df_today_auc['pre_close']) / df_today_auc['pre_close'] * 100
df_today_auc['auction_ratio'] = df_today_auc.apply(lambda x: x['amount'] / yester_amt_map.get(x['ts_code'], 1) if yester_amt_map.get(x['ts_code'], 0) > 0 else 0, axis=1)
df_today_auc['turnover_rate'] = df_today_auc.get('turnover_rate', pd.Series([0]*len(df_today_auc))).fillna(0)

# 市值数据 - 获取流通市值
df_basic = pro.daily_basic(trade_date=yesterday, fields='ts_code,circ_mv,total_mv,float_share,close')
circ_mv_map = {}  # 创建流通市值映射字典
if df_basic is not None:
    df_basic['total_mv_yi'] = (df_basic['total_mv'] / 10000).fillna(0).astype(int)
    df_basic['circ_mv_yi'] = (df_basic['circ_mv'] / 10000).fillna(0)  # 流通市值转为亿元
    df_basic['float_mv'] = df_basic['float_share'] * df_basic['close'] / 10000
    circ_mv_map = dict(zip(df_basic['ts_code'], df_basic['circ_mv_yi']))  # 构建流通市值映射
    df_today_auc = df_today_auc.merge(df_basic[['ts_code', 'total_mv_yi', 'float_mv', 'circ_mv_yi']], on='ts_code', how='left').fillna({'total_mv_yi': 0, 'circ_mv_yi': 0})

# ============================================================================
# 情绪指标计算（新增）
# ============================================================================
def calculate_sentiment_indicator():
    """计算市场情绪指标"""
    # 1. 获取昨日日线数据，计算日内涨跌幅
    df_yesterday_daily = pro.daily(trade_date=yesterday)
    if df_yesterday_daily is None or df_yesterday_daily.empty:
        return None, None
    
    # 过滤股票池并计算日内涨跌幅
    df_yesterday_filtered = df_yesterday_daily[df_yesterday_daily['ts_code'].isin(stock_pool)].copy()
    df_yesterday_filtered = df_yesterday_filtered[df_yesterday_filtered['open'] > 0].copy()
    df_yesterday_filtered['intraday_chg'] = (
        (df_yesterday_filtered['close'] - df_yesterday_filtered['open']) / 
        df_yesterday_filtered['open'] * 100
    )
    
    # 2. 获取昨日日内涨跌幅前10
    df_top10 = df_yesterday_filtered.nlargest(10, 'intraday_chg')
    df_bottom10 = df_yesterday_filtered.nsmallest(10, 'intraday_chg')
    
    top10_codes = df_top10['ts_code'].tolist()
    bottom10_codes = df_bottom10['ts_code'].tolist()
    
    # 3. 计算加权涨跌幅
    def calc_weighted(codes):
        valid = []
        for code in codes:
            auc = df_today_auc[df_today_auc['ts_code'] == code]
            if auc.empty:
                continue
            valid.append({
                'pct_chg': auc['pct_chg'].iloc[0],
                'circ_mv': circ_mv_map.get(code, 1)
            })
        if not valid:
            return None
        total_mv = sum(s['circ_mv'] for s in valid)
        return sum(s['pct_chg'] * s['circ_mv'] for s in valid) / total_mv
    
    top10_weighted = calc_weighted(top10_codes)
    bottom10_weighted = calc_weighted(bottom10_codes)
    
    if top10_weighted is None or bottom10_weighted is None:
        return None, None
    
    # 4. 综合情绪指标
    overall_sentiment = (top10_weighted + bottom10_weighted) / 2
    
    # 5. 情绪等级
    if overall_sentiment > 1:
        sentiment_label = "🔥🔥 强势正向"
    elif overall_sentiment > 0:
        sentiment_label = "🔥 偏正向"
    elif overall_sentiment > -1:
        sentiment_label = "❄️ 偏负向"
    else:
        sentiment_label = "❄️❄️ 强势负向"
    
    return overall_sentiment, sentiment_label

# 计算情绪指标
sentiment_score, sentiment_label = calculate_sentiment_indicator()

# 涨停与候选股
df_zhaban, df_prev_zt, df_cur_zt = pro.limit_list_d(trade_date=yesterday, limit_type='Z'), pro.limit_list_d(trade_date=day_before_yesterday, limit_type='U'), pro.limit_list_d(trade_date=yesterday, limit_type='U')
zhaban = [s for s in (df_zhaban['ts_code'].tolist() if df_zhaban is not None else []) if s in stock_pool]
duanban = list(set([s for s in (df_prev_zt['ts_code'].tolist() if df_prev_zt is not None else []) if s in stock_pool]) - set(df_cur_zt['ts_code'].tolist() if df_cur_zt is not None else []))
candidates = list(set(zhaban + duanban))

# 过滤大阴线
if candidates:
    df_yester_daily = pro.daily(trade_date=yesterday, ts_code=','.join(candidates))
    if df_yester_daily is not None and not df_yester_daily.empty:
        yin_dict = {idx: (row['close'] - row['open'])/row['open'] for idx, row in df_yester_daily.set_index('ts_code').iterrows() if row['open'] > 0}
        candidates = [c for c in candidates if yin_dict.get(c, -1) >= -0.06]

# 人气榜与热股榜
df_hot = pro.dc_hot(market='A股市场', hot_type='人气榜', trade_date=yesterday, fields='ts_code,rank')
hot_rank_map = dict(zip(df_hot['ts_code'], df_hot['rank'])) if df_hot is not None else {}
df_hot_stocks = pro.ths_hot(trade_date=yesterday, market='热股', is_new='Y')
ths_hot_rank_map = dict(zip(df_hot_stocks['ts_code'], df_hot_stocks['rank'])) if isinstance(df_hot_stocks, pd.DataFrame) else {}

# 涨停原因(获取所有相关股票的涨停原因)
zt_reason_dict = {}

# 获取candidates的涨停原因
if candidates:
    df_kpl = pro.kpl_list(ts_code=','.join(candidates), start_date=(datetime.strptime(yesterday, '%Y%m%d') - timedelta(days=15)).strftime('%Y%m%d'), end_date=yesterday, list_type='limit_up')
    if df_kpl is not None and not df_kpl.empty:
        for code in candidates:
            code_kpl = df_kpl[df_kpl['ts_code'] == code]
            if not code_kpl.empty: zt_reason_dict[code] = code_kpl.sort_values('trade_date').iloc[-1].get('lu_desc', '未知')

# 获取昨日所有涨停股票的涨停原因(用于首板、二板、高度板、弱转强)
if df_cur_zt is not None and not df_cur_zt.empty:
    yesterday_zt_codes = df_cur_zt['ts_code'].tolist()
    df_kpl_zt = pro.kpl_list(ts_code=','.join(yesterday_zt_codes), start_date=yesterday, end_date=yesterday, list_type='limit_up')
    if df_kpl_zt is not None and not df_kpl_zt.empty:
        for code in yesterday_zt_codes:
            if code not in zt_reason_dict:  # 避免覆盖已有的
                code_kpl = df_kpl_zt[df_kpl_zt['ts_code'] == code]
                if not code_kpl.empty: zt_reason_dict[code] = code_kpl.iloc[0].get('lu_desc', '未知')

# 题材情绪
topic_strength_list = []
df_topics = pro.kpl_concept(trade_date=yesterday)
if df_topics is not None:
    for _, topic in df_topics.head(20).iterrows():
        df_cons = pro.kpl_concept_cons(ts_code=topic['ts_code'], trade_date=yesterday)
        if df_cons is not None and len(df_cons) >= 3:
            avg_pct = df_today_auc[df_today_auc['ts_code'].isin(df_cons['con_code'])]['pct_chg'].mean()
            if pd.notna(avg_pct): topic_strength_list.append({'name': topic['name'], 'avg_pct': avg_pct})
        if len(topic_strength_list) >= 10: break
    topic_strength_list = sorted(topic_strength_list, key=lambda x: x['avg_pct'], reverse=True)[:5]

# 核心股板块（并用于今日推荐的 所属概念/板块高开/板块内涨停）
all_core_stocks = []
sector_results = []
df_cpt = pro.limit_cpt_list(trade_date=yesterday)
if isinstance(df_cpt, pd.DataFrame) and not df_cpt.empty:
    for _, sector in df_cpt.nsmallest(10, 'rank').iterrows():
        df_members = pro.ths_member(ts_code=sector['ts_code'], fields='con_code')
        if df_members is None or df_members.empty: continue
        df_sector = df_today_auc[df_today_auc['ts_code'].isin(df_members['con_code'].tolist())]
        if df_sector.empty: continue
        weighted_pct = (df_sector['pct_chg'] * df_sector.get('float_mv', 1)).sum() / df_sector.get('float_mv', 1).sum() if 'float_mv' in df_sector.columns else df_sector['pct_chg'].mean()
        sector_results.append({'name': sector['name'], 'weighted_pct': weighted_pct, 'codes': df_members['con_code'].tolist()})
    
    sector_results = sorted(sector_results, key=lambda x: x['weighted_pct'], reverse=True)[:5]
    for sector in sector_results:
        sector_stocks = []
        for code in sector['codes']:
            auc = df_today_auc[df_today_auc['ts_code'] == code]
            if not auc.empty and ths_hot_rank_map.get(code, 9999) < 9999:
                sector_stocks.append({'code': code, 'name': stock_name_map.get(code, '未知'), 'sector_name': sector['name'], 'today_pct': auc['pct_chg'].iloc[0], 'hot_rank': ths_hot_rank_map[code]})
        all_core_stocks.extend(sorted(sector_stocks, key=lambda x: x['hot_rank'])[:5])

# 通用排序
def get_best(codes, n):
    counts = Counter(codes)
    return sorted(counts.keys(), key=lambda x: (-counts[x], hot_rank_map.get(x, 9999), df_today_auc[df_today_auc['ts_code']==x]['total_mv_yi'].iloc[0] if not df_today_auc[df_today_auc['ts_code']==x].empty else 999999))[:n]

# 断板混合
jingjia_stocks, res_31, res_32, best_lb = set(), [], [], None
if candidates:
    df_zd = df_today_auc[(df_today_auc['ts_code'].isin(candidates)) & (df_today_auc['pct_chg'] >= -2)]
    if not df_zd.empty:
        t1, t2, t3 = df_zd.nlargest(1, 'amount_wan')['ts_code'].tolist(), df_zd.nlargest(1, 'turnover_rate')['ts_code'].tolist(), df_zd.nlargest(3, 'pct_chg')['ts_code'].tolist()
        res_31, res_32 = get_best(t1 + t2, 1), get_best(t1 + t2 + t3, 2)
        best_lb = df_zd.loc[df_zd['auction_ratio'].idxmax()]
        jingjia_stocks.update(t1 + t2 + t3)

# 市场三一
df_market = df_today_auc[df_today_auc['ts_code'].isin(market_pool) & (df_today_auc['pct_chg'] >= 0)]
market_res_31, market_res_32, market_best_lb = [], [], None
if not df_market.empty:
    t1, t2 = df_market.nlargest(1, 'amount_wan')['ts_code'].tolist(), df_market.nlargest(1, 'turnover_rate')['ts_code'].tolist()
    t3 = df_market.sort_values(['pct_chg', 'amount_wan'], ascending=False).head(3)['ts_code'].tolist()
    market_res_31, market_res_32 = get_best(t1 + t2, 1), get_best(t1 + t2 + t3, 2)
    market_best_lb = df_market.loc[df_market['auction_ratio'].idxmax()]
    jingjia_stocks.update(t1 + t2 + t3)

# 各板块三一
df_yesterday_zt = pro.limit_list_d(trade_date=yesterday, limit_type='U')
board_configs = {}
if df_yesterday_zt is not None and not df_yesterday_zt.empty:
    board_configs = {
        '首板': set(df_yesterday_zt[df_yesterday_zt['limit_times'] == 1]['ts_code']),
        '二板': set(df_yesterday_zt[df_yesterday_zt['limit_times'] == 2]['ts_code']),
        '高度板': set(df_yesterday_zt[df_yesterday_zt['limit_times'] >= 3]['ts_code']),
        '弱转强': set(df_yesterday_zt[pd.to_numeric(df_yesterday_zt['last_time'], errors='coerce').fillna(0).astype(int) >= 130000]['ts_code'])
    }

board_results = {}
for name, codes in board_configs.items():
    df_b = df_today_auc[(df_today_auc['ts_code'].isin(stock_pool & codes)) & (df_today_auc['pct_chg'] >= 0)]
    if not df_b.empty:
        t1, t2, t3 = df_b.nlargest(1, 'amount_wan')['ts_code'].tolist(), df_b.nlargest(1, 'turnover_rate')['ts_code'].tolist(), df_b.nlargest(3, 'pct_chg')['ts_code'].tolist()
        board_results[name] = {'res_31': get_best(t1+t2, 1), 'res_32': get_best(t1+t2+t3, 2), 'best_lb': df_b.loc[df_b['auction_ratio'].idxmax()] if df_b['auction_ratio'].max() > 0 else None}

# 交集
intersection = {}
for code in jingjia_stocks & set([s['code'] for s in all_core_stocks]):
    s = next((x for x in all_core_stocks if x['code'] == code), None)
    if s: intersection[code] = {'code': code, 'name': s['name'], 'sector': s['sector_name'], 'pct_chg': s['today_pct'], 'rank': s['hot_rank']}
intersection_details = sorted(intersection.values(), key=lambda x: x['pct_chg'], reverse=True)

# 今日推荐
recommendations = []
for res, cat in [(res_31, '断板混合'), (board_results.get('首板', {}).get('res_31'), '首板三一'), (board_results.get('二板', {}).get('res_31'), '二板三一'), 
                 (board_results.get('高度板', {}).get('res_31'), '高度板三一'), (board_results.get('弱转强', {}).get('res_31'), '弱转强三一'), (market_res_31, '市场三一')]:
    if res:
        sd = df_today_auc[df_today_auc['ts_code'] == res[0]]
        if not sd.empty: 
            recommendations.append({
                'code': res[0], 
                'name': stock_name_map.get(res[0], '未知'), 
                'cat': cat, 
                'pct': sd['pct_chg'].iloc[0], 
                'rank': hot_rank_map.get(res[0], 9999),
                'reason': zt_reason_dict.get(res[0], '未知'),
                'circ_mv': circ_mv_map.get(res[0], 0)  # 添加流通市值
            })

seen, unique_rec = set(), []
for r in recommendations:
    if r['code'] not in seen: unique_rec.append(r); seen.add(r['code'])
    else:
        for u in unique_rec:
            if u['code'] == r['code']: u['cat'] += f"+{r['cat']}"; break

# 为今日推荐每只股挂上 所属概念、板块今日高开、板块内涨停
yesterday_zt_set = set(df_yesterday_zt['ts_code']) if df_yesterday_zt is not None and not df_yesterday_zt.empty else set()
for s in sector_results:
    s['zt_count'] = sum(1 for c in s['codes'] if c in yesterday_zt_set)
code_to_sector = {}
for s in sector_results:
    for c in s['codes']:
        code_to_sector[c] = {'name': s['name'], 'weighted_pct': s['weighted_pct'], 'zt_count': s['zt_count']}
for r in unique_rec:
    info = code_to_sector.get(r['code'], {})
    r['sector_name'] = info.get('name') or r.get('reason') or '未知'
    r['sector_open'] = info.get('weighted_pct')  # None 表示未匹配到涨停概念榜
    r['sector_zt_count'] = info.get('zt_count')

# 构建报告
lines = [f"📊 {today} 竞价统计(快报)\n"]
if topic_strength_list: lines.append("【题材情绪】" + "、".join([f"{t['name']}({t['avg_pct']:.2f}%)" for t in topic_strength_list]) + "\n")

# ============================================================================
# 插入情绪指标（在题材情绪下方）
# ============================================================================
if sentiment_score is not None:
    lines.append(f"【市场情绪】综合指标: {sentiment_score:+.2f}% | {sentiment_label}\n")

lines.append("🎯 【核心股交集】" + ("\n" + "\n".join([f"  {s['name']} {s['sector']} 竞价{s['pct_chg']:+.2f}% rank{s['rank']}" for s in intersection_details]) + "\n" if intersection_details else "今日无交集\n"))

# 【今日推荐】部分：流通市值 + 所属概念、板块今日高开、板块内涨停
def _rec_sector_line(r):
    name = r.get('sector_name', '-')
    open_str = f"{r['sector_open']:+.2f}%" if r.get('sector_open') is not None else "-"
    zt = r.get('sector_zt_count')
    zt_str = f"{zt}只" if zt is not None else "-"
    return f"  所属概念:{name}  板块今日高开:{open_str}  板块内涨停:{zt_str}"
lines.append("⭐ 【今日推荐】" + (
    "\n" + "\n".join([
        f"  {r['name']} [{r['cat']}]\n"
        f"  竞价{r['pct']:+.2f}% {'rank'+str(r['rank']) if r['rank']<9999 else '无rank'} 流通市值{r['circ_mv']:.1f}亿  原因:{r['reason']}\n"
        + _rec_sector_line(r)
        for r in unique_rec
    ]) + "\n" if unique_rec else "今日无推荐\n"
))

# 各分类详情
def add_sec(title, data):
    if data and data.get('res_31'):
        unknown = "未知"
        lines.extend([f"【{title}】", 
                     f"1、三一:{stock_name_map.get(data['res_31'][0])}({zt_reason_dict.get(data['res_31'][0], unknown)})",
                     f"2、三二:{'、'.join([f'{stock_name_map.get(c)}({zt_reason_dict.get(c, unknown)})' for c in data.get('res_32', [])])}" if data.get('res_32') else "2、三二:无",
                     f"3、量比:{data['best_lb']['name']}({zt_reason_dict.get(data['best_lb']['ts_code'], unknown)}) 量比:{data['best_lb']['auction_ratio']:.2f}\n" if data.get('best_lb') is not None else "3、量比:无\n"])
    else: lines.append(f"【{title}】无\n")

add_sec("断板混合", {'res_31': res_31, 'res_32': res_32, 'best_lb': best_lb})
for b in ['首板', '二板', '高度板', '弱转强']: add_sec(f"{b}三一", board_results.get(b, {}))
add_sec("市场三一", {'res_31': market_res_31, 'res_32': market_res_32, 'best_lb': market_best_lb})

# 核心股板块报告
if 'sector_results' in locals() and sector_results:
    lines.extend(["\n" + "="*70, "📊 板块核心股报告", "="*70, "\n🔥 高开板块前五\n"])
    lines.extend([f"{s['name']} 高开{s['weighted_pct']:.2f}%" for s in sector_results])
    lines.append("")
    
    sector_stock_map = {}
    for stock in all_core_stocks:
        if stock['sector_name'] not in sector_stock_map:
            sector_stock_map[stock['sector_name']] = []
        sector_stock_map[stock['sector_name']].append(stock)
    
    for sector in sector_results:
        lines.append(f"【{sector['name']}】高开 {sector['weighted_pct']:.2f}%")
        stocks = sector_stock_map.get(sector['name'], [])
        if stocks:
            for i, stock in enumerate(stocks, 1):
                lines.extend([f"{i}. {stock['name']}", f"   热股榜rank:{stock['hot_rank']} 今日竞价:{stock['today_pct']:+.2f}%"])
        else:
            lines.append("   暂无热股榜股票")
        lines.append("")

lines.append(f"⏱️ 耗时: {time.time()-start_time:.1f}秒\n💡 一红定江山正在计算中,稍后推送...")

content = '\n'.join(lines)

# 支持 --no-push --output-file 供统一入口调用（先写文件再 print，避免 Windows GBK/emoji 报错）
import sys
do_push, out_file = True, None
argv = sys.argv
for i, a in enumerate(argv):
    if a == '--no-push': do_push = False
    if a == '--output-file' and i + 1 < len(argv): out_file = argv[i + 1]
if out_file:
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(content)
    sys.exit(0)
if not do_push:
    print("\n(未推送)")
    sys.exit(0)
try:
    print(content)
except UnicodeEncodeError:
    print(content.encode('utf-8', errors='replace').decode('utf-8'))
requests.post("http://www.pushplus.plus/send", json={"token": "66c0490b50c34e74b5cc000232b1d23c", "title": f"竞价快报 {today}", "content": content, "template": "txt", "channel": "wechat"})
print(f"\n✅ 快报推送完成!总耗时: {time.time()-start_time:.1f}秒")