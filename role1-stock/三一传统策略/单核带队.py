# -*- coding: utf-8 -*-
"""
单核带队：竞价封单前五 → kpl 涨停原因 → 同花顺最相关概念 → 该概念下竞价金额/换手前三。
每次运行先使用 Selenium 获取渲染后的完整 HTML，提取 id="tblive" 的封单数据，再取前五名；失败则回退到本地 md。
依赖：chinadata、chinamindata、requests、selenium，需要安装 Chrome 浏览器和 chromedriver。
"""
import json
import os
import re
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import chinadata.ca_data as ts
import chinamindata.min as tss
import pandas as pd
from datetime import datetime, timedelta, date
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options

TOKEN = 'e95696cde1bc72c2839d1c9cc510ab2cf33'
TOKEN_MIN = 'ne34e6697159de73c228e34379b510ec554'
ts.set_token(TOKEN)
tss.set_token(TOKEN_MIN)
pro = ts.pro_api()
pro_min = tss.pro_api()

BASE_DIR = os.path.dirname(__file__)
JJLIVE_DIR = os.path.join(BASE_DIR, 'jjlive_data')
UNIFIED_OUT = os.path.join(BASE_DIR, 'unified_out')

# 方式二概念统计时剔除的板块（与 unified_auction_report 保持一致；若存在 unified_out/excluded_concepts.txt 则从其读取）
EXCLUDED_CONCEPTS_DEFAULT = [
    "沪深300样本股", "上证50样本股", "上证180成份股", "上证380成份股", "中证500成份股",
    "融资融券", "沪股通", "深股通", "同花顺漂亮100", "同花顺中特估100", "高股息精选",
    "同花顺出海50", "同花顺果指数", "同花顺新质50", "中国AI 50",
    "2024三季报预增", "2024年报预增", "2025一季报预增", "2025中报预增", "2025三季报预增", "2025年报预增",
    "证金持股", "PPP概念", "中字头股票", "超级品牌", "国家大基金持股", "国企改革",
    "回购增持再贷款概念", "雅下水电概念",
]


def _get_excluded_concepts():
    """读取需剔除的概念名集合：优先从 unified_out/excluded_concepts.txt 读取，否则用默认列表。"""
    path = os.path.join(UNIFIED_OUT, 'excluded_concepts.txt')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return set(line.strip() for line in f if line.strip())
        except Exception:
            pass
    return set(EXCLUDED_CONCEPTS_DEFAULT)

# 网页URL（使用Selenium获取渲染后的HTML）
PAGE_URL = "https://duanxianxia.com/web/jjlive"
FENGDAN_COOKIES = {
    "PHPSESSID": "oqp340djv17ei39crnfu9l776i",
    "server_name_session": "3127dbcd3e774542f4696d061650306f",
    "Hm_lvt_423edf2a3e642c55a0df7f5063f8f22c": "1770693637",
    "HMACCOUNT": "A3C50FDEDBB92985",
    "Hm_lpvt_423edf2a3e642c55a0df7f5063f8f22c": "1770695440",
}


