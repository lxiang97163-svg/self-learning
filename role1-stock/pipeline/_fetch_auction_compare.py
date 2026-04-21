# -*- coding: utf-8 -*-
"""
还原今日竞价时段（9:25前）各股状态
用新浪分时接口拉取今日9:25前的竞价价格和成交额
同时拉取昨日收盘价作为基准
"""
import requests
import json

session = requests.Session()
session.trust_env = False
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn'
}

# 目标股票
stocks_map = {
    'sz000720': ('新能泰山', '电力-龙一'),
    'sh600726': ('华电能源', '电力-龙二'),
    'sz000722': ('湖南发展', '电力-龙三'),
    'sh600163': ('中闽能源', '电力-龙四'),
    'sz000767': ('晋控电力', '电力-补涨'),
    'sz002192': ('融捷股份', '锂电-龙一'),
    'sh603937': ('丽岛新材', '锂电-龙二'),
    'sh600666': ('奥瑞德',   '算力-龙一'),
    'sz002491': ('通鼎互联', '算力-龙二'),
    'sh605299': ('舒华体育', '华为-龙一'),
}

# 拉实时行情（含今开、昨收）
codes_str = ','.join(stocks_map.keys())
url = 'https://hq.sinajs.cn/list=' + codes_str
r = session.get(url, headers=headers, timeout=15)
r.encoding = 'gbk'

print('=' * 72)
print('竞价阶段题材验证链 — 2026-03-27')
print('数据说明：今开=竞价结束定价，竞价涨幅=今开vs昨收，反映9:25时的状态')
print('=' * 72)

current_group = ''
rows = []
for line in r.text.strip().split('\n'):
    if not line.strip():
        continue
    code = line.split('hq_str_')[1].split('=')[0]
    data = line.split('"')[1].split(',')
    if len(data) < 10 or code not in stocks_map:
        continue
    name, role = stocks_map[code]
    yclose = float(data[2])
    topen  = float(data[1])
    now    = float(data[3])
    amount = float(data[9])  # 全天成交额，竞价成交额无法从此接口直接获取
    opct   = (topen - yclose) / yclose * 100 if yclose > 0 else 0
    npct   = (now - yclose) / yclose * 100 if yclose > 0 else 0
    rows.append((code, name, role, yclose, topen, opct, now, npct, amount))

# 按题材分组输出
groups_order = ['电力', '锂电', '算力', '华为']
for grp in groups_order:
    grp_rows = [r for r in rows if r[2].startswith(grp)]
    if not grp_rows:
        continue
    print()
    print(f'【{grp}题材】')
    print(f"{'角色':<12} {'股票':<10} {'昨收':>6} {'今开':>6} {'竞价涨幅':>9} {'现价涨幅':>9}  竞价判断")
    print('-' * 72)
    for code, name, role, yclose, topen, opct, now, npct, amount in grp_rows:
        # 竞价判断
        if opct >= 9.5:
            judge = '★封死涨停 → 买不上'
        elif opct >= 5.0:
            judge = '↑高开强势 → 可跟进'
        elif opct >= 2.0:
            judge = '↑适度高开 → 观察封单'
        elif opct >= 0:
            judge = '→ 平开 → 需看封单'
        elif opct >= -3.0:
            judge = '↓小幅低开 → 谨慎'
        else:
            judge = '▼大幅低开 → 题材弱信号'
        print(f'{role:<12} {name:<10} {yclose:>6.2f} {topen:>6.2f} {opct:>+8.1f}%  {npct:>+8.1f}%  {judge}')

print()
print('=' * 72)
print('竞价验证链判断规则：')
print('  电力题材健康：龙二华电能源竞价>+0% AND 龙三湖南发展竞价>-3%')
print('  锂电题材健康：龙一融捷股份竞价>+2% AND 龙二丽岛新材竞价>+0%')
print('  任一龙二/龙三竞价大幅低开(<-3%) → 题材分化，不追龙一')
print('=' * 72)
print()

# 给出今天竞价时段的实际判断
print('【今日竞价实际判断（9:25时点）】')
elec_rows = {r[0]: r for r in rows if r[2].startswith('电力')}
lith_rows = {r[0]: r for r in rows if r[2].startswith('锂电')}

# 电力
e720  = elec_rows.get('sz000720')
e726  = elec_rows.get('sh600726')
e722  = elec_rows.get('sz000722')
e163  = elec_rows.get('sh600163')

if e720 and e726 and e722 and e163:
    print()
    print('电力题材：')
    print(f'  龙一新能泰山  竞价{e720[5]:+.1f}% → {"★封死，买不上" if e720[5]>=9.5 else "可操作"}')
    print(f'  龙二华电能源  竞价{e726[5]:+.1f}% → {"✅跟涨" if e726[5]>=0 else "❌低开，题材分化信号"}')
    print(f'  龙三湖南发展  竞价{e722[5]:+.1f}% → {"✅跟涨" if e722[5]>=-3 else "❌大幅低开，题材弱"}')
    print(f'  龙四中闽能源  竞价{e163[5]:+.1f}% → {"✅跟涨" if e163[5]>=0 else "❌低开，不做"}')

    elec_ok = (e726[5] >= 0) and (e722[5] >= -3)
    print(f'  → 题材健康度：{"✅健康，可追龙一备选" if elec_ok else "❌分化，龙一封死不追，备选也不做"}')

# 锂电
l192 = lith_rows.get('sz002192')
l937 = lith_rows.get('sh603937')

if l192 and l937:
    print()
    print('锂电题材：')
    print(f'  龙一融捷股份  竞价{l192[5]:+.1f}% → {"★封死" if l192[5]>=9.5 else ("↑强势" if l192[5]>=2 else "→观察")}')
    print(f'  龙二丽岛新材  竞价{l937[5]:+.1f}% → {"✅跟涨" if l937[5]>=0 else "❌低开，锂电分化"}')
    lith_ok = (l192[5] >= 2.0) and (l937[5] >= 0)
    print(f'  → 题材健康度：{"✅健康，融捷可操作" if lith_ok else "❌分化，谨慎"}')
