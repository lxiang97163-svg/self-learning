"""
开盘八法 - 一次性拉取所有判断所需数据 (修复版)
修复内容：
1. 强制禁用系统代理，避免 ProxyError
2. 增加 HTTP 协议作为 HTTPS 失败后的回退
3. 优化 5 分钟 K 线拉取逻辑，增加重试
4. 东财主域名不可用时：实时/板块用 push2delay；K 线用新浪；仍失败时上证用腾讯行情
"""
import requests
import datetime
import os
import json
import re

# 强制清除系统代理环境变量
for env in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    if env in os.environ:
        del os.environ[env]

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/"
}
UT  = "b2884a393a59ad64002292a3e90d46a5"
EM_DELAY = "http://push2delay.eastmoney.com"
TODAY = datetime.date.today().strftime("%Y%m%d")
D15AGO = (datetime.date.today() - datetime.timedelta(days=20)).strftime("%Y%m%d")
D60AGO = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y%m%d")

KLINE_SOURCE = "东财push2his"  # 或 新浪5分钟 / 无
DAY_SOURCE = "东财push2his"
QUOTE_NOTE = ""

def get_json(url, params):
    # 强制不使用代理
    proxies = {"http": None, "https": None}
    try:
        # 尝试 HTTPS
        r = requests.get(url, params=params, headers=HDR, timeout=10, proxies=proxies)
        return r.json()
    except Exception as e:
        # 如果 HTTPS 失败且 url 以 https 开头，尝试换成 http
        if url.startswith("https://"):
            http_url = url.replace("https://", "http://")
            try:
                r = requests.get(http_url, params=params, headers=HDR, timeout=10, proxies=proxies)
                return r.json()
            except:
                pass
        print(f"Error fetching {url}: {e}")
        return None


