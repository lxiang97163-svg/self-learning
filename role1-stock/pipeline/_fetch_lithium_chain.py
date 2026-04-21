# -*- coding: utf-8 -*-
"""
锂电产业链题材验证链 - 竞价时段数据
韭研异动2026-03-26中锂电产业链全部10只
"""
import requests
import json

session = requests.Session()
session.trust_env = False
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn'
}

# 韭研数据中锂电产业链10只，附板数信息
stocks_info = {
    'sz002192': ('融捷股份',   '3天3板', '锂矿+锂电投资'),
    'sh603937': ('丽岛新材',   '3天2板', '铝塑膜+锂电结构件'),
    'sh601515': ('东方锆业',   '首板',   '锆材料+锂电前驱体'),
    'sz002263': ('隆华科技',   '首板',   '复合铜箔+隔膜'),
    'sh603520': ('司太立',     '首板',   '锂电材料+收购锂矿'),
    'sh603026': ('石英股份',   '首板',   '锂电材料+石英坩埚'),
    'sz301292': ('恒兴新材',   '未涨停', '锂电电解液'),
    'sz000973': ('佛塑科技',   '未涨停', '湿法隔膜+锂电隔膜'),
    'sz002759': ('天鹅股份',   '未涨停', '隔膜+锂电'),
    'sz002108': ('沧州明珠',   '未涨停', '锂电隔膜'),
}

codes_str = ','.join(stocks_info.keys())
url = 'https://hq.sinajs.cn/list=' + codes_str
r = session.get(url, headers=headers, timeout=15)
r.encoding = 'gbk'

print('=' * 78)
print('锂电产业链题材验证链 - 2026-03-27 竞价时段（9:25）还原')
print('数据来源：韭研异动2026-03-26，共10只')
print('=' * 78)
print()
print('%-4s %-10s %-8s %6s %6s %9s %9s  %s' % (
    '顺位', '股票', '板数', '昨收', '今开', '竞价涨幅', '现价涨幅', '竞价判断'))
print('-' * 78)

rows = []
for line in r.text.strip().split('\n'):
    if not line.strip():
        continue
    code = line.split('hq_str_')[1].split('=')[0]
    data = line.split('"')[1].split(',')
    if len(data) < 10 or code not in stocks_info:
        continue
    name, ban_shu, keywords = stocks_info[code]
    yclose = float(data[2])
    topen  = float(data[1])
    now    = float(data[3])
    opct   = (topen - yclose) / yclose * 100 if yclose > 0 else 0
    npct   = (now - yclose) / yclose * 100 if yclose > 0 else 0
    rows.append((code, name, ban_shu, yclose, topen, opct, now, npct, keywords))

# 按竞价涨幅排序
rows.sort(key=lambda x: -x[5])

for i, (code, name, ban_shu, yclose, topen, opct, now, npct, keywords) in enumerate(rows, 1):
    if opct >= 9.5:
        judge = '★封死涨停'
    elif opct >= 5.0:
        judge = '↑高开强'
    elif opct >= 2.0:
        judge = '↑适度高开'
    elif opct >= 0:
        judge = '→ 平开'
    elif opct >= -3.0:
        judge = '↓小幅低开'
    else:
        judge = '▼大幅低开'

    now_flag = ''
    if npct >= 9.5:
        now_flag = '[现涨停]'
    elif npct <= -5:
        now_flag = '[现大跌]'

    print('%-4d %-10s %-8s %6.2f %6.2f %+8.1f%% %+8.1f%%  %s %s' % (
        i, name, ban_shu, yclose, topen, opct, npct, judge, now_flag))

print()
print('=' * 78)
print('题材健康度判断（9:25竞价结束时）：')
print()

# 统计
high_open = sum(1 for r in rows if r[5] >= 2.0)
low_open  = sum(1 for r in rows if r[5] < -3.0)
flat      = sum(1 for r in rows if -3.0 <= r[5] < 2.0)
total     = len(rows)

print('  竞价高开(>+2%%)：%d只 / %d只' % (high_open, total))
print('  竞价平开(-3%%~+2%%)：%d只 / %d只' % (flat, total))
print('  竞价低开(<-3%%)：%d只 / %d只' % (low_open, total))
print()

# 龙一龙二状态
if rows:
    l1 = rows[0]
    l2 = rows[1] if len(rows) > 1 else None
    print('  龙一 %s 竞价%+.1f%%' % (l1[1], l1[5]))
    if l2:
        print('  龙二 %s 竞价%+.1f%%' % (l2[1], l2[5]))

print()
# 综合判断
if high_open >= 4:
    health = '题材健康，多股跟涨，龙一可操作'
elif high_open >= 2 and low_open <= 2:
    health = '题材一般，龙一可轻仓，注意快进快出'
else:
    health = '题材分化，低开股多，谨慎操作'

print('  综合判断：' + health)
print()
print('  介入融捷股份的验证条件：')
print('  1. 融捷竞价涨幅 > +2%%（今日：%+.1f%%）' % (rows[0][5] if rows else 0))

# 找丽岛新材
lido = next((r for r in rows if r[0] == 'sh603937'), None)
sita = next((r for r in rows if r[0] == 'sh603520'), None)
if lido:
    print('  2. 龙二丽岛新材竞价 > 0%%（今日：%+.1f%%）' % lido[5])
if sita:
    print('  3. 至少1只首板股竞价 > 0%%（司太立今日：%+.1f%%）' % sita[5])

# 最终结论
l1_ok = rows[0][5] >= 2.0 if rows else False
l2_ok = lido[5] >= 0 if lido else False
print()
if l1_ok and l2_ok:
    print('  -> 9:25结论：条件满足，融捷可操作（1-1.5成仓）')
elif l1_ok and not l2_ok:
    print('  -> 9:25结论：龙一强但龙二弱，融捷轻仓快出（0.5-1成），注意止损')
else:
    print('  -> 9:25结论：条件不满足，观望')
