# -*- coding: utf-8 -*-
"""
回溯经验库脚本 backfill_experience.py
======================================
目的：从历史每日复盘表 md 文件中，解析出各日期的主线龙头股（2板以上），
      然后用 tushare API 拉取「次日」的竞价数据和全天结果，
      批量生成经验库「竞价阈值校准记录」中的命中/失误记录。

用法：
    python backfill_experience.py
    python backfill_experience.py --dry-run   # 只打印，不写入经验库

输出：
    1. 控制台打印每条记录
    2. 追加到 outputs/knowledge/经验库.md（竞价阈值校准记录表）

逻辑说明：
    - 复盘表日期 = 当日（如 2026-03-12）
    - 速查卡使用日期 = 次日（如 2026-03-13）
    - 因此拉取「次日」的竞价数据和全天结果，判断龙头股表现
    - 板数从复盘表3.4节读取
    - 失误类型判断：
        * 条件触发 + WIN → 命中
        * 条件触发 + LOSE + 题材今日涨停数下跌>50% → 题材崩盘型
        * 条件触发 + LOSE + 题材仍活跃 → 阈值偏低型
        * 条件未触发 + WIN → 冷启动型
        * 条件未触发 + LOSE → 正确过滤
    - 本脚本不判断「条件是否触发」（历史速查卡已删除），
      只记录「实际竞价数据 + 全天结果」，供 AI 在 Step 2 时做涨幅校准
"""

import argparse
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta

import chinamindata.min as tss
import chinadata.ca_data as ts

from _paths import KNOWLEDGE_DIR, REVIEW_DIR

# ── 路径配置：复盘表 outputs/review/，经验库 outputs/knowledge/ ───
EXP_LIB_PATH = KNOWLEDGE_DIR / "经验库.md"
TOKEN        = 'y64bdbe41e69304578e024369ab0ccbae88'

pro     = ts.pro_api(TOKEN)
pro_min = tss.pro_api()

# ── 已在经验库中存在的日期（避免重复写入）──────────────────────
# 从经验库中读取已有记录日期，跳过重复
def load_existing_dates(exp_path: Path) -> set:
    """
    从经验库「竞价阈值校准记录」表中读取已有的「记录日期」。
    只扫描竞价阈值校准记录表（## 竞价阈值校准记录 到下一个 ## 之间），
    避免把「市场情绪规律」「题材判断样本」等其他表的日期误判为已有记录。
    """
    if not exp_path.exists():
        return set()
    text = exp_path.read_text(encoding='utf-8')
    # 只截取「竞价阈值校准记录」表的内容
    section_match = re.search(
        r'## 竞价阈值校准记录(.*?)(?=/n## |/Z)',
        text, re.DOTALL
    )
    if not section_match:
        return set()
    section = section_match.group(1)
    # 匹配形如 | 20260313 | 的日期列
    dates = re.findall(r'/|/s*(/d{8})/s*/|', section)
    return set(dates)


# ── tushare 数据获取 ──────────────────────────────────────────

def get_next_trade_date(trade_date: str) -> str:
    """获取下一个交易日（YYYYMMDD）"""
    end = (datetime.strptime(trade_date, '%Y%m%d') + timedelta(days=14)).strftime('%Y%m%d')
    try:
        df = pro.trade_cal(exchange='SSE', start_date=trade_date, end_date=end, is_open='1')
        if df is None or df.empty:
            return str(int(trade_date) + 1)
        dates = sorted(df['cal_date'].tolist())
        if trade_date in dates:
            idx = dates.index(trade_date)
            if idx + 1 < len(dates):
                return dates[idx + 1]
        return dates[0]
    except Exception:
        return str(int(trade_date) + 1)


def fetch_auction(trade_date: str) -> dict:
    """返回 {ts_code: {amount_bn, pct, vol_ratio}}"""
    try:
        auc = pro_min.stk_auction(trade_date=trade_date)
    except Exception as e:
        print(f"  [警告] 竞价数据获取失败 {trade_date}: {e}")
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
            'pct':       pct,
            'vol_ratio': float(r.get('volume_ratio') or 0),
        }
    return result


