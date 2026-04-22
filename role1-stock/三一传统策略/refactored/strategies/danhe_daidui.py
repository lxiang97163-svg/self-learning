# -*- coding: utf-8 -*-
"""单核带队（重构版）：竞价封单前五 -> ths 概念 -> 概念下金额/换手前三。

变化：
* Cookies (``PHPSESSID`` / ``server_name_session``) 从 config.local.json 读取。
* 若 Selenium 失败或 cookie 不完整 -> 回退到本地 md。
* 保留 12 worker 线程池 + JSON 缓存逻辑 (build_stock_to_concepts_map)。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.auction import enrich_auction  # noqa: E402
from common.config import init_tushare_clients  # noqa: E402
from common.notifier import dispatch, parse_notify_args  # noqa: E402

logger = logging.getLogger(__name__)


PAGE_URL = "https://duanxianxia.com/web/jjlive"
BASE_DIR = Path(__file__).resolve().parent.parent
JJLIVE_DIR = BASE_DIR / "jjlive_data"
UNIFIED_OUT = BASE_DIR / "unified_out"

EXCLUDED_CONCEPTS_DEFAULT = [
    "沪深300样本股", "上证50样本股", "上证180成份股", "上证380成份股", "中证500成份股",
    "融资融券", "沪股通", "深股通", "同花顺漂亮100", "同花顺中特估100", "高股息精选",
    "同花顺出海50", "同花顺果指数", "同花顺新质50", "中国AI 50",
    "2024三季报预增", "2024年报预增", "2025一季报预增", "2025中报预增",
    "2025三季报预增", "2025年报预增",
    "证金持股", "PPP概念", "中字头股票", "超级品牌", "国家大基金持股", "国企改革",
    "回购增持再贷款概念", "雅下水电概念",
]


def _get_excluded_concepts() -> set:
    path = UNIFIED_OUT / "excluded_concepts.txt"
    if path.exists():
        try:
            return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        except OSError:
            pass
    return set(EXCLUDED_CONCEPTS_DEFAULT)


def _code_to_ts_code(code_str: str) -> Optional[str]:
    code_str = str(code_str).strip()
    if not code_str or len(code_str) < 6:
        return None
    if code_str.startswith(("6", "5")):
        return code_str + ".SH"
    return code_str + ".SZ"


def _parse_fengdan_table_html(html: str) -> List[Dict]:
    rows: List[Dict] = []
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


def _extract_tblive_table(html: str) -> str:
    if not html or "tblive" not in html:
        return ""
    td_match = re.search(r'<td\s+id=["\']tblive["\'][^>]*>', html, re.IGNORECASE)
    if not td_match:
        return ""
    start_pos = td_match.end()
    table_start = html.find("<table", start_pos)
    if table_start == -1:
        return ""
    depth = 1
    pos = html.find(">", table_start) + 1
    while pos < len(html) and depth > 0:
        next_open = html.find("<table", pos)
        next_close = html.find("</table>", pos)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 6
        else:
            depth -= 1
            if depth == 0:
                return html[table_start : next_close + 8]
            pos = next_close + 8
    return ""


def _top5_from_table_html(table_html: str) -> Optional[List[Tuple[str, str]]]:
    if not table_html:
        return None
    rows = _parse_fengdan_table_html(table_html)
    if len(rows) < 5:
        return None
    result = []
    for r in rows[:5]:
        tc = _code_to_ts_code(r["code"])
        if tc:
            result.append((tc, r["name"]))
    return result if len(result) >= 5 else None


def _fetch_html_with_selenium(cookies: Dict[str, str]) -> Optional[str]:
    if not cookies.get("PHPSESSID") or not cookies.get("server_name_session"):
        return None
    try:
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
        from selenium.webdriver.chrome.options import Options  # type: ignore
    except ImportError:
        logger.warning("⚠️ selenium 未安装，跳过 Selenium 抓取")
        return None

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as exc:
        logger.warning("⚠️ 创建 Chrome 驱动失败: %s", exc)
        return None

    try:
        driver.get(PAGE_URL)
        driver.add_cookie({"name": "PHPSESSID", "value": cookies["PHPSESSID"]})
        driver.add_cookie({"name": "server_name_session", "value": cookies["server_name_session"]})
        driver.refresh()
        try:
            WebDriverWait(driver, 15).until(
                lambda d: d.find_element(By.ID, "tblive").find_elements(By.TAG_NAME, "table")
            )
        except Exception:
            pass
        time.sleep(2)
        return driver.page_source
    except Exception as exc:
        logger.warning("⚠️ Selenium 抓取失败: %s", exc)
        return None
    finally:
        driver.quit()


def _parse_md_fallback(md_path: Path) -> List[Tuple[str, str]]:
    if not md_path.exists():
        return []
    content = md_path.read_text(encoding="utf-8")
    idx = content.find("| 序号 | 代码 | 名称 |")
    if idx == -1:
        return []
    rows: List[Tuple[str, str]] = []
    pat = re.compile(r"\|\s*\d+\s*\|\s*(\d+)\s*\|\s*([^|]+)\|")
    for m in pat.finditer(content[idx:]):
        tc = _code_to_ts_code((m.group(1) or "").strip())
        name = (m.group(2) or "").strip()
        if tc and name:
            rows.append((tc, name))
            if len(rows) >= 5:
                break
    return rows


def _fetch_one_concept_members(pro, row) -> Optional[Tuple[str, str, List[str]]]:
    concept_ts = row["ts_code"]
    concept_name = row["name"]
    try:
        df_m = pro.ths_member(ts_code=concept_ts, fields="con_code")
    except Exception:
        return None
    if df_m is None or df_m.empty:
        return None
    return concept_ts, concept_name, df_m["con_code"].tolist()


def build_stock_to_concepts_map(
    pro, *, only_for_codes=None, max_workers: int = 12, use_cache: bool = True
) -> Dict[str, List[Tuple[str, str]]]:
    today_str = datetime.now().strftime("%Y%m%d")
    JJLIVE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = JJLIVE_DIR / f"stock_concepts_map_{today_str}.json"
    only_set = set(only_for_codes) if only_for_codes else None
    excluded = _get_excluded_concepts()

    if use_cache and cache_file.is_file():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if data.get("date") == today_str:
                full: Dict[str, List[Tuple[str, str]]] = {}
                for k, v in data.get("stock_concepts", {}).items():
                    filtered = [(t[0], t[1]) for t in v if t[1] not in excluded]
                    if filtered:
                        full[k] = filtered
                logger.info("    同花顺概念成分使用本地缓存")
                if only_set:
                    return {k: full[k] for k in only_set if k in full}
                return full
        except Exception as exc:
            logger.warning("    缓存读取失败: %s，重新拉取", exc)

    df_concepts = pro.ths_index(exchange="A", type="N")
    if df_concepts is None or df_concepts.empty:
        return {}
    if excluded:
        df_concepts = df_concepts[~df_concepts["name"].isin(excluded)]

    stock_concepts: Dict[str, List[Tuple[str, str]]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_one_concept_members, pro, row): i
            for i, row in df_concepts.iterrows()
        }
        total = len(futures)
        for future in as_completed(futures):
            done += 1
            if done % 80 == 0:
                logger.info("    已扫描 %d/%d 个概念...", done, total)
            res = future.result()
            if not res:
                continue
            c_ts, c_name, con_codes = res
            for con in con_codes:
                stock_concepts.setdefault(con, []).append((c_ts, c_name))

    if use_cache:
        try:
            serial = {"date": today_str, "stock_concepts": {k: [list(t) for t in v] for k, v in stock_concepts.items()}}
            cache_file.write_text(json.dumps(serial, ensure_ascii=False, indent=0), encoding="utf-8")
            logger.info("    已写入同花顺概念缓存")
        except OSError as exc:
            logger.warning("    缓存写入失败: %s", exc)

    if only_set:
        return {k: stock_concepts[k] for k in only_set if k in stock_concepts}
    return stock_concepts


def _is_30_prefix(ts_code: str) -> bool:
    return str(ts_code).strip().startswith("30")


def _top_n_ensure_one_30(df_sorted: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    if df_sorted is None or df_sorted.empty:
        return df_sorted
    rows = []
    has_30 = False
    for _, row in df_sorted.iterrows():
        rows.append(row)
        if _is_30_prefix(row.get("ts_code", "")):
            has_30 = True
        if len(rows) >= n and has_30:
            break
    if not rows:
        return df_sorted.iloc[0:0]
    return pd.DataFrame(rows)


def _pick_most_relevant_concept(
    stock_code: str, stock_concepts_map: Dict[str, List[Tuple[str, str]]], lu_desc: str
) -> Optional[Tuple[str, str]]:
    excluded = _get_excluded_concepts()
    concepts = [(c_ts, c_name) for c_ts, c_name in stock_concepts_map.get(stock_code, []) if c_name not in excluded]
    if not concepts:
        return None
    lu_desc = (lu_desc or "").strip()
    for c_ts, c_name in concepts:
        if lu_desc and c_name and (lu_desc in c_name or c_name in lu_desc):
            return c_ts, c_name
    return concepts[0]


def _get_yesterday_for(pro, today: str, cfg) -> str:
    start = (datetime.strptime(today, "%Y%m%d") - timedelta(days=14)).strftime("%Y%m%d")
    try:
        df_idx = pro.index_daily(ts_code="000001.SH", start_date=start, end_date=today)
    except pd.errors.EmptyDataError:
        import chinadata.ca_data as ts_mod  # type: ignore
        import chinamindata.min as tss_mod  # type: ignore

        ts_mod.set_token(cfg.tushare_token)
        tss_mod.set_token(cfg.tushare_min_token)
        df_idx = pro.index_daily(ts_code="000001.SH", start_date=start, end_date=today)
    if df_idx is None or df_idx.empty:
        return today
    dates = df_idx.sort_values("trade_date", ascending=False)["trade_date"].tolist()
    if len(dates) >= 2 and dates[0] == today:
        return dates[1]
    return dates[0]


def _get_kpl_lu_desc_for_codes(pro, ts_codes: List[str], end_date: str, past_days: int = 730) -> Dict[str, str]:
    # Fix MEDIUM #14: default window changed from 365 to 730 days (2 years) for sufficient history
    start_date = (datetime.today() - timedelta(days=past_days)).strftime("%Y%m%d")
    result: Dict[str, str] = {}
    for i in range(0, len(ts_codes), 50):
        batch = ts_codes[i : i + 50]
        df = pro.kpl_list(ts_code=",".join(batch), start_date=start_date, end_date=end_date, list_type="limit_up")
        if df is None or df.empty:
            continue
        df = df.sort_values("trade_date", ascending=True)
        for code in batch:
            if code in result:
                continue
            sub = df[df["ts_code"] == code]
            if not sub.empty:
                result[code] = sub.iloc[-1].get("lu_desc", "") or "未知"
    for code in ts_codes:
        result.setdefault(code, "未知")
    return result


def run() -> int:
    options = parse_notify_args()
    cfg, pro, pro_min = init_tushare_clients()

    today = datetime.now().strftime("%Y%m%d")
    yesterday = _get_yesterday_for(pro, today, cfg)
    logger.info("日期: 封单/竞价=%s  涨停原因/概念基准=%s", today, yesterday)

    # 取竞价封单前五
    logger.info("正在拉取竞价封单...")
    cookies = cfg.dxx_cookies.as_dict()
    html = _fetch_html_with_selenium(cookies) if cfg.dxx_cookies.is_complete() else None
    if not cfg.dxx_cookies.is_complete():
        logger.warning("⚠️ 未配置 dxx_cookies，跳过 Selenium，直接走本地 md 回退")
    top5: Optional[List[Tuple[str, str]]] = None
    if html:
        top5 = _top5_from_table_html(_extract_tblive_table(html))
    if not top5:
        JJLIVE_DIR.mkdir(parents=True, exist_ok=True)
        md_candidates = sorted(
            (p for p in JJLIVE_DIR.glob("竞价封单汇总_*.md")), reverse=True
        )
        if md_candidates:
            top5 = _parse_md_fallback(md_candidates[0])
    if not top5:
        logger.error("未解析到竞价封单前五名，请检查 dxx_cookies 或 jjlive_data/竞价封单汇总_*.md")
        return 1
    logger.info("【竞价封单前五名】")
    for i, (tc, name) in enumerate(top5, 1):
        logger.info("  %d. %s(%s)", i, name, tc)

    ts_codes = [t[0] for t in top5]
    lu_desc_map = _get_kpl_lu_desc_for_codes(pro, ts_codes, yesterday)

    df_auc_raw = pro_min.stk_auction(trade_date=today)
    if df_auc_raw is None or df_auc_raw.empty:
        logger.warning("无法获取 %s 竞价数据", today)
        return 1
    # Fix HIGH #6: use enrich_auction instead of hand-rolling pct_chg/amount_wan/turnover_rate
    # enrich_auction now also includes division-by-zero protection for pre_close
    df_auc = enrich_auction(df_auc_raw)

    df_stocks = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    name_map = dict(zip(df_stocks["ts_code"], df_stocks["name"]))

    # 方式一：涨停概念榜
    lead_to_concepts: Dict[str, List[Tuple[str, str]]] = {c: [] for c in ts_codes}
    concept_members_cache: Dict[str, List[str]] = {}
    df_cpt = pro.limit_cpt_list(trade_date=yesterday)
    stock_concepts_fallback: Optional[Dict[str, List[Tuple[str, str]]]] = None
    if isinstance(df_cpt, pd.DataFrame) and not df_cpt.empty:
        df_cpt_sorted = df_cpt.sort_values("rank", ascending=True) if "rank" in df_cpt.columns else df_cpt
        remaining = set(ts_codes)
        for _, row in df_cpt_sorted.iterrows():
            concept_ts = row.get("ts_code")
            concept_name = row.get("name")
            if not concept_ts or not concept_name:
                continue
            df_members = pro.ths_member(ts_code=concept_ts, fields="con_code")
            if df_members is None or df_members.empty:
                continue
            con_codes = df_members["con_code"].tolist()
            concept_members_cache[concept_ts] = con_codes
            hit = remaining.intersection(con_codes)
            if hit:
                for code in hit:
                    lead_to_concepts[code].append((concept_ts, concept_name))
                remaining -= hit
                if not remaining:
                    break

    df_yzt = pro.limit_list_d(trade_date=yesterday, limit_type="U")
    yesterday_zt_set = set(df_yzt["ts_code"]) if df_yzt is not None and not df_yzt.empty else set()

    push_lines: List[str] = [f"📊 单核带队 {today}", "=" * 70, "", "【竞价封单前五名】"]
    for i, (tc, name) in enumerate(top5, 1):
        push_lines.append(f"  {i}. {name}({tc})")
    push_lines.append("")

    for idx, (lead_code, lead_name) in enumerate(top5, 1):
        lu_desc = lu_desc_map.get(lead_code, "未知")
        concepts = lead_to_concepts.get(lead_code, [])
        concept = None
        if concepts:
            lu_s = (lu_desc or "").strip()
            for c_ts, c_name in concepts:
                if lu_s and c_name and (lu_s in c_name or c_name in lu_s):
                    concept = (c_ts, c_name)
                    break
            if concept is None:
                if stock_concepts_fallback is None:
                    stock_concepts_fallback = build_stock_to_concepts_map(pro, only_for_codes=ts_codes)
                concept = _pick_most_relevant_concept(lead_code, stock_concepts_fallback, lu_desc)
                if concept is None:
                    concept = concepts[0]
        if not concept:
            push_lines.append(
                f"\n{idx}. {lead_name}({lead_code})  涨停原因: {lu_desc}\n   未匹配到涨停概念榜概念"
            )
            continue

        concept_ts, concept_name = concept
        member_codes = concept_members_cache.get(concept_ts)
        if member_codes is None:
            df_members = pro.ths_member(ts_code=concept_ts, fields="con_code")
            member_codes = df_members["con_code"].tolist() if df_members is not None and not df_members.empty else []
            concept_members_cache[concept_ts] = member_codes
        if not member_codes:
            push_lines.append(
                f"\n{idx}. {lead_name}({lead_code})  涨停原因: {lu_desc}  概念: {concept_name}\n   概念无成分股"
            )
            continue

        df_sector = df_auc[df_auc["ts_code"].isin(member_codes)]
        if df_sector.empty:
            push_lines.append(
                f"\n{idx}. {lead_name}({lead_code})  涨停原因: {lu_desc}  概念: {concept_name}\n   概念下无今日竞价数据"
            )
            continue

        sector_open_pct = df_sector["pct_chg"].mean()
        sector_zt_count = sum(1 for c in member_codes if c in yesterday_zt_set)
        amt_top3 = _top_n_ensure_one_30(df_sector.sort_values("amount_wan", ascending=False))
        hs_top3 = _top_n_ensure_one_30(df_sector.sort_values("turnover_rate", ascending=False))

        push_lines.append(f"\n{idx}. {lead_name}({lead_code})")
        push_lines.append(f"   涨停原因: {lu_desc}")
        push_lines.append(f"   所属概念: {concept_name}")
        push_lines.append(f"   板块今日高开: {sector_open_pct:+.2f}%  板块内涨停: {sector_zt_count}只")
        push_lines.append("   该概念下 竞价金额前三:")
        for i, (_, row) in enumerate(amt_top3.iterrows(), 1):
            push_lines.append(
                f"      {i}) {name_map.get(row['ts_code'], row['ts_code'])}({row['ts_code']}) 金额{int(row['amount_wan'])}万 竞价{row['pct_chg']:+.2f}%"
            )
        push_lines.append("   该概念下 竞价换手前三:")
        for i, (_, row) in enumerate(hs_top3.iterrows(), 1):
            push_lines.append(
                f"      {i}) {name_map.get(row['ts_code'], row['ts_code'])}({row['ts_code']}) 换手{row['turnover_rate']:.4f}% 竞价{row['pct_chg']:+.2f}%"
            )

    push_lines.append("\n" + "=" * 70)
    push_lines.append("(研究参考, 不构成投资建议)")

    content = "\n".join(push_lines)
    dispatch(content, title=f"单核带队 {today}", token=cfg.pushplus_token, options=options)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