def sina_json(url, params):
    proxies = {"http": None, "https": None}
    h = {
        "User-Agent": HDR["User-Agent"],
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        r = requests.get(url, params=params, headers=h, timeout=15, proxies=proxies)
        return r.json()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def sina_5min_to_em_klines():
    """新浪 5 分钟 K → 与东财 klines 同形（第 7 字段填成交量，用于同时段量比）。"""
    global KLINE_SOURCE
    raw = sina_json(
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
        {"symbol": "sh000001", "scale": 5, "ma": "no", "datalen": 400},
    )
    if not raw:
        return []
    out = []
    for x in raw:
        t = x.get("day", "").replace("  ", " ")
        op, cl, hi, lo = x.get("open"), x.get("close"), x.get("high"), x.get("low")
        vol = float(x.get("volume") or 0)
        # 时间,开,收,高,低,量,额占位(用成交量代替以便脚本内比值逻辑可用)
        line = f"{t},{op},{cl},{hi},{lo},{vol},{vol}"
        out.append(line)
    if out:
        KLINE_SOURCE = "新浪5分钟"
    return out


def sina_daily_to_day_data():
    """新浪日 K（scale=240）→ opening_pattern_data 中 day_data 结构。"""
    global DAY_SOURCE
    raw = sina_json(
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
        {"symbol": "sh000001", "scale": 240, "ma": "no", "datalen": 25},
    )
    if not raw:
        return []
    day_data = []
    prev_close = None
    for x in raw:
        d = (x.get("day") or "")[:10]
        if not d:
            continue
        op, cl, hi, lo = float(x["open"]), float(x["close"]), float(x["high"]), float(x["low"])
        vol = float(x.get("volume") or 0)
        if prev_close is not None and prev_close > 0:
            pct = f"{(cl - prev_close) / prev_close * 100:.2f}"
        else:
            pct = "--"
        prev_close = cl
        day_data.append(
            {"date": d, "open": op, "close": cl, "high": hi, "low": lo, "amt": vol, "pct": pct}
        )
    if day_data:
        DAY_SOURCE = "新浪日K(scale=240)"
    return day_data


def tencent_sh000001_quote():
    """腾讯 qt.gtimg.cn 上证指数：昨收、今开、现价、成交额（元）。"""
    proxies = {"http": None, "https": None}
    try:
        r = requests.get(
            "http://qt.gtimg.cn/q=sh000001",
            headers={"User-Agent": HDR["User-Agent"]},
            timeout=12,
            proxies=proxies,
        )
        s = r.content.decode("gbk", errors="replace")
        m = re.search(r'v_sh000001="([^"]*)"', s)
        if not m:
            return None
        p = m.group(1).split("~")
        price = float(p[3])
        prev = float(p[4])
        open_ = float(p[5])
        amt = 0.0
        tail = p[-1] if p else ""
        if "/" in tail:
            parts = tail.split("/")
            if len(parts) >= 3:
                try:
                    amt = float(parts[2])
                except ValueError:
                    pass
        return {"f2": price, "f3": round((price - prev) / prev * 100, 2), "f6": amt, "f12": "000001", "f14": "上证指数", "f17": open_, "f18": prev}
    except Exception as e:
        print(f"Tencent quote error: {e}")
        return None


def append_today_row_from_intraday(day_data, all_k5, tq):
    """新浪日K最后一根为昨收时，用当日5分钟+腾讯现价补今日一行（便于破/位阶）。"""
    if not day_data or not tq or not all_k5:
        return day_data
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    if day_data[-1]["date"] >= today_str:
        return day_data
    bars = []
    for k in all_k5:
        kt = k.split(",")[0]
        if kt.startswith(today_str):
            bars.append(k)
    if not bars:
        return day_data
    highs = [float(b.split(",")[3]) for b in bars]
    lows = [float(b.split(",")[4]) for b in bars]
    vols = [float(b.split(",")[5]) for b in bars]
    op = float(bars[0].split(",")[1])
    hi, lo = max(highs), min(lows)
    cl = float(tq["f2"])
    prev_close = float(tq["f18"])
    pct = f"{(cl - prev_close) / prev_close * 100:.2f}"
    day_data.append(
        {
            "date": today_str,
            "open": op,
            "close": cl,
            "high": hi,
            "low": lo,
            "amt": sum(vols),
            "pct": pct,
        }
    )
    return day_data


def sina_daily_long_all_day(n=120):
    """新浪日K（scale=240）→ 与 section6 all_day 同结构，用于东财日K失败时。"""
    raw = sina_json(
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
        {"symbol": "sh000001", "scale": 240, "ma": "no", "datalen": n},
    )
    if not raw:
        return []
    out = []
    for x in raw:
        d = (x.get("day") or "")[:10]
        if not d:
            continue
        op, cl, hi, lo = float(x["open"]), float(x["close"]), float(x["high"]), float(x["low"])
        vol = float(x.get("volume") or 0)
        out.append(
            {
                "date": d,
                "open": op,
                "close": cl,
                "high": hi,
                "low": lo,
                "amt": vol,
            }
        )
    return out


# ========== 1. 实时行情 ==========
data1 = get_json("http://push2.eastmoney.com/api/qt/ulist.np/get", {
    "secids": "1.000001,0.399001,0.399006",
    "fields": "f2,f3,f6,f12,f14,f17,f18",
    "fltt": 2, "invt": 2, "ut": UT,
})
if not data1 or not data1.get("data"):
    data1 = get_json(f"{EM_DELAY}/api/qt/ulist.np/get", {
        "secids": "1.000001,0.399001,0.399006",
        "fields": "f2,f3,f6,f12,f14,f17,f18",
        "fltt": 2, "invt": 2, "ut": UT,
    })
    if data1 and data1.get("data"):
        QUOTE_NOTE = "（东财主站不可用，已用 push2delay）"

raw1 = data1.get("data", {}).get("diff", []) if data1 else []
items = list(raw1.values()) if isinstance(raw1, dict) else raw1
nm = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}

if not items:
    tq = tencent_sh000001_quote()
    if tq:
        items = [tq]
        if not QUOTE_NOTE:
            QUOTE_NOTE = "（东财不可用，上证用腾讯 qt.gtimg.cn）"

print("=" * 60)
print("【1. 实时行情】" + (QUOTE_NOTE or ""))
print("=" * 60)
if not items:
    print("  (实时行情数据获取失败)")
else:
    for it in items:
        c = it.get("f12", "")
        n = nm.get(c, c)
        o = it.get("f17", "--")
        pre = it.get("f18", "--")
        gap = ((o - pre) / pre * 100) if isinstance(o, (int, float)) and isinstance(pre, (int, float)) and pre > 0 else 0
        amt = it.get("f6", 0)
        amt_s = f"{amt / 1e8:.0f}亿" if isinstance(amt, (int, float)) and amt > 0 else "--"
        print(f"  {n}: 现价={it.get('f2', '--')} 涨跌={it.get('f3', '--')}% "
              f"今开={o} 昨收={pre} 跳空={gap:+.2f}% 成交额={amt_s}")