def fetch_limit_codes(trade_date: str) -> tuple:
    """返回 (涨停代码集合, 跌停代码集合)"""
    try:
        df_zt = pro.limit_list_d(trade_date=trade_date, limit_type='U')
        df_dt = pro.limit_list_d(trade_date=trade_date, limit_type='D')
        zt = set(df_zt['ts_code'].tolist()) if df_zt is not None and not df_zt.empty else set()
        dt = set(df_dt['ts_code'].tolist()) if df_dt is not None and not df_dt.empty else set()
        return zt, dt
    except Exception:
        return set(), set()


def fetch_daily_pct(trade_date: str, codes: list) -> dict:
    """返回 {ts_code: pct_chg}"""
    result = {}
    for code in codes:
        try:
            df = pro.daily(ts_code=code, trade_date=trade_date)
            if df is not None and not df.empty:
                result[code] = float(df.iloc[0]['pct_chg'])
        except Exception:
            pass
    return result


def fetch_theme_zt_count(trade_date: str) -> dict:
    """返回 {题材: 涨停数}"""
    try:
        df = pro.kpl_list(trade_date=trade_date, list_type='limit_up')
    except Exception:
        return {}
    cnt = {}
    if df is None or df.empty or 'theme' not in df.columns:
        return cnt
    for _, r in df.iterrows():
        theme_str = str(r.get('theme', '') or '')
        for t in re.split(r'[/+|,，/、;；/s]+', theme_str):
            t = t.strip()
            if t:
                cnt[t] = cnt.get(t, 0) + 1
    return cnt


def get_stock_code_map() -> dict:
    """返回 {股票名称: ts_code}"""
    try:
        df = pro.stock_basic(fields='ts_code,name')
        return {row['name']: row['ts_code'] for _, row in df.iterrows()} if df is not None else {}
    except Exception:
        return {}


# ── 解析复盘表 3.4 节候选股池 ────────────────────────────────

def parse_review_md(md_path: Path, name_to_code: dict) -> list:
    """
    从复盘表 md 文件解析 3.4 节候选股池中的龙头股。
    只取「板数 >= 2」的股票（首板不做回溯，样本意义不大）。
    返回 list of dict: {name, code, boards, theme}
    去重（同一股票可能出现在多个题材下）
    """
    text = md_path.read_text(encoding='utf-8')
    
    # 找到 3.4 节
    sec_match = re.search(r'### 3/.4.*?(?=### 3/.5|## 四|$)', text, re.DOTALL)
    if not sec_match:
        return []
    section = sec_match.group(0)
    
    seen_codes = set()
    stocks = []
    current_theme = ''
    
    for line in section.splitlines():
        # 检测题材标题行（如 #### 风电（今日涨停24只...）
        theme_match = re.match(r'####/s+(.+?)（', line)
        if theme_match:
            current_theme = theme_match.group(1).strip()
            continue
        
        # 解析表格行
        if not line.startswith('|'):
            continue
        if '---' in line or '顺位' in line or '股票' in line:
            continue
        
        cols = [c.strip() for c in line.strip('|').split('|')]
        if len(cols) < 4:
            continue
        
        # 股票名称（去掉 ** 加粗）
        name_raw = cols[1].strip('* ').strip()
        # 板数列
        board_str = cols[2].strip()
        board_match = re.search(r'(/d+)板', board_str)
        if not board_match:
            continue
        boards = int(board_match.group(1))
        if boards < 2:
            continue  # 只回溯2板以上
        
        # 查找 ts_code
        code_match = re.search(r'/((/d{6}/.[A-Z]{2})/)', name_raw)
        if code_match:
            code = code_match.group(1)
            name = re.sub(r'/(.*?/)', '', name_raw).strip('* ').strip()
        else:
            name = name_raw
            code = name_to_code.get(name, '')
        
        if not code or code in seen_codes:
            continue
        
        seen_codes.add(code)
        stocks.append({
            'name':   name,
            'code':   code,
            'boards': boards,
            'theme':  current_theme,
        })
    
    return stocks


