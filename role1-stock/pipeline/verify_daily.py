# -*- coding: utf-8 -*-
"""
次日验证脚本
用法：python verify_daily.py --date 20260313
      （验证"20260313当天"速查卡建议是否准确）

设计原则：
  本脚本只输出「事实数据」，不产出任何机械结论。
  所有经验提炼、阈值校准建议均由 AI 在 Step 2 读取本报告后完成。

输出内容：
  1. 市场背景数据（指数、涨停/跌停总数）
  2. 今日实际题材排行 TOP10（今日 vs 昨日涨停数变化）
  3. 速查卡个股实际表现（竞价数据 + 全天结果 + 所属题材涨停数变化 + 量比）
  4. 速查卡竞价条件触发情况（条件原文 vs 实际数据 → 是否触发）
  5. 汇总统计
"""

import argparse
import chinamindata.min as tss
import chinadata.ca_data as ts
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import re

from _paths import REVIEW_DIR

# ── 路径配置（结构化后的复盘产出目录 outputs/review/）──────────
OUT_DIR = REVIEW_DIR

pro     = ts.pro_api('y64bdbe41e69304578e024369ab0ccbae88')
pro_min = tss.pro_api()


# ══════════════════════════════════════════════════════════════
# 数据获取函数（纯事实，无结论）
# ══════════════════════════════════════════════════════════════

def _ensure_frame(value) -> pd.DataFrame:
    """API 偶发返回字符串时统一降级为空表，避免 .empty / iterrows 直接报错。"""
    if isinstance(value, pd.DataFrame):
        return value
    return pd.DataFrame()

def auction_signal_label(amount_bn: float, pct: float) -> str:
    """
    竞价强弱标签（仅作参考标签，不用于生成结论）。
    AI 应结合题材背景自行判断信号是否有效，而非依赖此标签。
    """
    if amount_bn >= 1.0 and pct >= 5.0:
        return 'STRONG'
    elif amount_bn < 0.1 or pct < 0:
        return 'WEAK'
    else:
        return 'MEDIUM'


def fetch_prev_trade_date(trade_date: str) -> str:
    """获取上一个交易日（YYYYMMDD）"""
    start = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=14)).strftime('%Y%m%d')
    try:
        df = pro.trade_cal(exchange='SSE', start_date=start, end_date=trade_date, is_open='1')
        if isinstance(df, pd.DataFrame) and not df.empty:
            dates = sorted(df['cal_date'].astype(str).str.zfill(8).tolist())
            if trade_date in dates:
                idx = dates.index(trade_date)
                if idx > 0:
                    return dates[idx - 1]
            return dates[-2] if len(dates) >= 2 else trade_date
    except Exception:
        pass

    try:
        import akshare as ak
        cal = ak.tool_trade_date_hist_sina()
        dates = pd.to_datetime(cal['trade_date']).dt.strftime('%Y%m%d').tolist()
        prev_dates = [d for d in dates if d < trade_date]
        if prev_dates:
            return prev_dates[-1]
    except Exception:
        pass

    fallback = datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=1)
    while fallback.weekday() >= 5:
        fallback -= timedelta(days=1)
    return fallback.strftime('%Y%m%d')


def fetch_auction(trade_date: str) -> dict:
    """返回 {ts_code: {amount_bn, price, pct, vol_ratio}}"""
    try:
        auc = _ensure_frame(pro_min.stk_auction(trade_date=trade_date))
    except Exception:
        return {}
    result = {}
    if auc is None or auc.empty:
        return result
    for _, r in auc.iterrows():
        pre   = float(r.get('pre_close') or 0)
        price = float(r.get('price') or 0)
        pct   = (price - pre) / pre * 100 if pre > 0 else 0
        result[r['ts_code']] = {
            'amount_bn': float(r.get('amount') or 0) / 1e8,
            'price':     price,
            'pct':       pct,
            'vol_ratio': float(r.get('volume_ratio') or 0),
        }
    return result


def build_auc_rank(auc_map: dict) -> dict:
    """返回 {ts_code: 排名}，按 amount_bn 降序，第1名=1"""
    items = [(c, d.get('amount_bn', 0)) for c, d in auc_map.items()]
    items.sort(key=lambda x: -x[1])
    return {c: r for r, (c, _) in enumerate(items, 1)}


def fetch_daily(trade_date: str, codes: list) -> dict:
    """返回 {ts_code: {open, close, pct, high, low}}"""
    result = {}
    for code in codes:
        try:
            df = _ensure_frame(pro.daily(ts_code=code, trade_date=trade_date))
            if not df.empty:
                r = df.iloc[0]
                result[code] = {
                    'open':  float(r['open']),
                    'close': float(r['close']),
                    'pct':   float(r['pct_chg']),
                    'high':  float(r['high']),
                    'low':   float(r['low']),
                }
        except Exception:
            pass
    return result


