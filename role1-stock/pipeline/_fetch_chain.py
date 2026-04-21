# -*- coding: utf-8 -*-
import requests

session = requests.Session()
session.trust_env = False
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://finance.sina.com.cn'
}

# 电力题材：新能泰山、华电能源、湖南发展、中闽能源、晋控电力
# 锂电题材：融捷股份、丽岛新材
# 算力/华为：奥瑞德、通鼎互联、舒华体育
stocks = 'sz000720,sh600726,sz000722,sh600163,sz000767,sz002192,sh603937,sh600666,sz002491,sh605299'
url = 'https://hq.sinajs.cn/list=' + stocks
r = session.get(url, headers=headers, timeout=15)
r.encoding = 'gbk'

groups = {
    'sz000720': '电力', 'sh600726': '电力', 'sz000722': '电力',
    'sh600163': '电力', 'sz000767': '电力',
    'sz002192': '锂电', 'sh603937': '锂电',
    'sh600666': '算力/华为', 'sz002491': '算力/华为', 'sh605299': '算力/华为',
}

lines = r.text.strip().split('\n')
current_group = ''
for line in lines:
    if not line.strip():
        continue
    code = line.split('hq_str_')[1].split('=')[0]
    data = line.split('"')[1].split(',')
    if len(data) < 10:
        continue
    name    = data[0]
    yclose  = float(data[2])
    topen   = float(data[1])
    now     = float(data[3])
    high    = float(data[4])
    low     = float(data[5])
    amount  = float(data[9])
    pct     = (now - yclose) / yclose * 100 if yclose > 0 else 0
    opct    = (topen - yclose) / yclose * 100 if yclose > 0 else 0
    tstr    = data[31] if len(data) > 31 else ''

    grp = groups.get(code, '')
    if grp != current_group:
        current_group = grp
        print('\n【' + grp + '】')
        print('-' * 70)

    status = ''
    if pct >= 9.5:
        status = '★涨停'
    elif pct <= -9.5:
        status = '▼跌停'
    elif pct >= 5:
        status = '↑强'
    elif pct <= -3:
        status = '↓弱'

    print('%s(%s) 开%+.1f%% 现%+.1f%% 高%.2f 低%.2f 额%.1f亿 %s %s' % (
        name, code, opct, pct, high, low, amount/1e8, status, tstr))