# ========== 2. 今日前三根5分钟K线 ==========
# 尝试不指定 beg/end，直接取最近 20 根，然后过滤今日数据
data2 = get_json("http://push2his.eastmoney.com/api/qt/stock/kline/get", {
    "secid": "1.000001",
    "fields1": "f1,f2,f3,f4,f5,f6",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    "klt": 5, "fqt": 0, "lmt": 100, "ut": UT,
})
all_k5 = []
if data2 and "data" in data2 and data2["data"] and "klines" in data2["data"]:
    all_k5 = data2["data"]["klines"]
else:
    # 尝试备用接口
    data2_alt = get_json("http://push2his.eastmoney.com/api/qt/stock/kline/get", {
        "secid": "1.000001", "klt": 5, "fqt": 0, "lmt": 100,
        "fields2": "f51,f52,f53,f54,f55,f56,f57"
    })
    if data2_alt and "data" in data2_alt and data2_alt["data"] and "klines" in data2_alt["data"]:
        all_k5 = data2_alt["data"]["klines"]

if not all_k5:
    all_k5 = sina_5min_to_em_klines()

# 过滤出今日的数据 (兼容不同日期格式)
k5 = []
for k in all_k5:
    k_dt = k.split(",")[0]
    k_date = k_dt.replace("-", "").split(" ")[0]
    if k_date == TODAY:
        k5.append(k)

print()
print("=" * 60)
print(f"【2. 今日前三根5分钟K线（上证指数）- 采样日期: {TODAY}】 数据源: {KLINE_SOURCE}")
print("=" * 60)
closes = []
if not k5:
    print("  (今日5分钟K线数据尚未产生或获取失败)")
else:
    for i, k in enumerate(k5[:3]):
        p = k.split(",")
        # 字段: 时间,开,收,高,低,量,额,...
        t, op, cl, hi, lo, vol, amt = p[0], p[1], p[2], p[3], p[4], p[5], float(p[6])
        closes.append(float(cl))
        if KLINE_SOURCE == "新浪5分钟":
            print(f"  第{i+1}根 {t}: 开={op} 收={cl} 高={hi} 低={lo} 量={amt/1e8:.1f}亿(成交量)")
        else:
            print(f"  第{i+1}根 {t}: 开={op} 收={cl} 高={hi} 低={lo} 额={amt/1e8:.1f}亿")

    if len(closes) >= 3:
        if closes[0] < closes[1] < closes[2]:
            pat = ">>> 三高盘（帝王盘）：三根收盘逐级走高"
        elif closes[0] < closes[1] and closes[2] <= closes[1]:
            pat = ">>> 二高盘（辅臣盘）：前两根走高，第三根持平/略低"
        elif closes[0] > closes[1] > closes[2]:
            pat = ">>> 三低盘（冥王盘）：三根收盘逐级走低"
        elif closes[0] > closes[1] and closes[2] >= closes[1]:
            pat = ">>> 二低盘：前两根走低，第三根持平/略高"
        else:
            pat = ">>> 走法不明确，需结合全天判断"
        print(f"  {pat}")

# ========== 3. 近期日K线（量能+位阶） ==========
data3 = get_json("http://push2his.eastmoney.com/api/qt/stock/kline/get", {
    "secid": "1.000001",
    "fields1": "f1,f2,f3,f4,f5,f6",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    "klt": 101, "fqt": 0, "lmt": 20, "ut": UT,
})
dk = []
if data3 and "data" in data3 and data3["data"] and "klines" in data3["data"]:
    dk = data3["data"]["klines"]

day_data = []
if not dk:
    day_data = sina_daily_to_day_data()

print()
print("=" * 60)
print("【3. 近期日K线（量能对比 + 位阶判断）】" + f" 数据源: {DAY_SOURCE}")
print("=" * 60)
if not dk and day_data:
    for d in day_data:
        lab = "量(新浪成交量)" if DAY_SOURCE.startswith("新浪") else "额"
        print(
            f"  {d['date']} 开={d['open']} 收={d['close']} 高={d['high']} 低={d['low']} 涨跌={d['pct']}% "
            f"{lab}={d['amt']/1e8:.0f}亿"
        )
    dk = []
if not dk and not day_data:
    print("  (日K线数据获取失败)")
elif dk:
    for k in dk:
        p = k.split(",")
        d, op, cl, hi, lo, vol, amt, pct = p[0], p[1], p[2], p[3], p[4], p[5], float(p[6]), p[8]
        day_data.append({"date": d, "open": float(op), "close": float(cl),
                         "high": float(hi), "low": float(lo), "amt": amt, "pct": pct})
        print(f"  {d} 开={op} 收={cl} 高={hi} 低={lo} 涨跌={pct}% 额={amt/1e8:.0f}亿")