def _code_to_ts_em(code: str) -> str:
    """东财 6 位代码 → ts_code（与 generate_review_from_tushare._code_to_ts 一致）"""
    c = str(code).strip().zfill(6)
    if c.startswith(("60", "68", "90")):
        return c + ".SH"
    if c.startswith(("00", "30", "20")):
        return c + ".SZ"
    if c.startswith(("43", "83", "87", "92")):
        return c + ".BJ"
    return c + ".SZ"


def _fetch_limit_akshare(trade_date: str) -> tuple:
    """
    Tushare limit_list_d 当日常延迟或为空时，用 AKShare 东财涨停/跌停池对齐复盘表口径。
    见 generate_review_from_tushare._load_limit 回退逻辑。
    """
    zt, dt = set(), set()
    try:
        import akshare as ak
        df_u = _ensure_frame(ak.stock_zt_pool_em(date=trade_date))
        if not df_u.empty and "代码" in df_u.columns:
            zt = set(df_u["代码"].astype(str).map(_code_to_ts_em))
    except Exception:
        pass
    try:
        import akshare as ak
        df_d = _ensure_frame(ak.stock_zt_pool_dtgc_em(date=trade_date))
        if not df_d.empty and "代码" in df_d.columns:
            dt = set(df_d["代码"].astype(str).map(_code_to_ts_em))
    except Exception:
        pass
    return zt, dt


def fetch_limit(trade_date: str) -> tuple:
    """返回 (涨停代码集合, 跌停代码集合)"""
    zt, dt = set(), set()
    try:
        df_zt = _ensure_frame(pro.limit_list_d(trade_date=trade_date, limit_type='U'))
        df_dt = _ensure_frame(pro.limit_list_d(trade_date=trade_date, limit_type='D'))
        if not df_zt.empty:
            zt = set(df_zt["ts_code"].tolist())
        if not df_dt.empty:
            dt = set(df_dt["ts_code"].tolist())
    except Exception:
        pass
    if not zt or not dt:
        zt_ak, dt_ak = _fetch_limit_akshare(trade_date)
        if not zt:
            zt = zt_ak
        if not dt:
            dt = dt_ak
    return zt, dt


def fetch_theme_zt_from_cpt(trade_date: str) -> dict:
    """
    kpl_list 为空时，用 limit_cpt_list 概念涨停数填充「题材排行」（口径为概念维度，作仪表盘参考）。
    """
    try:
        df = _ensure_frame(pro.limit_cpt_list(trade_date=trade_date))
        if df.empty:
            return {}
        cnt_col = "count" if "count" in df.columns else ("up_nums" if "up_nums" in df.columns else None)
        if cnt_col is None:
            return {}
        out = {}
        for _, r in df.iterrows():
            name = str(r.get("name", "") or "").strip()
            if not name or "ST" in name.upper():
                continue
            v = int(pd.to_numeric(r.get(cnt_col, 0), errors="coerce") or 0)
            if v > 0:
                out[name] = v
        return out
    except Exception:
        return {}


def fetch_index_daily(trade_date: str) -> dict:
    """返回上证指数当日行情 {pct_chg, close}"""
    try:
        df = _ensure_frame(pro.index_daily(ts_code='000001.SH', trade_date=trade_date))
        if not df.empty:
            r = df.iloc[0]
            return {'pct': float(r['pct_chg']), 'close': float(r['close'])}
    except Exception:
        pass
    return {'pct': 0.0, 'close': 0.0}


def fetch_all_daily_top(trade_date: str) -> list:
    """
    返回当日全市场涨幅 TOP10 个股列表。
    每项：{ts_code, name, pct_chg, is_zt}
    """
    try:
        df = _ensure_frame(pro.daily(trade_date=trade_date, fields='ts_code,pct_chg,close,open'))
        if df.empty:
            return []
        df = df.sort_values('pct_chg', ascending=False).head(10)
        result = []
        for _, r in df.iterrows():
            result.append({
                'ts_code': r['ts_code'],
                'pct_chg': float(r['pct_chg']),
            })
        return result
    except Exception:
        return []


def fetch_theme_zt(trade_date: str) -> dict:
    """
    返回 {题材: 涨停数} 映射（基于 kpl_list limit_up）。
    同一只股票可能属于多个题材，每个题材都计数。
    """
    try:
        df = _ensure_frame(pro.kpl_list(trade_date=trade_date, list_type='limit_up'))
    except Exception:
        return {}
    cnt = {}
    if df.empty or 'theme' not in df.columns:
        return cnt
    for _, r in df.iterrows():
        theme_str = str(r.get('theme', '') or '')
        for t in re.split(r'[/+|,，/、;；/s]+', theme_str):
            t = t.strip()
            if t:
                cnt[t] = cnt.get(t, 0) + 1
    return cnt