# ── 生成单条经验记录 ─────────────────────────────────────────

def classify_result(is_zt: bool, is_dt: bool, pct: float) -> str:
    """判断全天结果"""
    if is_zt or pct > 5:
        return 'WIN'
    elif is_dt or pct < -3:
        return 'LOSE'
    else:
        return 'FLAT'


def classify_type(result: str, auc_pct: float, auc_amt: float,
                  theme_today: int, theme_prev: int) -> tuple:
    """
    判断失误类型和校准建议。
    由于历史速查卡已删除，无法判断「条件是否触发」，
    改为基于竞价数据和结果直接分类：
      - WIN + 竞价涨幅>=3% → 命中（有效竞价信号）
      - WIN + 竞价涨幅<3%  → 冷启动型
      - LOSE + 题材今日涨停数下跌>50% → 题材崩盘型
      - LOSE + 题材仍活跃 → 阈值偏低型（竞价涨幅偏高时触发）
      - FLAT → 正确过滤（中性）
    返回 (失误类型, 校准建议)
    """
    if result == 'WIN':
        if auc_pct >= 9.5:
            # 一字板封死（竞价涨幅≈10%），开盘买不到，不是可操作信号，单独标记
            return ('命中（一字板）', f'竞价涨幅{auc_pct:.1f}%≥9.5%，一字板封死，开盘买不到；不纳入涨幅校准')
        elif auc_pct >= 3.0:
            return ('命中', f'竞价涨幅{auc_pct:.1f}%≥3%+WIN，有效样本；涨幅阈值参考{auc_pct:.1f}%')
        else:
            return ('冷启动型', f'竞价涨幅{auc_pct:.1f}%<3%但WIN，样本积累中')
    elif result == 'LOSE':
        if theme_prev > 0 and theme_today / theme_prev < 0.5:
            return ('题材崩盘型', '题材今日涨停数下跌>50%，阈值不调，题材选择失误')
        else:
            return ('阈值偏低型', f'竞价涨幅{auc_pct:.1f}%但LOSE，题材仍活跃，建议上调阈值')
    else:
        return ('正确过滤', 'FLAT，中性结果')


def build_record(next_date_str: str, stock: dict,
                 auc_data: dict, zt_codes: set, dt_codes: set,
                 daily_pct: dict,
                 theme_today: dict, theme_prev: dict) -> dict | None:
    """构建单条经验记录，返回 dict 或 None（数据不足时）"""
    code = stock['code']
    a    = auc_data.get(code, {})
    
    if not a:
        return None  # 无竞价数据，跳过
    
    auc_amt   = a.get('amount_bn', 0.0)
    auc_pct   = a.get('pct', 0.0)
    vol_ratio = a.get('vol_ratio', 0.0)
    
    pct     = daily_pct.get(code, 0.0)
    is_zt   = code in zt_codes
    is_dt   = code in dt_codes
    result  = classify_result(is_zt, is_dt, pct)
    
    # 题材涨停数（今日 vs 昨日）
    theme = stock['theme']
    t_today = theme_today.get(theme, 0)
    t_prev  = theme_prev.get(theme, 0)
    theme_str = f"{t_today}/{t_prev}" if theme else "—/—"
    
    miss_type, advice = classify_type(result, auc_pct, auc_amt, t_today, t_prev)
    
    # 全天结果描述
    if is_zt:
        result_str = 'WIN（涨停）'
    elif is_dt:
        result_str = 'LOSE（跌停）'
    else:
        result_str = f'{"WIN" if result == "WIN" else "LOSE" if result == "LOSE" else "FLAT"}（{pct:+.2f}%）'
    
    return {
        'date':       next_date_str.replace('-', ''),
        'name':       stock['name'],
        'code':       code,
        'boards':     f"{stock['boards']}板",
        'threshold':  f"回溯（无速查卡）",
        'auc_amt':    f"{auc_amt:.2f}亿",
        'auc_pct':    f"{auc_pct:+.1f}%",
        'vol_ratio':  f"{vol_ratio:.1f}",
        'result':     result_str,
        'theme_str':  theme_str,
        'miss_type':  miss_type,
        'advice':     advice,
    }


