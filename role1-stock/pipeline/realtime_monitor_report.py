# -*- coding: utf-8 -*-
"""
盘中监控五段式报告：大盘 / 题材 / 第一优先 / 第二优先 / 盘中观察各包。
数据：gather_snapshot + 每日复盘表（昨日成交额）+ 东财上证指数当日累计额（push2delay）。

说明：
- 「昨日成交额」来自复盘表「两市成交额」行（与生成脚本一致，数值实为上证口径）。
- 「今日累计」为东财上证指数 f6（与昨日全日对比为近似放量/缩量，非同一分钟「同期」）。
- **同期缩量/放量**：用东财上证指数 **5 分钟 K** 计算「截至当前已产生根数」的累计成交额，
  与 **前一交易日同一根数** 对比；含义接近短线侠等工具里的「相对昨日同期 %」，**非**爬取 duanxianxia.com
  （该站量能图为前端/插件展示，无稳定公开 API，本机探测为 403/无接口名）。
- 输出结构固定为：**执行摘要（口令）** → **1 大盘** → **2 题材** → **3～4** 优先表 → **5 盘中观察**：含 **5.1** 包汇总、**5.2** 总表、**5.3 每包分表（代码/名称分列、一股一行）**、**5.4 各股流水清单（一股一条编号）**，不省略观察包内成分股。
- 执行摘要为编号 1～5 的口令式简报；**全市场首板/涨停晋级率**见 `realtime_promotion_ts.py`。**全市场成交额 Top10 同期 5 分 K 额对比**见 `realtime_top10_5m_compare.py`（昨日篮=tushare 全日额 Top10；今日篮=东财当前额 Top10；根数 N 与上证同期一致）。
- 非投资建议；盘中快照≠9:25 竞价。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from _paths import REVIEW_DIR

from realtime_engine import (
    build_vamp_note,
    gather_snapshot,
    pack_strong_signals,
    parse_card,
)
from realtime_promotion_ts import (
    fetch_promotion_rates,
    format_promotion_line,
    get_tushare_pro,
    promotion_md_rows,
)
from realtime_top10_5m_compare import (
    compute_top10_5m_volume_compare,
    format_top10_vol_line,
    top10_vol_md_rows,
)

_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}
_EM_ULIST = "http://push2delay.eastmoney.com/api/qt/ulist.np/get"
_EM_CLIST = "http://push2delay.eastmoney.com/api/qt/clist/get"
_EM_CLIST_ALT = "http://push2.eastmoney.com/api/qt/clist/get"
_EM_KLINE_HOSTS = (
    "http://push2his.eastmoney.com",
    "http://push2delay.eastmoney.com",
    "http://push2.eastmoney.com",
)


def _clear_proxy_env():
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def parse_review_basis_date(content: str) -> Optional[str]:
    m = re.search(r"依据\s*\*\*(\d{4}-\d{2}-\d{2})\*\*", content)
    return m.group(1) if m else None


def read_review_turnover_yi(review_date: str, base_dir: str) -> Tuple[Optional[float], Optional[str]]:
    """读取 每日复盘表_YYYY-MM-DD.md 中「两市成交额」数值（亿）。"""
    path = os.path.join(base_dir, f"每日复盘表_{review_date}.md")
    if not os.path.exists(path):
        return None, None
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    m = re.search(r"\*\*两市成交额\*\*[：:]\s*([\d.]+)\s*亿", txt)
    if not m:
        return None, path
    try:
        return float(m.group(1)), path
    except ValueError:
        return None, path


def fetch_em_sh_amount_yi() -> Optional[float]:
    """上证指数当日累计成交额（亿），东财 ulist f6。"""
    proxies = {"http": None, "https": None}
    for url in (_EM_ULIST, "http://push2.eastmoney.com/api/qt/ulist.np/get"):
        try:
            r = requests.get(
                url,
                params={
                    "secids": "1.000001",
                    "fields": "f2,f3,f6,f12,f14",
                    "fltt": 2,
                    "invt": 2,
                    "ut": _EM_UT,
                },
                headers=_EM_HEADERS,
                timeout=14,
                proxies=proxies,
            )
            if r.status_code != 200:
                continue
            j = r.json()
            raw = (j or {}).get("data", {}).get("diff", [])
            items = list(raw.values()) if isinstance(raw, dict) else raw
            if not items:
                continue
            f6 = items[0].get("f6")
            if isinstance(f6, (int, float)) and f6 > 0:
                return float(f6) / 1e8
        except Exception:
            continue
    return None


def fetch_em_sh_5min_klines_one_day(ymd: str) -> List[str]:
    """
    上证指数某日全部 5 分钟 K 线（东财）。
    ymd: YYYY-MM-DD；返回 klines 字符串列表，单条格式含时间前缀与成交额字段。
    """
    beg = ymd.replace("-", "")
    proxies = {"http": None, "https": None}
    for host in _EM_KLINE_HOSTS:
        try:
            r = requests.get(
                f"{host}/api/qt/stock/kline/get",
                params={
                    "secid": "1.000001",
                    "klt": 5,
                    "fqt": 0,
                    "beg": beg,
                    "end": beg,
                    "fields2": "f51,f52,f53,f54,f55,f56,f57",
                    "ut": _EM_UT,
                },
                headers=_EM_HEADERS,
                timeout=16,
                proxies=proxies,
            )
            if r.status_code != 200:
                continue
            j = r.json()
            data = (j or {}).get("data")
            if not data:
                continue
            lines = data.get("klines") or []
            if lines:
                return list(lines)
        except Exception:
            continue
    return []


def fetch_em_sh_5min_klines_lmt(lmt: int = 300) -> List[str]:
    """拉最近若干根 5 分钟 K（不按日过滤），用于 beg/end 不可用时的回退。"""
    proxies = {"http": None, "https": None}
    for host in _EM_KLINE_HOSTS:
        try:
            r = requests.get(
                f"{host}/api/qt/stock/kline/get",
                params={
                    "secid": "1.000001",
                    "klt": 5,
                    "fqt": 0,
                    "lmt": lmt,
                    "fields2": "f51,f52,f53,f54,f55,f56,f57",
                    "ut": _EM_UT,
                },
                headers=_EM_HEADERS,
                timeout=18,
                proxies=proxies,
            )
            if r.status_code != 200:
                continue
            j = r.json()
            data = (j or {}).get("data")
            if not data:
                continue
            lines = data.get("klines") or []
            if lines:
                return list(lines)
        except Exception:
            continue
    return []


def fetch_sina_sh_5min_klines(datalen: int = 400) -> List[str]:
    """
    新浪 5 分钟 K，转成与东财 klines 相近的逗号串；第 7 字段为成交量（股），
    与东财「成交额」不可混比绝对值，但**同期比**仍可用于缩量/放量判断。
    """
    try:
        r = requests.get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": "sh000001", "scale": 5, "ma": "no", "datalen": datalen},
            headers={"User-Agent": _EM_HEADERS["User-Agent"]},
            timeout=18,
            proxies={"http": None, "https": None},
        )
        r.raise_for_status()
        raw = json.loads(r.text)
    except Exception:
        return []
    out: List[str] = []
    for x in raw:
        t = (x.get("day") or "").replace("  ", " ")
        op, cl, hi, lo = x.get("open"), x.get("close"), x.get("high"), x.get("low")
        vol = float(x.get("volume") or 0)
        line = f"{t},{op},{cl},{hi},{lo},{vol},{vol}"
        out.append(line)
    return out


def compute_same_period_5min_amount_ratio(
    yesterday_ymd: str, today_ymd: str
) -> Optional[Dict[str, Any]]:
    """
    截至「今日已产生的 5 分钟根数」，累计成交额 vs 昨日同一根数累计。
    返回 ratio=today/yesterday、pct_diff=(ratio-1)*100、根数 n。
    """
    kt = fetch_em_sh_5min_klines_one_day(today_ymd)
    ky = fetch_em_sh_5min_klines_one_day(yesterday_ymd)
    source_note = "东财·成交额"
    if not kt or not ky:
        all_k = fetch_em_sh_5min_klines_lmt(400)
        prefix_t = today_ymd[:10]
        prefix_y = yesterday_ymd[:10]
        kt = [k for k in all_k if k.split(",")[0].strip().startswith(prefix_t)]
        ky = [k for k in all_k if k.split(",")[0].strip().startswith(prefix_y)]
    if not kt or not ky:
        all_k = fetch_sina_sh_5min_klines(500)
        prefix_t = today_ymd[:10]
        prefix_y = yesterday_ymd[:10]
        kt = [k for k in all_k if k.split(",")[0].strip().startswith(prefix_t)]
        ky = [k for k in all_k if k.split(",")[0].strip().startswith(prefix_y)]
        source_note = "新浪·成交量（股，累计；仅用于同期相对强弱）"
    if not kt or not ky:
        return None
    prefix_t = today_ymd[:10]
    prefix_y = yesterday_ymd[:10]
    kt = [k for k in kt if k.split(",")[0].strip().startswith(prefix_t)]
    ky = [k for k in ky if k.split(",")[0].strip().startswith(prefix_y)]
    n = min(len(kt), len(ky))
    if n <= 0:
        return None

    def sum_amt(klines: List[str], n_bars: int) -> float:
        s = 0.0
        for k in klines[:n_bars]:
            parts = k.split(",")
            if len(parts) > 6:
                try:
                    s += float(parts[6])
                except ValueError:
                    pass
        return s

    amt_t = sum_amt(kt, n)
    amt_y = sum_amt(ky, n)
    if amt_y <= 0:
        return None
    ratio = amt_t / amt_y
    # 东财 parts[6] 为成交额（元）；新浪为成交量（股），均除以 1e8 以「亿」展示，便于阅读
    scale = 1e8
    unit = "亿元(额)" if source_note.startswith("东财") else "亿股(量)"
    return {
        "n_bars": n,
        "amt_today_yi": amt_t / scale,
        "amt_yest_yi": amt_y / scale,
        "ratio": ratio,
        "pct_vs_yesterday_same_bars": (ratio - 1.0) * 100.0,
        "today_ymd": today_ymd,
        "yesterday_ymd": yesterday_ymd,
        "source_note": source_note,
        "amount_unit": unit,
    }


def parse_buy_condition_rows(content: str) -> Dict[str, Dict[str, Any]]:
    """
    解析「| 标的 | 角色 | 买入条件 | 否决 |」行，提取代码与首个 ≥+X.XX% 门槛。
    """
    out: Dict[str, Dict[str, Any]] = {}
    row_re = re.compile(
        r"^\|\s*\*\*(.+?)\*\*\(([\d.]+)\.(SZ|SH)\)\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*([^|]*)\|"
    )
    for line in content.splitlines():
        m = row_re.match(line.strip())
        if not m:
            continue
        code = f"{m.group(2)}.{m.group(3)}"
        role = m.group(4).strip()
        buy = m.group(5).strip()
        if not buy:
            continue
        thresh: Optional[float] = None
        for mm in re.finditer(r"(?:≥|>=)\s*\+?\s*(\d+\.\d+)%", buy):
            try:
                thresh = float(mm.group(1))
                break
            except ValueError:
                pass
        if thresh is None:
            mm2 = re.search(r"\+(\d+\.\d+)%", buy)
            if mm2:
                try:
                    thresh = float(mm2.group(1))
                except ValueError:
                    pass
        out[code] = {"name": m.group(1).strip(), "role": role, "buy_raw": buy, "min_pct": thresh}
    return out


def rows_to_code_map(stock_rows: List[tuple]) -> Dict[str, tuple]:
    return {r[1]: r for r in stock_rows if len(r) >= 4}


def pct_for_code(code_full: str, code_map: Dict[str, tuple]) -> Optional[float]:
    num = code_full.split(".")[0]
    row = code_map.get(num)
    if not row:
        return None
    return float(row[3])


def fmt_pct(p: Optional[float]) -> str:
    if p is None:
        return "—"
    return f"{p:+.2f}%"


def one_line_summary(name: str, pct: Optional[float], role: str) -> str:
    if pct is None:
        return f"{name}（{role}）：行情缺失"
    if pct >= 9.4:
        return f"{name}（{role}）：接近涨停，注意封单与换手"
    if pct >= 5:
        return f"{name}（{role}）：偏强"
    if pct >= 0:
        return f"{name}（{role}）：红盘但未大肉"
    if pct <= -9.4:
        return f"{name}（{role}）：跌停附近，回避接力"
    return f"{name}（{role}）：绿盘，观望"


def format_immediate_buy_yes_no(
    pct: Optional[float],
    min_pct: Optional[float],
) -> str:
    """第一/第二优先：仅按速查涨幅数字门槛 + 当前涨跌幅，给出是否「具备立即买入」的机械结论。"""
    if pct is None:
        return "否（无行情）"
    if min_pct is None:
        return "否（速查无明确涨幅数字，无法机械判定「是」）"
    if pct + 1e-9 >= min_pct:
        return (
            f"是（当前 ≥+{min_pct:.2f}% 门槛；仍须人工核对封单/分歧/链上验证等全文，非荐股）"
        )
    return f"否（当前未到 +{min_pct:.2f}%）"


def format_immediate_buy_watch(
    rank: Optional[int],
    pack: dict,
    code_map: Dict[str, tuple],
    ks: Optional[float],
    sh_price: Optional[float],
) -> str:
    """盘中观察包：按速查「板块够强」数据项 + 顺位，不判分时。"""
    if rank is None:
        return "否（—）"
    if rank > 3:
        return "否（速查建议不做顺位 4、5）"
    c2, c3, _d = pack_strong_signals(pack, code_map)
    broken = ks is not None and sh_price is not None and sh_price < ks
    if broken:
        return f"否（上证低于关键位 {ks:.2f}，观察包慎做）"
    if not (c2 and c3):
        return "否（包内「板块够强」数据项未同时满足）"
    return "待定（数据项已齐；是否买入须分时确认，脚本无法代判「立即」）"


def fetch_em_board_top_rows(fs: str, n: int = 8) -> List[Tuple[str, float]]:
    """东财 clist：概念 m:90+t:3 / 行业 m:90+t:2，返回 [(名称, 涨跌幅%), ...]。"""
    proxies = {"http": None, "https": None}
    params = {
        "fid": "f3",
        "po": 1,
        "pz": n,
        "pn": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fs": fs,
        "fields": "f12,f14,f3",
        "ut": _EM_UT,
    }
    for url in (_EM_CLIST, _EM_CLIST_ALT):
        try:
            r = requests.get(
                url, params=params, headers=_EM_HEADERS, timeout=14, proxies=proxies
            )
            if r.status_code != 200:
                continue
            j = r.json()
            data = (j or {}).get("data") or {}
            diff = data.get("diff")
            if diff is None:
                continue
            if isinstance(diff, dict):
                diff = list(diff.values())
            out: List[Tuple[str, float]] = []
            for bk in diff[:n]:
                name = str(bk.get("f14") or "").strip()
                p3 = bk.get("f3")
                if not name:
                    continue
                try:
                    pf = float(p3) if p3 is not None else 0.0
                except (TypeError, ValueError):
                    pf = 0.0
                out.append((name, pf))
            if out:
                return out
        except Exception:
            continue
    return []


def _brief_priority_line(
    chain: List[tuple],
    code_map: Dict[str, tuple],
    buy_map: Dict[str, Dict[str, Any]],
) -> str:
    yes: List[str] = []
    for _tag, name, code in chain:
        pct = pct_for_code(code, code_map)
        meta = buy_map.get(code, {})
        imm = format_immediate_buy_yes_no(pct, meta.get("min_pct"))
        if imm.startswith("是"):
            yes.append(name)
    if yes:
        return f"{'、'.join(yes)}满足要求，立即买入！其他不符合要求"
    return "无个股满足速查涨幅门槛；其他不符合要求"


def _brief_watch_pack_line(
    wp: dict,
    code_map: Dict[str, tuple],
    ks: Optional[float],
    sh_price: Optional[float],
) -> str:
    title = (wp.get("title") or "未命名").strip()
    pending: List[str] = []
    for s in wp.get("stocks") or []:
        rk = s.get("rank")
        code = s.get("ts_code") or ""
        name = s.get("name") or ""
        imm = format_immediate_buy_watch(rk, wp, code_map, ks, sh_price)
        if imm.startswith("待定"):
            pending.append(name)
    if pending:
        return (
            f"\t{title}：{'、'.join(pending)}满足包内数据项，可参与（分时确认）！"
            "其他不符合要求"
        )
    return f"\t{title}：无满足要求；其他不符合要求"


def build_compact_brief(
    sh_line: Optional[tuple],
    same_period: Optional[Dict[str, Any]],
    concept_rows: List[Tuple[str, float]],
    industry_rows: List[Tuple[str, float]],
    vamp: str,
    top10_src: str,
    top10: List[Dict[str, Any]],
    up_n: int,
    dn_n: int,
    zt_n: int,
    n_pool: int,
    mood: str,
    p1s: List[tuple],
    p2s: List[tuple],
    code_map: Dict[str, tuple],
    buy_map: Dict[str, Dict[str, Any]],
    packs: List[dict],
    ks: Optional[float],
    sh_price: Optional[float],
    promo: Optional[Dict[str, Any]] = None,
    top10_vol: Optional[Dict[str, Any]] = None,
) -> str:
    """口令式执行摘要（纯文本多行），与 build_markdown 共用同一套机械判定。"""
    if sh_line is not None:
        sh_pct = float(sh_line[3])
        line1 = f"1、大盘:上证{sh_pct:+.2f}%，"
    else:
        line1 = "1、大盘:上证—，"

    if same_period:
        pv = float(same_period["pct_vs_yesterday_same_bars"])
        if pv >= 0:
            line1 += f"放量{pv:+.2f}%"
        else:
            line1 += f"缩量{pv:+.2f}%"
    else:
        line1 += "同期量能—"

    seen = set()
    theme_names: List[str] = []
    for row_list in (concept_rows, industry_rows):
        for nm, _p in row_list:
            if nm and nm not in seen:
                seen.add(nm)
                theme_names.append(nm)
    theme = "、".join(theme_names) if theme_names else "—"
    src_hint = (
        "速查池内成交额排序"
        if top10_src == "speedcard"
        else "东财全市场成交额榜"
    )
    top5_hint = ""
    if top10:
        top5_hint = "；当前榜前列：" + "、".join(
            f"{it.get('f14', '?')}({float((it.get('f6') or 0)) / 1e8:.1f}亿)"
            for it in top10[:5]
        )
    tv_line = (
        format_top10_vol_line(top10_vol)
        if top10_vol
        else "全市场Top10同期成交额对比：—（未算出）"
    )
    line2 = (
        f"2、题材：{theme}居前；{vamp}（{src_hint}）。"
        f"{tv_line}；"
        f"若榜前列成交额集中，易有吸血效应，小盘股易被分流{top5_hint}。"
    )

    if "偏热" in mood:
        mood_word = "好"
    elif "偏冷" in mood:
        mood_word = "差"
    else:
        mood_word = "中性"
    line3 = (
        f"3、短线：短线情绪{mood_word}（{format_promotion_line(promo)}；"
        f"速查池近似涨停{zt_n}只，红{up_n}/绿{dn_n}；定性{mood}）"
    )

    p1_line = _brief_priority_line(p1s, code_map, buy_map)
    p2_line = _brief_priority_line(p2s, code_map, buy_map)
    line4 = f"4、第一优先：{p1_line}\n第二优先：{p2_line}"

    watch_lines: List[str] = ["5、盘中观察各包各股"]
    if packs:
        for wp in packs:
            watch_lines.append(_brief_watch_pack_line(wp, code_map, ks, sh_price))
    else:
        watch_lines.append("\t（速查未解析观察包）")

    return "\n".join([line1, line2, line3, line4, "\n".join(watch_lines)])


def build_markdown(
    card_path: Optional[str],
    snap: Dict[str, Any],
    yesterday_yi: Optional[float],
    today_sh_yi: Optional[float],
    buy_map: Dict[str, Dict[str, Any]],
    same_period: Optional[Dict[str, Any]] = None,
    embed_brief: bool = True,
    return_brief_only: bool = False,
    promo: Optional[Dict[str, Any]] = None,
    top10_vol: Optional[Dict[str, Any]] = None,
) -> str:
    struct = snap["struct"] or {}
    indices = snap["indices"] or []
    rows = snap["stock_rows"] or []
    top10 = snap["top10"]
    top10_src = snap.get("top10_source") or "speedcard"
    sh_ext = snap.get("sh_extended") or {}
    path = snap.get("path") or ""
    code_map = rows_to_code_map(rows)

    sh_line = next((x for x in indices if x[1] == "000001"), None)
    cyb = next((x for x in indices if x[1] == "399006"), None)
    sz = next((x for x in indices if x[1] == "399001"), None)
    sh_price = float(sh_line[2]) if sh_line else None
    ks = struct.get("key_support")

    vamp = build_vamp_note(snap["stock_map"], top10, top10_source=top10_src)
    p1s = struct.get("p1_chain") or []
    p2s = struct.get("p2_chain") or []
    p1_names = "、".join(x[1] for x in p1s[:3]) or "—"
    p2_names = "、".join(x[1] for x in p2s[:3]) or "—"
    top10_src_label = "速查池内排序" if top10_src == "speedcard" else "东财沪深A股"

    up_n = sum(1 for r in rows if len(r) > 3 and float(r[3]) > 0)
    dn_n = sum(1 for r in rows if len(r) > 3 and float(r[3]) < 0)
    flat_n = len(rows) - up_n - dn_n
    zt_n = sum(1 for r in rows if len(r) > 3 and float(r[3]) >= 9.45)
    n_pool = len(rows)
    if n_pool > 0:
        if dn_n >= n_pool * 0.55:
            mood = "偏冷（绿盘占优）"
        elif up_n >= n_pool * 0.55:
            mood = "偏热（红盘占优）"
        else:
            mood = "中性（分化）"
    else:
        mood = "—"

    concept_rows = fetch_em_board_top_rows("m:90+t:3", 8)
    industry_rows = fetch_em_board_top_rows("m:90+t:2", 8)
    packs = struct.get("watch_packages") or []

    brief_text = build_compact_brief(
        sh_line,
        same_period,
        concept_rows,
        industry_rows,
        vamp,
        top10_src,
        top10,
        up_n,
        dn_n,
        zt_n,
        n_pool,
        mood,
        p1s,
        p2s,
        code_map,
        buy_map,
        packs,
        ks,
        sh_price,
        promo=promo,
        top10_vol=top10_vol,
    )

    if return_brief_only:
        return brief_text

    lines: List[str] = []
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines.append("# 盘中监控报告（用户结构五段式）")
    lines.append("")
    lines.append(f"> 生成时间：{now} ｜ 速查文件：`{path}`")
    lines.append(
        "> **风险提示**：以下为行情快照与速查条文机械对照，不构成投资建议；"
        "盘中价不等于 9:25 竞价结果。"
    )
    lines.append("")
    if embed_brief:
        lines.append("## 执行摘要（口令）")
        lines.append("")
        lines.append(brief_text)
        lines.append("")

    # 1 大盘（表格 + 同期量能）
    lines.append("## 1、大盘情况")
    lines.append("")
    lines.append("### 主要指数")
    lines.append("| 指数 | 点位 | 涨跌幅 |")
    lines.append("|------|------|--------|")
    if sh_line:
        lines.append(f"| 上证指数 | {sh_line[2]:.2f} | {sh_line[3]:+.2f}% |")
    else:
        lines.append("| 上证指数 | — | — |")
    if sz:
        lines.append(f"| 深证成指 | {sz[2]:.2f} | {sz[3]:+.2f}% |")
    else:
        lines.append("| 深证成指 | — | — |")
    if cyb:
        lines.append(f"| 创业板指 | {cyb[2]:.2f} | {cyb[3]:+.2f}% |")
    else:
        lines.append("| 创业板指 | — | — |")

    if ks is not None and sh_price is not None:
        lines.append("")
        lines.append(
            f"- **速查关键位**：{ks:.2f} ｜ 现价相对关键位：**{'上方' if sh_price >= ks else '下方'}**"
        )

    lines.append("")
    lines.append("### 量能：相对昨日全日 + 前一天「同期」")
    lines.append(
        "- **昨日全日（复盘表）**："
        + (
            f"约 **{yesterday_yi:.2f} 亿**（来源：依据日复盘表「两市成交额」行；与生成脚本一致，实为上证成交额口径）"
            if yesterday_yi is not None
            else "**未读到** 对应日期的 `每日复盘表_*.md`"
        )
    )
    if today_sh_yi is not None:
        lines.append(
            f"- **今日上证累计（东财）**：约 **{today_sh_yi:.2f} 亿**（当日截至快照的累计成交额）"
        )
    elif isinstance(sh_ext, dict) and sh_ext.get("amount_yuan"):
        ty = float(sh_ext["amount_yuan"]) / 1e8
        lines.append(f"- **今日上证累计（腾讯）**：约 **{ty:.2f} 亿**（备用数据源）")
    else:
        lines.append("- **今日累计成交额**：未能从东财/腾讯取得")

    if yesterday_yi is not None and today_sh_yi is not None and yesterday_yi > 0:
        ratio = today_sh_yi / yesterday_yi
        if ratio >= 1.05:
            tag = "偏放量（相对昨日全日）"
        elif ratio <= 0.95:
            tag = "偏缩量（相对昨日全日）"
        else:
            tag = "与昨日全日接近"
        lines.append(
            f"- **对比结论（近似）**：今日上证累计 / 昨日复盘表数值 ≈ **{ratio*100:.1f}%** → {tag}。"
            "**注意**：若当前未收盘，该比例会随时间上升；并非「同一时刻」精确可比。"
        )
    else:
        lines.append(
            "- **对比结论**：数据不全，无法给出相对昨日全日的放量/缩量判断。"
        )

    lines.append("")
    lines.append("**前一天「同期」缩量/放量**（东财/新浪 5 分钟 K 同根数对比；与短线侠类工具同义）")
    lines.append(
        "- **说明**：此处为程序可复现的「同根数累计」相对昨日；与 [短线侠](https://duanxianxia.com/) 等前端曲线数据源可能不同。"
    )
    if same_period:
        pv = same_period["pct_vs_yesterday_same_bars"]
        tag = "偏放量" if pv >= 1.0 else ("偏缩量" if pv <= -1.0 else "接近平量")
        unit = same_period.get("amount_unit") or "亿"
        sn = same_period.get("source_note") or ""
        lines.append(
            f"- **昨日交易日**：{same_period['yesterday_ymd']} ｜ **今日**：{same_period['today_ymd']} ｜ "
            f"已对齐 **{same_period['n_bars']}** 根 5 分钟 K（自开盘起同根数）。"
        )
        lines.append(f"- **数据源**：{sn}")
        lines.append(
            f"- **累计（上证）**：今日约 **{same_period['amt_today_yi']:.0f} {unit}** ，"
            f"昨日同期约 **{same_period['amt_yest_yi']:.0f} {unit}** 。"
        )
        lines.append(
            f"- **相对昨日同期**：约 **{pv:+.2f}%** → **{tag}**（(今日/昨日同期−1)×100%）。"
        )
    else:
        lines.append(
            "- **相对昨日同期**：当前无法从东财 K 线拉取（非交易日、接口失败或根数为 0）。"
        )

    lines.append("")
    lines.append("## 2、题材情况")

    lines.append("")
    lines.append("### 2.1 哪个板块涨得好（全市场 · 东财涨幅榜）")
    if concept_rows:
        lines.append("| 序号 | 概念板块 | 涨跌幅 |")
        lines.append("|:---:|----------|--------|")
        for i, (nm, p) in enumerate(concept_rows, 1):
            lines.append(f"| {i} | {nm} | {p:+.2f}% |")
    else:
        lines.append("（概念板块数据暂不可用）")
    lines.append("")
    if industry_rows:
        lines.append("| 序号 | 行业板块 | 涨跌幅 |")
        lines.append("|:---:|----------|--------|")
        for i, (nm, p) in enumerate(industry_rows, 1):
            lines.append(f"| {i} | {nm} | {p:+.2f}% |")
    else:
        lines.append("（行业板块数据暂不可用）")

    lines.append("")
    lines.append("### 2.2 吸血效应")
    lines.append("| 项目 | 内容 |")
    lines.append("|------|------|")
    for tvr in top10_vol_md_rows(top10_vol):
        lines.append(tvr)
    lines.append(f"| 吸血/集中度结论 | {vamp} |")
    lines.append(f"| 成交额榜来源 | {top10_src_label} |")
    if top10:
        tline = "；".join(
            f"{it.get('f14','?')}({float((it.get('f6') or 0))/1e8:.1f}亿)"
            for it in top10[:5]
        )
        lines.append(f"| 当前榜前列（至多 5） | {tline} |")

    lines.append("")
    lines.append("### 2.3 短线情绪（全市场晋级 + 速查池内）")
    lines.append("| 指标 | 数值 | 备注 |")
    lines.append("|------|------|------|")
    for pr in promotion_md_rows(promo):
        lines.append(pr)
    lines.append(f"| 红盘家数 | {up_n} | 仅速查池 |")
    lines.append(f"| 绿盘家数 | {dn_n} | 仅速查池 |")
    lines.append(f"| 平盘家数 | {flat_n} | |")
    lines.append(
        f"| 近似涨停家数（≥9.45%） | {zt_n} | 非全市场涨停家数 |"
    )
    lines.append(f"| 情绪定性 | **{mood}** | 按池内红绿占比粗判 |")
    lines.append("")
    lines.append(
        f"**与速查主线关系**：第一优先相关 **{p1_names}**；第二优先相关 **{p2_names}**。"
        "（全市场领涨板块与速查主线可能不一致，以你交易预案为准。）"
    )

    def table_block(title: str, chain: List[tuple]):
        lines.append("")
        lines.append(title)
        lines.append("")
        lines.append(
            "| 标的 | 涨跌 | 一句话 | 满足条件可立即买入（机械对照速查涨幅门槛） |"
        )
        lines.append("|------|------|--------|--------------------------------------------|")
        for tag, name, code in chain:
            pct = pct_for_code(code, code_map)
            meta = buy_map.get(code, {})
            role = meta.get("role") or f"顺位龙{tag}"
            summ = one_line_summary(name, pct, role)
            imm = format_immediate_buy_yes_no(pct, meta.get("min_pct"))
            lines.append(
                f"| **{name}**({code}) | {fmt_pct(pct)} | {summ} | {imm} |"
            )

    table_block("## 3、第一优先各股情况", p1s)
    table_block("## 4、第二优先各股情况", p2s)

    lines.append("")
    lines.append("## 5、盘中观察各包各股情况")
    if not packs:
        lines.append("")
        lines.append("（速查中未解析到「#### 观察包」表格）")
    else:
        lines.append("")
        lines.append("### 5.1 各包「板块够强」数据项汇总（脚本可算部分）")
        lines.append("")
        lines.append(
            "| 观察包 | 条件二（包内≥2只≥+2%） | 条件三（近涨停+扩散） | 上证 vs 速查关键位 | 数据项摘要 |"
        )
        lines.append(
            "|--------|---------------------------|------------------------|-------------------|------------|"
        )
        for wp in packs:
            title = (wp.get("title") or "未命名").strip()
            c2, c3, detail = pack_strong_signals(wp, code_map)
            broken = ks is not None and sh_price is not None and sh_price < ks
            if ks is not None and sh_price is not None:
                ks_cell = f"低于{ks:.2f}" if broken else f"未破{ks:.2f}"
            else:
                ks_cell = "—"
            lines.append(
                f"| {title} | {'满足' if c2 else '不满足'} | {'满足' if c3 else '不满足'} | {ks_cell} | {detail} |"
            )
        lines.append("")
        lines.append(
            "> 说明：速查「板块够强」另含 **概念板块涨幅** 须在行情软件中核对；上表仅为包内个股涨跌幅可计算项。"
        )
        lines.append("")
        lines.append("### 5.2 各包个股一览（总表）")
        lines.append("")
        lines.append(
            "| 观察包 | 顺位 | 标的 | 涨跌 | 一句话 | 满足条件可立即买入（包级+顺位+快照） |"
        )
        lines.append(
            "|--------|:---:|------|------|--------|----------------------------------------|"
        )
        for wp in packs:
            title = (wp.get("title") or "未命名").strip()
            for s in wp.get("stocks") or []:
                code = s.get("ts_code") or ""
                name = s.get("name") or ""
                rk = s.get("rank")
                role = (s.get("role") or "").strip()
                pct = pct_for_code(code, code_map)
                summ = one_line_summary(name, pct, role or "观察")
                immediate = format_immediate_buy_watch(rk, wp, code_map, ks, sh_price)
                lines.append(
                    f"| {title} | {rk} | **{name}**({code}) | {fmt_pct(pct)} | {summ} | {immediate} |"
                )

        lines.append("")
        lines.append("### 5.3 分观察包 · 各股逐只（每包一张表，代码/名称分列）")
        lines.append("")
        lines.append(
            "以下为**每个观察包内**的**全部**成分股，**一股一行**，不合并、不省略。"
        )
        for wp in packs:
            title = (wp.get("title") or "未命名").strip()
            stocks = wp.get("stocks") or []
            n_stocks = len(stocks)
            lines.append("")
            lines.append(f"#### 观察包「{title}」— 共 **{n_stocks}** 只股")
            lines.append("")
            lines.append(
                "| 顺位 | 股票代码 | 股票名称 | 涨跌幅 | 一句话 | 满足条件可立即买入 |"
            )
            lines.append(
                "|:---:|----------|----------|--------|--------|------------------------|"
            )
            for s in stocks:
                code = s.get("ts_code") or ""
                name = s.get("name") or ""
                rk = s.get("rank")
                role = (s.get("role") or "").strip()
                pct = pct_for_code(code, code_map)
                summ = one_line_summary(name, pct, role or "观察")
                immediate = format_immediate_buy_watch(rk, wp, code_map, ks, sh_price)
                code_cell = f"`{code}`" if code else "—"
                lines.append(
                    f"| {rk} | {code_cell} | {name} | {fmt_pct(pct)} | {summ} | {immediate} |"
                )

        lines.append("")
        lines.append("### 5.4 各股流水清单（观察包内全部个股 · 一股一条）")
        lines.append("")
        lines.append(
            "以下为**观察包内**每只股票的**纯文本清单**，便于逐只核对（格式：`[包名-顺位] 代码 名称 涨跌`）。"
        )
        lines.append("")
        n_all = 0
        for wp in packs:
            title = (wp.get("title") or "未命名").strip()
            for s in wp.get("stocks") or []:
                n_all += 1
                code = s.get("ts_code") or ""
                name = s.get("name") or ""
                rk = s.get("rank")
                role = (s.get("role") or "").strip()
                pct = pct_for_code(code, code_map)
                summ = one_line_summary(name, pct, role or "观察")
                immediate = format_immediate_buy_watch(rk, wp, code_map, ks, sh_price)
                lines.append(
                    f"{n_all}. **[{title}-{rk}]** `{code}` **{name}** 涨跌 {fmt_pct(pct)} ｜ {summ} ｜ **立即买入：{immediate}**"
                )
        lines.append("")
        lines.append(f"**合计**：观察包内共 **{n_all}** 条个股记录（逐包逐顺位）。")

    lines.append("")
    lines.append("---")
    lines.append("*报告由 `realtime_monitor_report.py` 生成。*")
    lines.append("")
    return "\n".join(lines)


def main():
    _clear_proxy_env()
    ap = argparse.ArgumentParser(description="盘中监控五段式 Markdown 报告")
    ap.add_argument(
        "--card",
        default=None,
        metavar="PATH",
        help="速查 md 路径（默认与 realtime_engine 相同规则）",
    )
    ap.add_argument(
        "--http-only",
        action="store_true",
        help="与引擎一致：不用 Playwright",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="写入 Markdown 文件路径（默认不写 stdout）",
    )
    ap.add_argument(
        "--compact",
        action="store_true",
        help="仅向 stdout 输出口令式执行摘要（可与 -o 同用：文件仍为完整 Markdown）",
    )
    ap.add_argument(
        "--no-brief",
        action="store_true",
        help="完整 Markdown 中不嵌入「执行摘要（口令）」区块",
    )
    args = ap.parse_args()
    base = str(REVIEW_DIR)
    card_path = args.card
    use_pw = not args.http_only
    snap = gather_snapshot(card_path=card_path, use_playwright=use_pw)
    if not snap:
        print("无法获取快照：请检查速查文件是否存在且可解析。", file=sys.stderr)
        sys.exit(1)

    _, _, path, _ = parse_card(override_path=card_path)
    content = ""
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    review_date = parse_review_basis_date(content)
    yesterday_yi = None
    if review_date:
        yesterday_yi, _rp = read_review_turnover_yi(review_date, base)

    today_str = time.strftime("%Y-%m-%d")
    same_period: Optional[Dict[str, Any]] = None
    y_trade = review_date
    if not y_trade:
        d = _dt.date.today() - _dt.timedelta(days=1)
        while d.weekday() >= 5:
            d -= _dt.timedelta(days=1)
        y_trade = d.strftime("%Y-%m-%d")
    if y_trade and y_trade != today_str:
        same_period = compute_same_period_5min_amount_ratio(y_trade, today_str)

    today_sh_yi = fetch_em_sh_amount_yi()
    buy_map = parse_buy_condition_rows(content)

    promo = fetch_promotion_rates()
    pro_ts = get_tushare_pro()
    top10_vol = None
    if y_trade and y_trade != today_str:
        top10_vol = compute_top10_5m_volume_compare(
            y_trade, today_str, pro=pro_ts
        )

    embed_brief = not args.no_brief
    md = build_markdown(
        card_path,
        snap,
        yesterday_yi,
        today_sh_yi,
        buy_map,
        same_period=same_period,
        embed_brief=embed_brief,
        return_brief_only=False,
        promo=promo,
        top10_vol=top10_vol,
    )

    if args.output:
        out_path = os.path.abspath(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(out_path)

    if args.compact:
        brief = build_markdown(
            card_path,
            snap,
            yesterday_yi,
            today_sh_yi,
            buy_map,
            same_period=same_period,
            embed_brief=False,
            return_brief_only=True,
            promo=promo,
            top10_vol=top10_vol,
        )
        try:
            sys.stdout.buffer.write((brief + "\n").encode("utf-8", errors="replace"))
        except (AttributeError, OSError, ValueError):
            print(brief)
    elif not args.output:
        try:
            sys.stdout.buffer.write(md.encode("utf-8", errors="replace"))
        except (AttributeError, OSError, ValueError):
            print(md, end="")


if __name__ == "__main__":
    main()