def fetch_stock_primary_theme(trade_date: str) -> dict:
    """
    返回 {ts_code: 主要题材} 映射（取 kpl_list 中 theme 字段的第一个值）。
    包含当日涨停股，不含未涨停股。
    """
    try:
        df = _ensure_frame(pro.kpl_list(trade_date=trade_date, list_type='limit_up'))
    except Exception:
        return {}
    result = {}
    if df.empty or 'theme' not in df.columns:
        return result
    for _, r in df.iterrows():
        theme_str = str(r.get('theme', '') or '')
        themes = [t.strip() for t in re.split(r'[/+|,，/、;；/s]+', theme_str) if t.strip()]
        if themes:
            result[r['ts_code']] = themes[0]
    return result


def get_name_map() -> dict:
    """返回 {ts_code: 股票名称}"""
    try:
        df = _ensure_frame(pro.stock_basic(fields='ts_code,name'))
        return dict(zip(df['ts_code'], df['name'])) if not df.empty else {}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════
# 速查卡解析
# ══════════════════════════════════════════════════════════════

def parse_speedcard(date_str: str, name_to_code: dict) -> list:
    """
    解析 速查_YYYY-MM-DD.md 中的股票信息。
    支持两种格式：
      1. 旧格式：「买入清单」表格（列：优先级|股票|板数|买入条件|仓位|否决）
      2. 新格式：「第一优先/第二优先/低吸候选」分区表格
         - 优先区：| 标的 | 板数 | 买入条件 | 否决 |
         - 低吸候选：| 标的 | 条件 |
    如果股票名称后无 (ts_code) 括号，则通过 name_to_code 反查代码。
    返回 list of dict: {name, code, role, weight, condition, stop_condition}
    """
    md_path = OUT_DIR / f"速查_{date_str}.md"
    if not md_path.exists():
        return []
    text = md_path.read_text(encoding='utf-8')

    stocks = []

    # ── 优先尝试旧格式「买入清单」 ──
    if '买入清单' in text:
        in_table = False
        for line in text.splitlines():
            if '买入清单' in line:
                in_table = True
                continue
            if not in_table:
                continue
            if not line.startswith('|'):
                if line.startswith('##'):
                    break
                continue
            if '---' in line or '优先级' in line or '股票' in line:
                continue

            cols = [c.strip() for c in line.strip('|').split('|')]
            if len(cols) < 5:
                continue

            name_raw = cols[1].strip('* ')
            code_m = re.search(r'(\d{6}\.[A-Z]{2})', cols[1])
            code   = code_m.group(1) if code_m else ''
            name = re.sub(r'\(\d{6}\.[A-Z]{2}\)', '', name_raw).strip('* ').strip()
            if not code and name:
                code = name_to_code.get(name, '')

            weight_m = re.findall(r'(\d+(?:\.\d+)?)[成%]', cols[4])
            weight = float(max(weight_m, key=float)) / 10 if weight_m else 0.0
            if weight > 1.0:
                weight /= 10

            condition = cols[3] if len(cols) > 3 else ''
            stop_cond = cols[5] if len(cols) > 5 else ''

            stocks.append({
                'name':      name,
                'code':      code,
                'role':      cols[0],
                'weight':    weight,
                'condition': condition,
                'stop_cond': stop_cond,
            })
        return stocks

    # ── 新格式：解析 第一优先 / 第二优先 / 低吸候选 ──
    PRIORITY_KEYWORDS = ('第一优先', '第二优先', '低吸候选')
    SKIP_KEYWORDS = ('不做', '❌', '如果则', '今日特别', '一句话执行', '风标三阶段')
    current_role = ''
    in_table = False
    is_dixie = False  # 低吸候选格式（只有2列）

    for line in text.splitlines():
        stripped = line.strip()

        # 检测到「不做」等区域则停止收集
        if stripped.startswith('#') and any(k in stripped for k in SKIP_KEYWORDS):
            current_role = ''
            in_table = False
            continue

        # 检测优先区标题
        if stripped.startswith('#') and any(k in stripped for k in PRIORITY_KEYWORDS):
            if '第一优先' in stripped:
                current_role = '第一优先'
                is_dixie = False
            elif '第二优先' in stripped:
                current_role = '第二优先'
                is_dixie = False
            elif '低吸候选' in stripped:
                current_role = '低吸候选'
                is_dixie = True
            in_table = True
            continue

        # 其他 ### 标题（新分区）→ 重置
        if stripped.startswith('#'):
            in_table = False
            current_role = ''
            continue

        if not in_table or not current_role:
            continue
        if not stripped.startswith('|'):
            continue
        if '---' in stripped:
            continue
        # 跳过表头行
        cols_raw = [c.strip() for c in stripped.strip('|').split('|')]
        if any(h in cols_raw[0] for h in ('标的', '股票', '优先')):
            continue

        # 提取股票名称和代码（第0列）
        col0 = cols_raw[0] if cols_raw else ''
        code_m = re.search(r'(\d{6}\.[A-Z]{2})', col0)
        code   = code_m.group(1) if code_m else ''
        name_raw = re.sub(r'\(\d{6}\.[A-Z]{2}\)', '', col0).strip('* ').strip()
        # 去掉中文括号备注（如"（海工装备·5板峰值）"）
        name = re.sub(r'（.*?）', '', name_raw).strip()
        if not code and name:
            code = name_to_code.get(name, '')

        if not name:
            continue

        if is_dixie:
            # 低吸候选：| 标的 | 条件 |
            condition = cols_raw[1] if len(cols_raw) > 1 else ''
            stop_cond = ''
            weight = 0.05  # 低吸候选默认0.5成仓位
        else:
            # 优先区：| 标的 | 板数 | 买入条件 | 否决 |
            condition = cols_raw[2] if len(cols_raw) > 2 else ''
            stop_cond = cols_raw[3] if len(cols_raw) > 3 else ''
            weight_m = re.findall(r'(\d+(?:\.\d+)?)[成%]', condition + stop_cond)
            weight = 0.1  # 默认1成

        stocks.append({
            'name':      name,
            'code':      code,
            'role':      current_role,
            'weight':    weight,
            'condition': condition,
            'stop_cond': stop_cond,
        })

    return stocks