if day_data and DAY_SOURCE.startswith("新浪"):
    tq_merge = tencent_sh000001_quote()
    day_data = append_today_row_from_intraday(day_data, all_k5, tq_merge)

if len(day_data) >= 2:
    ya = day_data[-2]["amt"]
    ta = day_data[-1]["amt"]
    is_sina = DAY_SOURCE.startswith("新浪")
    unit = "成交量" if is_sina else "成交额"

    now = datetime.datetime.now()
    is_closed = now.hour > 15 or (now.hour == 15 and now.minute >= 1)

    if is_closed:
        ratio = ta / ya if ya > 0 else 0
        if ratio > 1.5:
            vl = "爆量"
        elif ratio > 1.1:
            vl = "增量"
        elif ratio > 0.9:
            vl = "平量"
        elif ratio > 0.6:
            vl = "缩量"
        else:
            vl = "量窒息"
        print(f"  >>> 量能（全天，{unit}）: 今日{ta/1e8:.0f}亿 vs 昨日{ya/1e8:.0f}亿 = {ratio:.2f}x → {vl}")
    else:
        def get_5min_klines(lmt=100):
            resp = get_json("http://push2his.eastmoney.com/api/qt/stock/kline/get", {
                "secid": "1.000001",
                "klt": 5, "fqt": 0, "lmt": lmt, "ut": UT,
                "fields2": "f51,f52,f53,f54,f55,f56,f57"
            })
            lines = []
            if resp:
                blob = resp.get("data")
                if blob:
                    lines = blob.get("klines") or []
            if not lines:
                lines = sina_5min_to_em_klines()
            return lines

        yest_date = datetime.date.today() - datetime.timedelta(days=1)
        if yest_date.weekday() >= 5:
            yest_date = yest_date - datetime.timedelta(days=yest_date.weekday() - 4)
        yest_str = yest_date.strftime("%Y-%m-%d")

        all_k = get_5min_klines(200)
        today_prefix = datetime.date.today().strftime("%Y-%m-%d")
        k_today = [k for k in all_k if k.split(",")[0].startswith(today_prefix)]
        k_yest = [k for k in all_k if k.split(",")[0].startswith(yest_str)]

        n = min(len(k_today), len(k_yest))
        if n > 0:
            def sum_amt_5min(klines, n):
                return sum(float(k.split(",")[6]) for k in klines[:n])

            amt_t = sum_amt_5min(k_today, n)
            amt_y = sum_amt_5min(k_yest, n)
            ratio = amt_t / amt_y if amt_y > 0 else 0

            if ratio > 1.5:
                vl = "爆量"
            elif ratio > 1.1:
                vl = "增量"
            elif ratio > 0.9:
                vl = "平量"
            elif ratio > 0.6:
                vl = "缩量"
            else:
                vl = "量窒息"

            src_note = "（新浪5分钟为成交量）" if KLINE_SOURCE == "新浪5分钟" else ""
            print(f"  >>> 量能（同时段前{n}根5分钟K线对比）{src_note}:")
            print(f"      今日累计: {amt_t/1e8:.0f}亿  昨日同期: {amt_y/1e8:.0f}亿  比值: {ratio:.2f}x → {vl}")

if len(day_data) >= 5:
    recent = day_data[-5:]
    hi5 = max(d["high"] for d in recent)
    lo5 = min(d["low"] for d in recent)
    cur = day_data[-1]["close"]
    pos = (cur - lo5) / (hi5 - lo5) * 100 if hi5 != lo5 else 50
    if pos > 80:
        pl = "高档（近5日高位区域）"
    elif pos < 20:
        pl = "低档（近5日低位区域）"
    else:
        pl = f"中波整理（近5日位置 {pos:.0f}%）"
    print(f"  >>> 位阶: 近5日高={hi5} 低={lo5} 当前={cur} → {pl}")

# ========== 4. 板块涨跌幅TOP10 ==========
def fetch_board(label, fs):
    print()
    print("=" * 60)
    print(f"【{label}】")
    print("=" * 60)
    params = {
        "fid": "f3", "po": 1, "pz": 10, "pn": 1,
        "np": 1, "fltt": 2, "invt": 2,
        "fs": fs, "fields": "f2,f3,f12,f14", "ut": UT,
    }
    resp = get_json("http://push2.eastmoney.com/api/qt/clist/get", params)
    if not resp or not resp.get("data"):
        resp = get_json(f"{EM_DELAY}/api/qt/clist/get", params)
    d = resp.get("data") if resp else None
    if d is None:
        print("  (数据获取失败)")
        return
    diff = d.get("diff", [])
    if isinstance(diff, dict):
        diff = list(diff.values())
    for i, bk in enumerate(diff[:10]):
        print(f"  {i+1}. {bk.get('f14', '--')}: {bk.get('f3', '--')}%")