def format_record_row(rec: dict) -> str:
    """格式化为经验库表格行"""
    return (
        f"| {rec['date']} | {rec['name']} | {rec['boards']} "
        f"| {rec['threshold']} | {rec['auc_amt']} | {rec['auc_pct']} "
        f"| {rec['vol_ratio']} | {rec['result']} | {rec['theme_str']} "
        f"| **{rec['miss_type']}** | {rec['advice']} |"
    )


# ── 主流程 ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='回溯经验库竞价数据')
    parser.add_argument('--dry-run', action='store_true', help='只打印，不写入经验库')
    parser.add_argument('--min-boards', type=int, default=2, help='最低板数（默认2板）')
    args = parser.parse_args()
    
    print("=== 回溯经验库脚本启动 ===")
    print(f"复盘表目录：{REVIEW_DIR}")
    print(f"经验库路径：{EXP_LIB_PATH}")
    print(f"模式：{'DRY RUN（不写入）' if args.dry_run else '写入模式'}")
    print()
    
    # 加载已有记录日期
    existing_dates = load_existing_dates(EXP_LIB_PATH)
    print(f"经验库已有记录日期：{sorted(existing_dates)}")
    print()
    
    # 获取所有历史复盘表 md 文件（排除模板）
    md_files = sorted([
        f for f in REVIEW_DIR.glob("每日复盘表_*.md")
        if '模板' not in f.name
    ])
    print(f"找到 {len(md_files)} 份历史复盘表")
    
    # 获取股票名称→代码映射
    print("拉取股票基础信息...")
    name_to_code = get_stock_code_map()
    print(f"共 {len(name_to_code)} 只股票")
    print()
    
    all_records = []
    
    for md_file in md_files:
        # 解析日期
        date_match = re.search(r'(/d{4}-/d{2}-/d{2})', md_file.name)
        if not date_match:
            continue
        review_date_fmt = date_match.group(1)
        review_date     = review_date_fmt.replace('-', '')
        
        # 获取次日交易日
        next_date = get_next_trade_date(review_date)
        next_date_fmt = f"{next_date[:4]}-{next_date[4:6]}-{next_date[6:]}"
        
        # 检查次日是否已在经验库中（跳过已有记录）
        if next_date in existing_dates:
            print(f"[跳过] {review_date_fmt} → 次日 {next_date_fmt} 已在经验库中")
            continue
        
        print(f"处理 {review_date_fmt} 复盘表 → 次日 {next_date_fmt} 竞价数据...")
        
        # 解析复盘表中的龙头股
        stocks = parse_review_md(md_file, name_to_code)
        if not stocks:
            print(f"  [跳过] 未解析到候选股")
            continue
        
        # 过滤板数
        stocks = [s for s in stocks if s['boards'] >= args.min_boards]
        print(f"  解析到 {len(stocks)} 只 {args.min_boards}板以上龙头股：{[s['name'] for s in stocks]}")
        
        codes = [s['code'] for s in stocks if s['code']]
        if not codes:
            print(f"  [跳过] 无有效代码")
            continue
        
        # 拉取次日数据
        print(f"  拉取次日 {next_date_fmt} 竞价数据...")
        auc_data = fetch_auction(next_date)
        if not auc_data:
            print(f"  [警告] 次日竞价数据为空（可能是非交易日或数据源问题）")
            continue
        
        print(f"  拉取次日 {next_date_fmt} 涨跌停数据...")
        zt_codes, dt_codes = fetch_limit_codes(next_date)
        
        print(f"  拉取次日 {next_date_fmt} 日线数据...")
        daily_pct = fetch_daily_pct(next_date, codes)
        
        print(f"  拉取次日 {next_date_fmt} 题材涨停数...")
        theme_today = fetch_theme_zt_count(next_date)
        theme_prev  = fetch_theme_zt_count(review_date)
        
        # 生成记录
        day_records = []
        for stock in stocks:
            rec = build_record(
                next_date_fmt, stock, auc_data,
                zt_codes, dt_codes, daily_pct,
                theme_today, theme_prev
            )
            if rec:
                day_records.append(rec)
                print(f"    [OK] {stock['name']}({stock['boards']}板) | 竞价{rec['auc_pct']} | {rec['result']} | {rec['miss_type']}")
            else:
                print(f"    [--] {stock['name']} 无竞价数据，跳过")
        
        all_records.extend(day_records)
        print(f"  本日生成 {len(day_records)} 条记录")
        print()
    
    print(f"=== 共生成 {len(all_records)} 条回溯记录 ===")
    print()
    
    if not all_records:
        print("无新记录需要写入。")
        return
    
    # 打印所有记录
    print("--- 生成的记录预览 ---")
    print("| 记录日期 | 股票 | 板数 | 速查卡阈值 | 实际竞价成交额 | 实际竞价涨幅 | 量比 | 全天结果 | 题材今/昨涨停 | 失误类型 | 校准建议 |")
    print("|:---:|---|:---:|---|:---:|:---:|:---:|:---:|:---:|---|---|")
    for rec in all_records:
        print(format_record_row(rec))
    print()
    
    if args.dry_run:
        print("[DRY RUN] 未写入经验库。")
        return
    
    # 写入经验库
    print(f"写入经验库：{EXP_LIB_PATH}")
    exp_text = EXP_LIB_PATH.read_text(encoding='utf-8')
    
    # 找到竞价阈值校准记录表的末尾（在 --- 分隔线之前）
    # 在表格最后一行之后、下一个 --- 之前插入
    insert_marker = "/n---/n/n## 题材判断样本"
    if insert_marker not in exp_text:
        # 兜底：直接在竞价阈值校准记录部分末尾追加
        insert_marker = "/n---/n/n## 龙头判断校准"
    
    new_rows = "/n".join(format_record_row(rec) for rec in all_records)
    
    # 在表格末尾（--- 之前）插入新行
    exp_text = exp_text.replace(
        insert_marker,
        f"/n{new_rows}{insert_marker}"
    )
    
    EXP_LIB_PATH.write_text(exp_text, encoding='utf-8')
    print(f"[OK] 已追加 {len(all_records)} 条记录到经验库。")
    print()
    
    # 统计命中记录
    hit_records = [r for r in all_records if r['miss_type'] == '命中']
    hit_yz = [r for r in all_records if r['miss_type'] == '命中（一字板）']
    print(f"=== 命中记录统计（用于涨幅校准）===")
    print(f"总命中数：{len(hit_records)} 条（非一字板，纳入校准）")
    print(f"一字板命中：{len(hit_yz)} 条（已剔除，不纳入涨幅校准）")
    
    by_boards = {}
    for r in hit_records:
        b = r['boards']
        by_boards.setdefault(b, []).append(float(r['auc_pct'].replace('%', '').replace('+', '')))
    
    print()
    print("--- 各板数非一字板命中中位数（速查卡校准值）---")
    for boards, pcts in sorted(by_boards.items()):
        pcts.sort()
        n = len(pcts)
        median = pcts[n//2] if n % 2 == 1 else (pcts[n//2-1] + pcts[n//2]) / 2
        print(f"  {boards}：{n}条，竞价涨幅中位数 = {median:.1f}%  ← 速查卡校准值")
        print(f"    样本：{[f'{p:.1f}%' for p in pcts]}")


if __name__ == '__main__':
    main()