def _normalize_condition_text(condition: str) -> str:
    """把速查文案中的常见写法归一，便于正则解析。"""
    text = condition or ''
    text = text.replace('**', '').replace('`', '')
    text = text.replace('昨×', '昨日×').replace('昨竞', '昨日竞价')
    text = text.replace('今日≥昨', '今日≥昨日').replace('今日>昨', '今日>昨日')
    text = text.replace('两市竞价成交前', '两市前').replace('两市竞价前', '两市前')
    text = text.replace('两市成交前', '两市前').replace('前排', '前10名')
    return text


def _extract_pct_threshold(condition: str) -> float:
    pct_m = re.search(r'涨幅[≥>=≧＞]+\s*([+\-]?\d+(?:\.\d+)?)%', condition)
    return float(pct_m.group(1)) if pct_m else 0.0


def check_condition_triggered(condition: str, auc_amt: float, auc_pct: float, auc_prev: float = 0.0, auc_rank: int = 0) -> str:
    """
    根据买入条件字符串和实际竞价数据，判断条件是否触发。
    支持格式：
      - 两市第一/前排：竞价成交额两市第一、两市前排
      - 竞价回流：今日≥昨日×Z、今日≥上次×Z（Z 如 0.3、1.2）
      - 绝对阈值（兜底）：竞价成交额≥X亿
    返回：'触发' / '未触发（具体原因）' / '条件不可解析'
    """
    normalized = _normalize_condition_text(condition)
    thr_pct = _extract_pct_threshold(normalized)
    checks = []

    # 两市第一/前N名
    liang_m = re.search(r'两市第一|两市前\s*(\d+)\s*名', normalized)
    if liang_m and auc_rank > 0:
        top_n = int(liang_m.group(1)) if liang_m.lastindex and liang_m.group(1) else 1
        met_rank = auc_rank <= top_n
        met_pct = (auc_pct >= thr_pct) if thr_pct > 0 else True
        if met_rank and met_pct:
            checks.append(('触发', ''))
        else:
            reasons = []
            if not met_rank:
                reasons.append(f'两市排名{auc_rank}名，未达前{top_n}')
            if thr_pct > 0 and not met_pct:
                reasons.append(f'涨幅{auc_pct:+.1f}%＜{thr_pct}%')
            checks.append(('未触发', '、'.join(reasons)))

    # 回流逻辑：今日≥昨日×系数（支持 昨/昨日/上次）
    hui_m = re.search(r'(?:今日)?\s*[≥>=≧＞]+\s*(?:昨日|上次)[×*]\s*(\d+(?:\.\d+)?)', normalized)
    hui_m2 = re.search(r'回流|今日\s*[≥>=≧＞]\s*(?:昨日|上次)', normalized)
    if hui_m or hui_m2:
        if auc_prev > 0:
            coef = float(hui_m.group(1)) if hui_m else 1.0
            thr_amt = auc_prev * coef
            met_amt = auc_amt >= thr_amt
            met_pct = (auc_pct >= thr_pct) if thr_pct > 0 else True
            if met_amt and met_pct:
                checks.append(('触发', ''))
            else:
                reasons = []
                if not met_amt:
                    reasons.append(f'今日{auc_amt:.2f}亿＜昨日×{coef}={thr_amt:.2f}亿')
                if thr_pct > 0 and not met_pct:
                    reasons.append(f'涨幅{auc_pct:+.1f}%＜{thr_pct}%')
                checks.append(('未触发', '、'.join(reasons)))
        else:
            checks.append(('未触发', '昨日竞价缺失，无法比较回流'))

    # 绝对成交额阈值
    amt_m = re.search(r'(?:竞价)?(?:成交额|封单)[≥>=≧＞]+\s*(\d+(?:\.\d+)?)亿', normalized)
    if amt_m:
        thr_amt = float(amt_m.group(1))
        met_amt = auc_amt >= thr_amt
        met_pct = (auc_pct >= thr_pct) if thr_pct > 0 else True
        if met_amt and met_pct:
            checks.append(('触发', ''))
        else:
            reasons = []
            if not met_amt:
                reasons.append(f'成交额{auc_amt:.2f}亿＜阈值{thr_amt}亿')
            if thr_pct > 0 and not met_pct:
                reasons.append(f'涨幅{auc_pct:+.1f}%＜{thr_pct}%')
            checks.append(('未触发', '、'.join(reasons)))

    if not checks:
        return '条件不可解析'
    if any(status == '触发' for status, _ in checks):
        return '触发'

    reasons = [reason for status, reason in checks if status == '未触发' and reason]
    return '未触发（' + '；'.join(reasons) + '）' if reasons else '未触发'


