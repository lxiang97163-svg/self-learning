# -*- coding: utf-8 -*-
"""
拉取今日各题材完整验证链数据（竞价涨幅+现价涨幅）
"""
import requests, json

session = requests.Session()
session.trust_env = False
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn'
}

# 电力题材（韭研2026-03-26 电力板块）
elec = {
    'sz000720': ('新能泰山', '3天3板', 0),
    'sh600726': ('华电能源', '13天8板', 0),
    'sz000722': ('湖南发展', '3天3板', 13),
    'sh600163': ('中闽能源', '2天2板', 1),
    'sz000767': ('晋控电力', '首板', 0),
}

# 锂电产业链（韭研2026-03-26 锂电产业链板块，按板数+涨停时间排序取前5）
lith = {
    'sz002192': ('融捷股份',  '3天3板', 9),
    'sh603937': ('丽岛新材',  '3天2板', 0),
    'sh603520': ('司太立',    '首板',   0),
    'sh601515': ('东方锆业',  '首板',   0),
    'sz002263': ('隆华科技',  '首板',   0),
}

# 算力/华为（低吸候选）
other = {
    'sh600666': ('奥瑞德',   '首板',   0),
    'sz002491': ('通鼎互联', '首板',   0),
    'sh605299': ('舒华体育', '首板',   0),
    'sz002309': ('中利集团', '首板',   0),
    'sh000001': ('上证指数', '-',      0),
}

all_codes = {**elec, **lith, **other}
codes_str = ','.join(all_codes.keys())
url = 'https://hq.sinajs.cn/list=' + codes_str
r = session.get(url, headers=headers, timeout=15)
r.encoding = 'gbk'

parsed = {}
for line in r.text.strip().split('\n'):
    if not line.strip():
        continue
    code = line.split('hq_str_')[1].split('=')[0]
    data = line.split('"')[1].split(',')
    if len(data) < 10:
        continue
    yclose = float(data[2]) if data[2] else 0
    topen  = float(data[1]) if data[1] else 0
    now    = float(data[3]) if data[3] else 0
    high   = float(data[4]) if data[4] else 0
    low    = float(data[5]) if data[5] else 0
    amount = float(data[9]) if data[9] else 0
    opct   = (topen - yclose) / yclose * 100 if yclose > 0 else 0
    npct   = (now - yclose) / yclose * 100 if yclose > 0 else 0
    parsed[code] = {
        'yclose': yclose, 'topen': topen, 'now': now,
        'high': high, 'low': low, 'amount': amount,
        'opct': opct, 'npct': npct,
    }

def fmt_pct(v):
    return '%+.1f%%' % v

def judge_open(opct):
    if opct >= 9.5:  return '★封死'
    if opct >= 5.0:  return '↑高开强'
    if opct >= 2.0:  return '↑高开'
    if opct >= 0:    return '→平开'
    if opct >= -3.0: return '↓小低开'
    return '▼大低开'

def now_status(npct):
    if npct >= 9.5:  return '[涨停]'
    if npct <= -9.5: return '[跌停]'
    if npct <= -5:   return '[大跌]'
    if npct >= 5:    return '[强势]'
    return ''

# 输出
def print_chain(title, stocks_dict, intro=''):
    print()
    print('【%s】%s' % (title, intro))
    print('%-4s %-10s %-8s %-6s %8s %8s  %-8s  %s' % (
        '顺位', '股票', '板数/开板', '昨收', '竞价涨幅', '现价涨幅', '竞价判断', '现状'))
    print('-' * 72)
    for i, (code, (name, ban, kbcs)) in enumerate(stocks_dict.items(), 1):
        d = parsed.get(code, {})
        opct = d.get('opct', 0)
        npct = d.get('npct', 0)
        yclose = d.get('yclose', 0)
        ban_str = ban + ('/%d次开' % kbcs if kbcs > 0 else '')
        print('龙%-3d %-10s %-10s %6.2f %8s %8s  %-8s  %s' % (
            i, name, ban_str, yclose,
            fmt_pct(opct), fmt_pct(npct),
            judge_open(opct), now_status(npct)))

print_chain('电力题材', elec, '  判断锚：新能泰山')
print_chain('锂电产业链', lith, '  判断锚：融捷股份')

# 低吸候选单独输出
print()
print('【低吸候选 / 大盘参考】')
print('%-4s %-10s %-8s %6s %8s %8s  %-8s  %s' % (
    '类型', '股票', '板数', '昨收', '竞价涨幅', '现价涨幅', '竞价判断', '现状'))
print('-' * 72)
labels = {'sh600666':'算力龙一','sz002491':'算力龙二','sh605299':'华为龙一','sz002309':'华为龙二','sh000001':'上证指数'}
for code, (name, ban, _) in other.items():
    d = parsed.get(code, {})
    opct = d.get('opct', 0)
    npct = d.get('npct', 0)
    yclose = d.get('yclose', 0)
    print('%-10s %-10s %-8s %6.2f %8s %8s  %-8s  %s' % (
        labels.get(code,''), name, ban, yclose,
        fmt_pct(opct), fmt_pct(npct),
        judge_open(opct), now_status(npct)))

# 综合健康度判断
print()
print('=' * 72)
print('9:25竞价结束时 — 题材健康度综合判断')
print('=' * 72)

def health_check(stocks_dict, title):
    vals = [(code, parsed.get(code,{}).get('opct',0)) for code in stocks_dict]
    high = sum(1 for _,v in vals if v >= 2)
    low  = sum(1 for _,v in vals if v < -3)
    l1_opct = vals[0][1] if vals else 0
    l2_opct = vals[1][1] if len(vals)>1 else 0
    print()
    print('%s：' % title)
    print('  高开(>+2%%)：%d/5只  低开(<-3%%)：%d/5只' % (high, low))
    if l1_opct >= 9.5:
        l1_msg = '龙一封死买不上'
    elif l1_opct >= 2:
        l1_msg = '龙一可操作'
    else:
        l1_msg = '龙一弱，不做'
    if l2_opct >= 0:
        l2_msg = '龙二跟涨'
    elif l2_opct >= -3:
        l2_msg = '龙二平开偏弱'
    else:
        l2_msg = '龙二低开！分化警报'
    if high >= 3:
        health = '健康，多股跟涨'
    elif high >= 2 and low <= 1:
        health = '一般，龙一轻仓快出'
    else:
        health = '分化，谨慎'
    print('  %s | %s | 综合：%s' % (l1_msg, l2_msg, health))

health_check(elec, '电力')
health_check(lith, '锂电产业链')