fetch_board("4. 今日概念板块涨幅TOP10（比盘）", "m:90+t:3")
fetch_board("5. 今日行业板块涨幅TOP10（比盘）", "m:90+t:2")

# ========== 5. 破：压力位分析 ==========
data6 = get_json("http://push2his.eastmoney.com/api/qt/stock/kline/get", {
    "secid": "1.000001",
    "fields1": "f1,f2,f3,f4,f5,f6",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    "klt": 101, "fqt": 0, "lmt": 90, "ut": UT,
})
all_dk = []
if data6 and "data" in data6 and data6["data"] and "klines" in data6["data"]:
    all_dk = data6["data"]["klines"]
all_day = []
for k in all_dk:
    p = k.split(",")
    all_day.append({
        "date": p[0], "open": float(p[1]), "close": float(p[2]),
        "high": float(p[3]), "low": float(p[4]), "amt": float(p[6])
    })
if not all_day:
    all_day = sina_daily_long_all_day(120)
    tq6 = tencent_sh000001_quote()
    if all_day and tq6:
        all_day = append_today_row_from_intraday(all_day, all_k5, tq6)

print()
print("=" * 60)
print("【6. 破：压力位分析】")
print("=" * 60)

if len(all_day) >= 3:
    cur_close = all_day[-1]["close"]
    cur_high  = all_day[-1]["high"]

    peak_idx = None
    peak_high = 0
    for i in range(len(all_day) - 2, max(len(all_day) - 60, 0), -1):
        if all_day[i]["high"] > peak_high:
            subsequent_lows = [all_day[j]["low"] for j in range(i+1, len(all_day)-1)]
            if subsequent_lows and min(subsequent_lows) < all_day[i]["high"] * 0.97:
                peak_high = all_day[i]["high"]
                peak_idx = i

    if peak_idx is not None:
        decline_segment = all_day[peak_idx:]
        bottom_idx_rel = min(range(len(decline_segment)), key=lambda i: decline_segment[i]["low"])
        bottom_day = decline_segment[bottom_idx_rel]
        decline_days = decline_segment[:bottom_idx_rel + 1]

        print(f"  本轮下跌起点: {all_day[peak_idx]['date']} 高点={peak_high}")
        print(f"  本轮底部:     {bottom_day['date']} 低点={bottom_day['low']}")
        print(f"  下跌幅度:     {(bottom_day['low'] - peak_high) / peak_high * 100:.1f}%")
        print(f"  今日收盘/现价: {cur_close}（反弹 {(cur_close - bottom_day['low']) / bottom_day['low'] * 100:.1f}%）")
        print()

        decline_sorted = sorted(decline_days, key=lambda x: x["amt"], reverse=True)
        print("  压力区（下跌段成交量最大的K线，套牢盘最重）：")
        for i, d in enumerate(decline_sorted[:5]):
            lo_zone = min(d["open"], d["close"])
            hi_zone = max(d["open"], d["close"])
            reached = "[当前已进入]" if cur_close >= lo_zone else f"[距离 {lo_zone - cur_close:.1f}点]"
            print(f"  {i+1}. {d['date']} 区间={lo_zone:.2f}~{hi_zone:.2f} 额={d['amt']/1e8:.0f}亿 {reached}")

        print()
        if len(day_data) >= 2:
            yest = day_data[-2]
            tod  = day_data[-1]
            print(f"  昨日最高={yest['high']}  今日最高={tod['high']}")
            if tod["high"] > yest["high"]:
                print(f"  >>> 已破昨日最高 {yest['high']} [YES]")
            else:
                print(f"  >>> 未破昨日最高 {yest['high']} [NO]")

        print(f"  >>> 前波高点压力: {peak_high}（需破此位才算完全收复）")
        if cur_high >= peak_high:
            print(f"  >>> 已破前波高点 [YES]")
        else:
            print(f"  >>> 未破前波高点，距离 {peak_high - cur_high:.1f}点 [NO]")

print()
print("=" * 60)
print("以上为开盘八法判断所需全部数据，AI据此做最终定性。")
print("=" * 60)