def setup_driver():
    """设置 Chrome 驱动"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # 无头模式
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        print(f"创建 Chrome 驱动失败: {e}")
        print("提示：请确保已安装 Chrome 浏览器和 chromedriver")
        return None


def _code_to_ts_code(code_str):
    """6/5开头 -> .SH，0/3 开头 -> .SZ"""
    code_str = str(code_str).strip()
    if not code_str or len(code_str) < 6:
        return None
    if code_str.startswith(('6', '5')):
        return code_str + '.SH'
    return code_str + '.SZ'


def fetch_fengdan_html_with_selenium():
    """使用 Selenium 获取渲染后的完整 HTML（包含 id="tblive" 的数据）。"""
    driver = setup_driver()
    if not driver:
        return None
    
    try:
        driver.get(PAGE_URL)
        
        # 添加 cookies
        driver.add_cookie({
            'name': 'PHPSESSID',
            'value': FENGDAN_COOKIES['PHPSESSID']
        })
        driver.add_cookie({
            'name': 'server_name_session',
            'value': FENGDAN_COOKIES['server_name_session']
        })
        
        # 刷新页面使 cookies 生效
        driver.refresh()
        
        # 等待 id="tblive" 的元素出现，最多等待15秒
        try:
            wait = WebDriverWait(driver, 15)
            wait.until(
                lambda d: d.find_element(By.ID, "tblive").find_elements(By.TAG_NAME, "table")
            )
        except Exception:
            pass  # 即使超时也继续，可能数据已经加载了
        
        # 额外等待2秒确保数据完全加载
        time.sleep(2)
        
        # 获取完整 HTML
        html = driver.page_source
        return html
        
    except Exception as e:
        print(f"Selenium 获取页面失败: {e}")
        return None
    finally:
        driver.quit()


def parse_fengdan_table_html(html):
    """解析 getFengdanLast 返回的 table HTML，返回 [{'code': str, 'name': str}, ...]"""
    rows = []
    pat = re.compile(
        r"<td\s+code=['\"]?(\d+)['\"]?[^>]*><b>([^<]+)<i>(.*?)</i></b><br>(.*?)</td>",
        re.DOTALL,
    )
    for m in pat.finditer(html):
        code_raw = (m.group(1) or "").strip()
        name = (m.group(2) or "").strip()
        if code_raw and name:
            rows.append({"code": code_raw, "name": name})
    return rows


def _parse_fengdan_date_key(key):
    """
    把 API 返回的日期 key 转成 date 便于按真实日期取最新。
    支持 "2026-02-10"、"2026-2-10" 等，避免字符串排序导致 "2026-2-9" > "2026-2-10"。
    """
    s = str(key).strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    parts = s.replace("/", "-").split("-")
    if len(parts) == 3:
        try:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, TypeError):
            pass
    return None


def _latest_date_key_in_fengdan(data):
    """从 getFengdanLast 返回的 dict 中按真实日期取最新一天的 key。"""
    valid = [(k, _parse_fengdan_date_key(k)) for k in data.keys()]
    valid = [(k, d) for k, d in valid if d is not None]
    if not valid:
        return None
    return max(valid, key=lambda x: x[1])[0]


def _get_top5_from_table_html(table_html):
    """从 table HTML 解析前五名，返回 [(ts_code, name), ...] 或 None。"""
    if not table_html:
        return None
    rows = parse_fengdan_table_html(table_html)
    if len(rows) < 5:
        return None
    result = []
    for r in rows[:5]:
        ts_code = _code_to_ts_code(r["code"])
        if ts_code:
            result.append((ts_code, r["name"]))
    return result if len(result) >= 5 else None


def _extract_tblive_table_from_html(html):
    """
    从完整 HTML 中提取 id="tblive" 下的 table 内容（今天的数据）。
    """
    if not html or "tblive" not in html:
        return ""
    
    # 找到 <td id="tblive"> 的位置
    td_pattern = re.compile(r'<td\s+id=["\']tblive["\'][^>]*>', re.IGNORECASE)
    match = td_pattern.search(html)
    
    if not match:
        return ""
    
    # 从 td 标签结束位置开始查找 table
    start_pos = match.end()
    table_start = html.find('<table', start_pos)
    
    if table_start == -1:
        return ""
    
    # 匹配嵌套的 table 标签
    depth = 1
    pos = html.find('>', table_start) + 1
    
    while pos < len(html) and depth > 0:
        next_open = html.find('<table', pos)
        next_close = html.find('</table>', pos)
        
        if next_close == -1:
            break
        
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 6
        else:
            depth -= 1
            if depth == 0:
                table_end = next_close + 8
                return html[table_start:table_end]
            pos = next_close + 8
    
    return ""


def get_top5_from_tblive_html(html):
    """
    从 Selenium 获取的完整 HTML 中取「今天」的封单前五。
    网页中 <td id="tblive"> 内为今天。
    返回 [(ts_code, name), ...] 或 None。
    """
    if not html:
        return None
    table_html = _extract_tblive_table_from_html(html)
    if table_html:
        return _get_top5_from_table_html(table_html)
    return None


def get_top5_from_fengdan_api():
    """使用 Selenium 获取渲染后的 HTML，提取 id=tblive（今天）的数据；失败返回 None。"""
    html = fetch_fengdan_html_with_selenium()
    if not html:
        return None
    # 从 HTML 中提取 id=tblive 的数据（今天）
    top5 = get_top5_from_tblive_html(html)
    if top5:
        print("  封单数据使用: tblive（今天，Selenium获取）")
    return top5


def get_top5_for_date(fengdan_data, date_str):
    """
    从 getFengdanLast 返回的 JSON 中取指定日期的前五名。
    date_str: 如 '2026-02-10'（与 API 的 key 一致）。
    返回 [(ts_code, name), ...] 或 None。
    """
    if not fengdan_data or not isinstance(fengdan_data, dict):
        return None
    day = fengdan_data.get(date_str)
    if not day:
        return None
    table_html = day.get("table") or ""
    if not table_html:
        return None
    rows = parse_fengdan_table_html(table_html)
    if len(rows) < 5:
        return None
    result = []
    for r in rows[:5]:
        ts_code = _code_to_ts_code(r["code"])
        if ts_code:
            result.append((ts_code, r["name"]))
    return result if len(result) >= 5 else None


def get_yesterday_for(today_yyyymmdd):
    """
    给定 today_yyyymmdd（运行日），返回「前一交易日」yyyymmdd。
    若指数里最新一天就是 run date，取次新；否则（当天尚未录入）取指数最新一天，保证涨停原因等用前一交易日。
    """
    global pro, pro_min
    start = (datetime.strptime(today_yyyymmdd, '%Y%m%d') - timedelta(days=14)).strftime('%Y%m%d')
    try:
        df_idx = pro.index_daily(ts_code='000001.SH', start_date=start, end_date=today_yyyymmdd)
    except pd.errors.EmptyDataError:
        ts.set_token(TOKEN)
        tss.set_token(TOKEN_MIN)
        pro, pro_min = ts.pro_api(), tss.pro_api()
        df_idx = pro.index_daily(ts_code='000001.SH', start_date=start, end_date=today_yyyymmdd)
    if df_idx is None or df_idx.empty:
        return today_yyyymmdd
    dates = df_idx.sort_values('trade_date', ascending=False)['trade_date'].tolist()
    if len(dates) >= 2 and dates[0] == today_yyyymmdd:
        return dates[1]  # 运行日已录入 → 前一交易日
    return dates[0]  # 运行日未录入 → 当前指数最新日即为「前一交易日」


def parse_top5_from_md(md_path):
    """从竞价封单汇总 md 中解析「最新一个交易日」表格的前五名，返回 [(ts_code, name), ...]"""
    if not os.path.exists(md_path):
        return []
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    table_start = content.find('| 序号 | 代码 | 名称 |')
    if table_start == -1:
        return []
    table_content = content[table_start:]
    rows = []
    pat = re.compile(r'\|\s*\d+\s*\|\s*(\d+)\s*\|\s*([^|]+)\|')
    for m in pat.finditer(table_content):
        code = (m.group(1) or "").strip()
        name = (m.group(2) or "").strip()
        ts_code = _code_to_ts_code(code)
        if ts_code and name:
            rows.append((ts_code, name))
            if len(rows) >= 5:
                break
    return rows


def get_yesterday_and_today():
    """返回 (today, yesterday) 日期字符串"""
    today = datetime.now().strftime('%Y%m%d')
    df_idx = pro.index_daily(ts_code='000001.SH', start_date=(datetime.now() - timedelta(days=10)).strftime('%Y%m%d'), end_date=today)
    if df_idx is None or df_idx.empty:
        return today, today
    dates = df_idx.sort_values('trade_date', ascending=False)['trade_date'].tolist()
    yesterday = dates[1] if len(dates) >= 2 else dates[0]
    return today, yesterday


def get_kpl_lu_desc_for_codes(ts_codes, end_date, past_days=365):
    """获取这些股票在过去一年内 kpl 最近一次的涨停原因 lu_desc。返回 dict: ts_code -> lu_desc"""
    start_date = (datetime.strptime(end_date, '%Y%m%d') - timedelta(days=past_days)).strftime('%Y%m%d')
    result = {}
    for i in range(0, len(ts_codes), 50):
        batch = ts_codes[i:i+50]
        df = pro.kpl_list(ts_code=','.join(batch), start_date=start_date, end_date=end_date, list_type='limit_up')
        if df is None or df.empty:
            continue
        df = df.sort_values('trade_date', ascending=True)
        for code in batch:
            if code in result:
                continue
            sub = df[df['ts_code'] == code]
            if not sub.empty:
                result[code] = sub.iloc[-1].get('lu_desc', '') or '未知'
    for code in ts_codes:
        if code not in result:
            result[code] = '未知'
    return result


def _fetch_one_concept_members(row):
    """拉取单个概念的成分股，返回 (concept_ts, concept_name, con_codes)。"""
    concept_ts = row['ts_code']
    concept_name = row['name']
    try:
        df_m = pro.ths_member(ts_code=concept_ts, fields='con_code')
    except Exception:
        return None
    if df_m is None or df_m.empty:
        return None
    return (concept_ts, concept_name, df_m['con_code'].tolist())


def build_stock_to_concepts_map(only_for_codes=None, max_workers=12, use_cache=True):
    """同花顺概念：建立 股票 ts_code -> [(concept_ts_code, concept_name), ...]。若 only_for_codes 有值则只保留这些股票。
    使用线程池并行拉取 ths_member 加速；use_cache 为 True 时同一天内使用本地缓存，第二次起几乎秒出。"""
    cache_dir = JJLIVE_DIR
    today_str = datetime.now().strftime('%Y%m%d')
    cache_file = os.path.join(cache_dir, f'stock_concepts_map_{today_str}.json')
    only_set = set(only_for_codes) if only_for_codes else None

    excluded = _get_excluded_concepts()
    if use_cache and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('date') == today_str:
                full_map = {}
                for k, v in data.get('stock_concepts', {}).items():
                    filtered = [(t[0], t[1]) for t in v if t[1] not in excluded]
                    if filtered:
                        full_map[k] = filtered
                print("    同花顺概念成分使用本地缓存")
                if only_set:
                    return {k: full_map[k] for k in only_set if k in full_map}
                return full_map
        except Exception as e:
            print(f"    缓存读取失败: {e}，重新拉取")
    df_concepts = pro.ths_index(exchange='A', type='N')
    if df_concepts is None or df_concepts.empty:
        return {}
    if excluded:
        df_concepts = df_concepts[~df_concepts['name'].isin(excluded)]
    stock_concepts = {}
    n = len(df_concepts)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one_concept_members, row): i for i, row in df_concepts.iterrows()}
        for future in as_completed(futures):
            done += 1
            if done % 80 == 0:
                print(f"    已扫描 {done}/{n} 个概念...")
            res = future.result()
            if res is None:
                continue
            concept_ts, concept_name, con_codes = res
            for con in con_codes:
                if con not in stock_concepts:
                    stock_concepts[con] = []
                stock_concepts[con].append((concept_ts, concept_name))
    if use_cache:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            serial = {'date': today_str, 'stock_concepts': {k: [list(t) for t in v] for k, v in stock_concepts.items()}}
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(serial, f, ensure_ascii=False, indent=0)
            print("    已写入同花顺概念缓存")
        except Exception as e:
            print(f"    缓存写入失败: {e}")
    if only_set:
        return {k: stock_concepts[k] for k in only_set if k in stock_concepts}
    return stock_concepts


def pick_most_relevant_concept(stock_code, stock_concepts_map, lu_desc):
    """从该股票所属同花顺概念中，选一个与涨停原因最相关的（名称包含 lu_desc 或反之），否则取第一个；剔除 excluded_concepts。返回 (concept_ts_code, concept_name) 或 None"""
    concepts = stock_concepts_map.get(stock_code, [])
    if not concepts:
        return None
    excluded = _get_excluded_concepts()
    concepts = [(c_ts, c_name) for c_ts, c_name in concepts if c_name not in excluded]
    if not concepts:
        return None
    lu_desc = (lu_desc or '').strip()
    for c_ts, c_name in concepts:
        if lu_desc and c_name and (lu_desc in c_name or c_name in lu_desc):
            return (c_ts, c_name)
    return concepts[0]


def _is_30_prefix(ts_code):
    """是否创业板：ts_code 如 300750.SZ，以 30 开头"""
    return str(ts_code).strip().startswith('30')


def top_n_ensure_one_30(df_sorted, n=3, ts_code_col='ts_code'):
    """
    从已按某指标排序的 df 中取「至少前 n 名，且至少包含一只 30 开头」。
    若前 n 名里没有 30 开头，则顺延直到找到一只符合条件的再截断。
    返回 DataFrame（可能多于 n 行）。
    """
    if df_sorted is None or df_sorted.empty:
        return df_sorted
    rows = []
    has_30 = False
    for _, row in df_sorted.iterrows():
        rows.append(row)
        if _is_30_prefix(row.get(ts_code_col, '')):
            has_30 = True
        if len(rows) >= n and has_30:
            break
    if not rows:
        return df_sorted.iloc[0:0]
    return pd.DataFrame(rows)


def run_for_date(today_yyyymmdd, fengdan_date=None, output_file=None):
    """
    按指定日期跑单核带队：竞价封单前五（使用 Selenium 获取 id="tblive" 的今天数据）、涨停原因、概念下竞价金额/换手前三。
    today_yyyymmdd: 竞价数据日期，如 '20260210'
    fengdan_date: 封单日期（已废弃，保留兼容性），现在总是使用 Selenium 获取今天的 id="tblive" 数据
    output_file: 若指定则把完整内容写入该文件且不推送微信；为 None 则正常推送
    """
    yesterday = get_yesterday_for(today_yyyymmdd)
    today = today_yyyymmdd
    print(f"日期: 封单/竞价={today}  涨停原因/概念基准={yesterday}  封单使用 Selenium 获取 id=tblive（今天）\n")

    print("正在拉取竞价封单（使用 Selenium 获取 HTML）...")
    # 使用 Selenium 获取渲染后的 HTML，提取 id=tblive（今天）的数据
    top5 = get_top5_from_fengdan_api()
    if not top5:
        print("接口未返回有效数据，改用本地 竞价封单汇总_*.md")
        md_candidates = [f for f in os.listdir(JJLIVE_DIR) if f.startswith('竞价封单汇总_') and f.endswith('.md')]
        md_candidates.sort(reverse=True)
        md_path = os.path.join(JJLIVE_DIR, md_candidates[0]) if md_candidates else os.path.join(JJLIVE_DIR, '竞价封单汇总_2026-02-10.md')
        top5 = parse_top5_from_md(md_path)
    if not top5:
        print("未解析到竞价封单前五名，请检查接口 Cookie 或 jjlive_data/竞价封单汇总_*.md")
        return
    print("【竞价封单前五名】")
    for i, (tc, name) in enumerate(top5, 1):
        print(f"  {i}. {name}({tc})")
    print()

    ts_codes = [t[0] for t in top5]
    lu_desc_map = get_kpl_lu_desc_for_codes(ts_codes, yesterday)
    print("【涨停原因 kpl 近一年最近一次】")
    for tc, name in top5:
        print(f"  {name}({tc}): {lu_desc_map.get(tc, '未知')}")
    print()

    df_auc = pro_min.stk_auction(trade_date=today)
    if df_auc is None or df_auc.empty:
        print(f"无法获取 {today} 竞价数据")
        return
    df_auc['pct_chg'] = (df_auc['price'] - df_auc['pre_close']) / df_auc['pre_close'] * 100
    df_auc['amount_wan'] = df_auc['amount'] / 10000
    df_auc['turnover_rate'] = df_auc.get('turnover_rate', pd.Series(0.0, index=df_auc.index)).fillna(0)

    df_stocks = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
    stock_name_map = dict(zip(df_stocks['ts_code'], df_stocks['name']))

    # 方式一：涨停概念榜（limit_cpt_list）→ ths_member → 股票所属概念；未匹配到与涨停原因一致时，用该股全部同花顺概念选最相关
    print("正在匹配涨停概念榜概念（方式一，仅前五只）...")
    lead_to_concepts = {c: [] for c in ts_codes}  # lead_code -> [(concept_ts, concept_name), ...]
    concept_members_cache = {}  # concept_ts -> [con_code, ...]
    stock_concepts_map_fallback = None  # 懒加载：仅当需要「从该股全部概念选最相关」时再拉取
    df_cpt = pro.limit_cpt_list(trade_date=yesterday)
    if isinstance(df_cpt, pd.DataFrame) and not df_cpt.empty:
        df_cpt_sorted = df_cpt.sort_values('rank', ascending=True) if 'rank' in df_cpt.columns else df_cpt
        remaining = set(ts_codes)
        for _, row in df_cpt_sorted.iterrows():
            concept_ts = row.get('ts_code')
            concept_name = row.get('name')
            if not concept_ts or not concept_name:
                continue
            df_members = pro.ths_member(ts_code=concept_ts, fields='con_code')
            if df_members is None or df_members.empty:
                continue
            con_codes = df_members['con_code'].tolist()
            concept_members_cache[concept_ts] = con_codes
            hit = remaining.intersection(con_codes)
            if hit:
                for code in hit:
                    lead_to_concepts[code].append((concept_ts, concept_name))
                remaining -= hit
                if not remaining:
                    break

    print("\n" + "=" * 70)
    print("【单核带队】前五名 + 涨停原因 + 该概念下竞价金额前三、竞价换手前三")
    print("=" * 70)

    push_lines = [f"📊 单核带队 {today}\n", "=" * 70 + "\n"]
    push_lines.append("【竞价封单前五名】\n")
    for i, (tc, name) in enumerate(top5, 1):
        push_lines.append(f"  {i}. {name}({tc})\n")
    push_lines.append("\n")

    df_yesterday_zt = pro.limit_list_d(trade_date=yesterday, limit_type='U')
    yesterday_zt_set = set(df_yesterday_zt['ts_code']) if df_yesterday_zt is not None and not df_yesterday_zt.empty else set()

    for idx, (lead_code, lead_name) in enumerate(top5, 1):
        lu_desc = lu_desc_map.get(lead_code, '未知')
        concepts = lead_to_concepts.get(lead_code, [])
        concept = None
        if concepts:
            lu_desc_s = (lu_desc or '').strip()
            for c_ts, c_name in concepts:
                if lu_desc_s and c_name and (lu_desc_s in c_name or c_name in lu_desc_s):
                    concept = (c_ts, c_name)
                    break
            if concept is None:
                # 涨停概念榜里没有与涨停原因匹配的概念时，从该股全部同花顺概念中选最相关（如涨停原因「人工智能」→ 概念「人工智能」）
                if stock_concepts_map_fallback is None:
                    stock_concepts_map_fallback = build_stock_to_concepts_map(only_for_codes=ts_codes, use_cache=True)
                concept = pick_most_relevant_concept(lead_code, stock_concepts_map_fallback, lu_desc)
                if concept is None:
                    concept = concepts[0]  # 最终回退：涨停概念榜中更靠前的概念
        if not concept:
            msg = f"\n{idx}. {lead_name}({lead_code})  涨停原因: {lu_desc}\n   未匹配到涨停概念榜概念"
            print(msg)
            push_lines.append(msg + "\n")
            continue
        concept_ts, concept_name = concept
        member_codes = concept_members_cache.get(concept_ts)
        if member_codes is None:
            df_members = pro.ths_member(ts_code=concept_ts, fields='con_code')
            if df_members is None or df_members.empty:
                member_codes = []
            else:
                member_codes = df_members['con_code'].tolist()
                concept_members_cache[concept_ts] = member_codes
        if not member_codes:
            msg = f"\n{idx}. {lead_name}({lead_code})  涨停原因: {lu_desc}  概念: {concept_name}\n   概念无成分股"
            print(msg)
            push_lines.append(msg + "\n")
            continue
        df_sector = df_auc[df_auc['ts_code'].isin(member_codes)]
        if df_sector.empty:
            msg = f"\n{idx}. {lead_name}({lead_code})  涨停原因: {lu_desc}  概念: {concept_name}\n   概念下无今日竞价数据"
            print(msg)
            push_lines.append(msg + "\n")
            continue

        sector_open_pct = df_sector['pct_chg'].mean()
        sector_zt_count = sum(1 for c in member_codes if c in yesterday_zt_set)

        amt_sorted = df_sector.sort_values('amount_wan', ascending=False)
        hs_sorted = df_sector.sort_values('turnover_rate', ascending=False)
        amt_top3 = top_n_ensure_one_30(amt_sorted, n=3, ts_code_col='ts_code')
        hs_top3 = top_n_ensure_one_30(hs_sorted, n=3, ts_code_col='ts_code')

        block = [
            f"\n{idx}. {lead_name}({lead_code})",
            f"   涨停原因: {lu_desc}",
            f"   所属概念: {concept_name}",
            f"   板块今日高开: {sector_open_pct:+.2f}%  板块内涨停: {sector_zt_count}只",
            "   该概念下 竞价金额前三:",
        ]
        for i, (_, row) in enumerate(amt_top3.iterrows(), 1):
            line = f"      {i}) {stock_name_map.get(row['ts_code'], row['ts_code'])}({row['ts_code']}) 金额{int(row['amount_wan'])}万 竞价{row['pct_chg']:+.2f}%"
            block.append(line)
        block.append("   该概念下 竞价换手前三:")
        for i, (_, row) in enumerate(hs_top3.iterrows(), 1):
            line = f"      {i}) {stock_name_map.get(row['ts_code'], row['ts_code'])}({row['ts_code']}) 换手{row['turnover_rate']:.4f}% 竞价{row['pct_chg']:+.2f}%"
            block.append(line)
        text = "\n".join(block)
        print(text)
        push_lines.append(text + "\n")

    print("\n" + "=" * 70)
    push_lines.append("\n" + "=" * 70 + "\n")

    content = "".join(push_lines)
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ 已写入: {output_file}")
        return
    try:
        resp = requests.post("http://www.pushplus.plus/send", json={
            "token": "66c0490b50c34e74b5cc000232b1d23c",
            "title": f"单核带队 {today}",
            "content": content,
            "template": "txt",
            "channel": "wechat"
        }, timeout=10)
        if resp.status_code == 200 and resp.json().get("code") == 200:
            print("✅ 已推送到微信")
        else:
            print(f"⚠️ 推送结果: {resp.json() if resp.status_code == 200 else resp.status_code}")
    except Exception as e:
        print(f"⚠️ 推送失败: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-push', action='store_true', help='不推送，仅写文件')
    parser.add_argument('--output-file', type=str, default=None, help='输出文件路径')
    args = parser.parse_args()
    output_file = args.output_file  # 指定则写文件；no-push 时也写文件不推送
    today, _ = get_yesterday_and_today()
    fengdan_date = datetime.now().strftime('%Y-%m-%d')
    run_for_date(today, fengdan_date=fengdan_date, output_file=output_file)


if __name__ == '__main__':
    main()