# ══════════════════════════════════════════════════════════════
# 主验证逻辑
# ══════════════════════════════════════════════════════════════

def run_verify(trade_date: str):
    """
    trade_date: YYYYMMDD，当天实盘日期。
    速查卡文件名：速查_YYYY-MM-DD.md（该卡由前一天复盘生成，当天使用）。
    """
    date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    print(f"=== 验证 {date_fmt} 速查卡 ===")

    # ── 获取名称→代码映射（用于补全速查卡中缺失代码）──
    print("拉取股票基础信息...")
    name_map     = get_name_map()
    name_to_code = {v: k for k, v in name_map.items()}

    # ── 读速查卡 ──
    stocks = parse_speedcard(date_fmt, name_to_code)
    if not stocks:
        print(f"[跳过] 未找到速查卡：{OUT_DIR / f'速查_{date_fmt}.md'}")
        return None
    codes = [s['code'] for s in stocks if s['code']]

    # ── 拉昨日交易日（用于竞价回流验证）──
    prev_date = fetch_prev_trade_date(trade_date)

    # ── 拉当日数据 ──
    print(f"拉取 {date_fmt} 竞价数据...")
    auc_map         = fetch_auction(trade_date)
    print(f"拉取昨日 {prev_date} 竞价数据（用于回流验证）...")
    auc_prev_map   = fetch_auction(prev_date)
    print(f"拉取 {date_fmt} 日线数据...")
    daily_map       = fetch_daily(trade_date, codes)
    zt_codes, dt_codes = fetch_limit(trade_date)

    # ── 拉市场背景数据 ──
    print("拉取市场背景数据...")
    idx_data        = fetch_index_daily(trade_date)
    theme_zt_today  = fetch_theme_zt(trade_date)
    if not theme_zt_today:
        theme_zt_today = fetch_theme_zt_from_cpt(trade_date)
    theme_zt_prev   = fetch_theme_zt(prev_date)
    if not theme_zt_prev:
        theme_zt_prev = fetch_theme_zt_from_cpt(prev_date)

    # ── 拉全市场赚钱效应数据 ──
    print("拉取全市场涨幅TOP10...")
    market_top10    = fetch_all_daily_top(trade_date)
    # 补充竞价TOP5的日线数据（竞价数据已有，只补日线）
    auc_top5_codes = [c for c, _ in sorted(auc_map.items(), key=lambda x: -x[1].get('amount_bn', 0))[:5]]
    extra_daily_codes = [c for c in auc_top5_codes if c not in daily_map]
    if extra_daily_codes:
        daily_map.update(fetch_daily(trade_date, extra_daily_codes))
    # 补充涨幅TOP10的日线数据
    top10_codes = [item['ts_code'] for item in market_top10 if item['ts_code'] not in daily_map]
    if top10_codes:
        daily_map.update(fetch_daily(trade_date, top10_codes))

    # 股票→主要题材（今日 + 昨日，用于未涨停股的兜底查询）
    code_theme_today = fetch_stock_primary_theme(trade_date)
    code_theme_prev  = fetch_stock_primary_theme(prev_date)

    # 今日题材 TOP10
    top_themes = sorted(theme_zt_today.items(), key=lambda x: -x[1])[:10]

    # 两市竞价成交额排名（用于验证「两市第一/前排」）
    auc_rank = build_auc_rank(auc_map) if auc_map else {}

    # ── 逐股统计 ──
    total_capital = 1_000_000
    total_pnl     = 0.0
    rows          = []

    for s in stocks:
        code = s['code']
        if not code:
            rows.append({**s, 'no_code': True})
            continue

        a = auc_map.get(code, {})
        d = daily_map.get(code, {})

        auc_amt     = a.get('amount_bn', 0.0)
        auc_prev    = auc_prev_map.get(code, {}).get('amount_bn', 0.0)
        auc_pct     = a.get('pct',       0.0)
        vol_ratio   = a.get('vol_ratio',  0.0)
        sig_label   = auction_signal_label(auc_amt, auc_pct) if a else 'NO_DATA'

        pct   = d.get('pct',   0.0)
        close = d.get('close', 0.0)
        open_ = d.get('open',  0.0)

        is_zt = code in zt_codes
        is_dt = code in dt_codes

        result_flag = (
            'WIN' if (is_zt or pct > 5) else 'LOSE' if (is_dt or pct < -3) else 'FLAT'
        )

        # 竞价条件触发情况（支持两市第一/回流）
        auc_rank_val = auc_rank.get(code, 0)
        cond_status = check_condition_triggered(s['condition'], auc_amt, auc_pct, auc_prev, auc_rank_val)

        # 该股主要题材（优先取今日涨停数据，兜底用昨日）
        primary_theme  = code_theme_today.get(code) or code_theme_prev.get(code) or '—'
        theme_zt_t     = theme_zt_today.get(primary_theme, 0) if primary_theme != '—' else 0
        theme_zt_p     = theme_zt_prev.get(primary_theme,  0) if primary_theme != '—' else 0

        # 理论盈亏（以开盘价买入，收盘价卖出，按速查卡仓位比例）
        if open_ > 0 and s['weight'] > 0:
            capital = total_capital * s['weight']
            pnl     = capital / open_ * (close - open_)
        else:
            pnl = 0.0
        total_pnl += pnl

        rows.append({
            'name':          s['name'],
            'code':          code,
            'role':          s['role'],
            'weight':        s['weight'],
            'condition':     s['condition'],
            'cond_status':   cond_status,
            'auc_amt':       auc_amt,
            'auc_prev':      auc_prev,
            'auc_rank':      auc_rank_val,
            'auc_pct':       auc_pct,
            'vol_ratio':     vol_ratio,
            'sig_label':     sig_label,
            'day_pct':       pct,
            'open':          open_,
            'close':         close,
            'is_zt':         is_zt,
            'is_dt':         is_dt,
            'result':        result_flag,
            'primary_theme': primary_theme,
            'theme_zt_t':    theme_zt_t,
            'theme_zt_p':    theme_zt_p,
            'pnl':           pnl,
            'no_code':       False,
        })

    # ══════════════════════════════════════════════════════════
    # 构建报告
    # ══════════════════════════════════════════════════════════
    lines = []
    lines.append(f"# 速查卡验证报告 {date_fmt}")
    lines.append("")
    lines.append("> **设计说明**：本报告为纯事实数据，不含机械结论。")
    lines.append("> AI 读取本报告后，须结合当日复盘表数据，自行分析经验并追加到 `outputs/knowledge/经验库.md`。")
    lines.append("")

    # ── 市场背景数据 ──
    lines.append("## 市场背景数据（今日）")
    lines.append("")
    lines.append("| 项目 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 上证指数收盘 | {idx_data['close']:.2f} |")
    lines.append(f"| 上证指数涨跌 | {idx_data['pct']:+.2f}% |")
    lines.append(f"| 今日涨停总数 | {len(zt_codes)}只 |")
    lines.append(f"| 今日跌停总数 | {len(dt_codes)}只 |")
    lines.append(f"| 昨日（{prev_date}）涨停总数 | {len([v for v in theme_zt_prev.values()])}（按题材统计，含重复）|")
    lines.append("")

    # ── 今日题材 TOP10 ──
    lines.append("## 今日实际题材排行（TOP10）")
    lines.append("")
    lines.append("| 顺位 | 题材 | 今日涨停数 | 昨日涨停数 | 变化 |")
    lines.append("|:---:|---|:---:|:---:|:---:|")
    for i, (th, cnt) in enumerate(top_themes, 1):
        prev_cnt  = theme_zt_prev.get(th, 0)
        delta     = cnt - prev_cnt
        delta_str = f"+{delta}" if delta > 0 else str(delta)
        lines.append(f"| {i} | {th} | {cnt} | {prev_cnt} | {delta_str} |")
    lines.append("")

    # ── 速查卡个股实际表现 ──
    lines.append("## 速查卡个股实际表现")
    lines.append("")
    lines.append("| 股票 | 角色 | 仓位 | 今日竞价 | 昨日竞价 | 竞价涨幅 | 量比 | 信号标签 | 全天涨幅 | 结果 | 主题材 | 题材今/昨涨停 | 竞价条件触发? | 理论盈亏 |")
    lines.append("|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|:---:|---|:---:|")
    for r in rows:
        if r.get('no_code'):
            lines.append(f"| {r['name']} | {r['role']} | — | — | — | — | — | NO_CODE | — | — | — | — | — | — |")
            continue
        day_str  = '[涨停]' if r['is_zt'] else ('[跌停]' if r['is_dt'] else f"{r['day_pct']:+.2f}%")
        pnl_str  = f"+{r['pnl']:,.0f}" if r['pnl'] >= 0 else f"{r['pnl']:,.0f}"
        th_str   = f"{r['theme_zt_t']}/{r['theme_zt_p']}" if r['primary_theme'] != '—' else '—/—'
        auc_prev_str = f"{r['auc_prev']:.2f}亿" if r.get('auc_prev', 0) > 0 else "—"
        lines.append(
            f"| **{r['name']}**({r['code']}) | {r['role']} | {r['weight']*100:.0f}%"
            f" | {r['auc_amt']:.2f}亿 | {auc_prev_str} | {r['auc_pct']:+.1f}% | {r['vol_ratio']:.1f}"
            f" | {r['sig_label']} | {day_str} | {r['result']}"
            f" | {r['primary_theme']} | {th_str} | {r['cond_status']} | {pnl_str}元 |"
        )
    lines.append("")

    # ── 竞价条件原文对照 ──
    lines.append("## 速查卡竞价条件原文 vs 实际")
    lines.append("")
    lines.append("| 股票 | 速查卡买入条件（原文） | 今日竞价 | 昨日竞价 | 竞价涨幅 | 条件是否触发 |")
    lines.append("|---|---|:---:|:---:|:---:|---|")
    for r in rows:
        if r.get('no_code'):
            continue
        auc_prev_str = f"{r['auc_prev']:.2f}亿" if r.get('auc_prev', 0) > 0 else "—"
        lines.append(
            f"| {r['name']} | {r['condition']}"
            f" | {r['auc_amt']:.2f}亿 | {auc_prev_str} | {r['auc_pct']:+.1f}%"
            f" | {r['cond_status']} |"
        )
    lines.append("")

    # ── 当日赚钱效应还原 ──
    # 速查卡覆盖的代码集合
    sc_codes = set(s['code'] for s in stocks if s.get('code'))
    # 速查卡题材顺位（从执行手册第三步题材顺位推断，此处用速查卡个股的主题材近似）
    sc_themes_ordered = []
    seen_sc_themes = set()
    for s in stocks:
        code = s.get('code', '')
        th = code_theme_today.get(code) or code_theme_prev.get(code) or ''
        if th and th not in seen_sc_themes:
            sc_themes_ordered.append(th)
            seen_sc_themes.add(th)

    lines.append("## 当日赚钱效应还原（进攻性复盘核心）")
    lines.append("")
    lines.append("> **用途**：找出今天市场真正赚钱的地方，对照速查卡覆盖情况，分析「为什么没去」。")
    lines.append("> AI 在 Step 2 读取本节时，必须逐项分析「错过原因」并写入速查卡「今日特别提示」。")
    lines.append("")

    # 子节1：全市场涨幅 TOP10
    lines.append("### 全市场涨幅 TOP10（今日最赚钱的票）")
    lines.append("")
    lines.append("| 顺位 | 股票代码 | 涨幅 | 速查卡覆盖 |")
    lines.append("|:---:|---|:---:|:---:|")
    for i, item in enumerate(market_top10, 1):
        code = item['ts_code']
        name = name_map.get(code, code)
        pct  = item['pct_chg']
        covered = '✅ 有' if code in sc_codes else '❌ 无'
        lines.append(f"| {i} | **{name}**({code}) | {pct:+.2f}% | {covered} |")
    if not market_top10:
        lines.append("| — | 数据获取失败 | — | — |")
    lines.append("")

    # 子节2：今日题材涨停数 TOP5 vs 速查卡顺位
    lines.append("### 今日题材涨停数 TOP5 vs 速查卡顺位")
    lines.append("")
    lines.append("| 实际顺位 | 题材 | 今日涨停数 | 速查卡顺位 |")
    lines.append("|:---:|---|:---:|:---:|")
    top5_themes = sorted(theme_zt_today.items(), key=lambda x: -x[1])[:5]
    for i, (th, cnt) in enumerate(top5_themes, 1):
        if th in sc_themes_ordered:
            sc_rank = f"第{sc_themes_ordered.index(th)+1}位"
        else:
            sc_rank = "❌ 未列入"
        lines.append(f"| {i} | {th} | {cnt} | {sc_rank} |")
    lines.append("")

    # 子节3：今日竞价成交额 TOP5 vs 速查卡
    lines.append("### 今日竞价成交额 TOP5（竞价最活跃的票）")
    lines.append("")
    lines.append("| 顺位 | 股票 | 竞价成交额 | 竞价涨幅 | 全天结果 | 速查卡覆盖 |")
    lines.append("|:---:|---|:---:|:---:|:---:|:---:|")
    auc_top5 = sorted(auc_map.items(), key=lambda x: -x[1].get('amount_bn', 0))[:5]
    for i, (code, adata) in enumerate(auc_top5, 1):
        name    = name_map.get(code, code)
        amt     = adata.get('amount_bn', 0)
        pct_a   = adata.get('pct', 0)
        # 全天结果
        is_zt_c = code in zt_codes
        is_dt_c = code in dt_codes
        d_info  = daily_map.get(code, {})
        d_pct   = d_info.get('pct', 0)
        if is_zt_c:
            day_res = '涨停'
        elif is_dt_c:
            day_res = '跌停'
        else:
            day_res = f'{d_pct:+.2f}%'
        covered = '✅ 有' if code in sc_codes else '❌ 无'
        lines.append(f"| {i} | **{name}**({code}) | {amt:.2f}亿 | {pct_a:+.1f}% | {day_res} | {covered} |")
    if not auc_top5:
        lines.append("| — | 数据获取失败 | — | — | — | — |")
    lines.append("")

    # 子节4：AI 分析提示（错过原因分类框架）
    lines.append("### 错过原因分类（AI 在 Step 2 必须逐项填写）")
    lines.append("")
    lines.append("对上方「速查卡覆盖=❌无」的每只票/每个题材，AI 必须判断属于以下哪类原因：")
    lines.append("")
    lines.append("| 错过原因类型 | 含义 | 下次如何修正 |")
    lines.append("|---|---|---|")
    lines.append("| 候选池问题 | 昨天数据里就有这只票，但我没选进速查卡 | 下次把该类票纳入候选池 |")
    lines.append("| 阈值问题 | 选进去了但买入条件太严，竞价时触发不了 | 下调涨幅/成交额阈值（经验库校准） |")
    lines.append("| 题材判断问题 | 题材排顺位排错了，没排到第一优先 | 调整题材排序逻辑，写入经验库题材样本 |")
    lines.append("| 数据盲区 | 昨天的数据根本看不到这个机会 | 写入经验库「数据缺口记录」，触发py脚本修改 |")
    lines.append("")
    lines.append("> **速查卡落地规则**：分析完成后，把最重要的1条错过原因及修正操作，写入次日速查卡「今日特别提示」。")
    lines.append("")

    # ── 汇总统计 ──
    valid_rows  = [r for r in rows if not r.get('no_code')]
    win_count   = sum(1 for r in valid_rows if r['result'] == 'WIN')
    lose_count  = sum(1 for r in valid_rows if r['result'] == 'LOSE')
    flat_count  = sum(1 for r in valid_rows if r['result'] == 'FLAT')
    triggered   = sum(1 for r in valid_rows if r['cond_status'] == '触发')
    total_count = len(valid_rows)

    lines.append("## 汇总统计")
    lines.append("")
    lines.append("| 项目 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 速查卡股票总数 | {total_count}只 |")
    lines.append(f"| 竞价条件实际触发数 | {triggered}只 |")
    lines.append(f"| 结果 WIN（涨停或涨幅>5%） | {win_count}只 |")
    lines.append(f"| 结果 LOSE（跌停或涨幅<-3%） | {lose_count}只 |")
    lines.append(f"| 结果 FLAT（其余） | {flat_count}只 |")
    if total_count > 0:
        lines.append(f"| 命中率（WIN/总数） | {win_count/total_count*100:.0f}% |")
    lines.append(f"| 理论总盈亏（100万本金） | {'+' if total_pnl>=0 else ''}{total_pnl:,.0f}元 |")
    lines.append(f"| 理论收益率 | {total_pnl/1_000_000*100:+.2f}% |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## AI 分析提示（Step 2 读取本报告时参考）")
    lines.append("")
    lines.append("以上均为事实数据。AI 在 Step 2 时，请结合当日复盘表，逐项分析：")
    lines.append("")
    lines.append("**失误类型区分（最重要）**：")
    lines.append("- 条件「触发」→ 结果 LOSE：")
    lines.append("  - 若该股主题材今/昨涨停数下跌 > 50% → **题材崩盘型失误**（阈值无需调整，题材判断失误）")
    lines.append("  - 若题材仍活跃 → **阈值偏低型失误**（建议上调买入阈值）")
    lines.append("  - 若有特殊公告/利空 → **个股特殊型失误**（不做规律归纳）")
    lines.append("- 条件「未触发」→ 结果 LOSE：**正确过滤**（条件设置合理）")
    lines.append("- 条件「未触发」→ 结果 WIN：**冷启动型**（低竞价但全天涨停，观察是否有规律）")
    lines.append("- 条件「触发」→ 结果 WIN：**正常命中**，记录实际竞价数值供下次参考")
    lines.append("")
    lines.append("**题材判断分析**：")
    lines.append("- 对比「今日实际题材排行 TOP10」与昨日速查卡的题材顺位预测，分析偏差原因")
    lines.append("- 是否有速查卡未覆盖的题材今日大幅爆发？（资金切换信号）")
    lines.append("")
    lines.append("**将以上分析结论结构化追加到** `outputs/knowledge/经验库.md` **对应表格中。**")

    # ── 写出文件 ──
    out_md = OUT_DIR / f"验证报告_{date_fmt}.md"
    out_md.write_text("\n".join(lines), encoding='utf-8')
    print(f"[OK] 验证报告已生成：{out_md}")
    return str(out_md)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.now().strftime('%Y%m%d'),
                        help='验证日期 YYYYMMDD，默认今天')
    args = parser.parse_args()
    run_verify(args.date)
