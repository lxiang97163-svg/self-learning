# -*- coding: utf-8 -*-
"""
实时监控：腾讯 qt.gtimg 拉指数/个股；成交额榜单默认用**速查池内**腾讯成交额排序（字段35），
不依赖东财（适合东财 API/IP 被 ban）。

解析当日 `速查_YYYY-MM-DD.md`：第一/第二优先顺位表、`#### 观察包…` 盘中观察包；
日志中输出「上证 vs 关键支撑」、各包「板块够强」可对齐项 ②③、顺位 1～3 涨幅。

环境变量 REALTIME_USE_EM_TOP10=1 时额外尝试东财 clist 全市场前十；失败则仍回退池内排序。

循环：交易时段每分钟；单次：python realtime_engine.py --once
Playwright 仅用于拉 qt.gtimg（可选）；可用 --http-only 全部 requests。
"""
import argparse
import os
import random
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests

from _paths import LOGS_DIR, REVIEW_DIR

try:
    from playwright.sync_api import sync_playwright

    _HAS_PW = True
except ImportError:
    _HAS_PW = False

# 与常见桌面 Chrome 接近，避免部分行情接口对非浏览器 UA 限流
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_EM_HEADERS = {
    "User-Agent": _DEFAULT_UA,
    "Referer": "https://quote.eastmoney.com/",
}
_EM_CLIST = "http://push2.eastmoney.com/api/qt/clist/get"
_EM_CLIST_DELAY = "http://push2delay.eastmoney.com/api/qt/clist/get"

# 无当日速查卡时回退（与本工作区 skill 约定一致）
_CARD_FALLBACK = "速查_2026-03-28.md"

# 速查正文中的上证关键支撑（用于日志提示，与 parse_key_support 一致）
_DEFAULT_KEY_SUPPORT = 3794.68


def _clear_proxy_env():
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "all_proxy", "ALL_PROXY"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"


def _qq_parse_index_line(line: str):
    if "~" not in line or '="' not in line:
        return None
    inner = line.split('="', 1)[1].split('"', 1)[0]
    p = inner.split("~")
    if len(p) < 6:
        return None
    try:
        name, code = p[1], p[2]
        price = float(p[3])
        pct = float(p[5])
    except (ValueError, IndexError):
        return None
    return name, code, price, pct


def _qq_parse_stock_line(line: str):
    """返回 (名称, 代码, 现价, 涨跌幅%, 成交额元或 None)。成交额来自字段35 现价/量/额。"""
    if "~" not in line or '="' not in line:
        return None
    inner = line.split('="', 1)[1].split('"', 1)[0]
    p = inner.split("~")
    if len(p) < 6:
        return None
    try:
        name, code = p[1], p[2]
        cur = float(p[3])
        # 腾讯个股：p[4]=昨收 p[5]=今开；误用 p[5] 会把涨跌算反
        pre = float(p[4])
        pct = (cur / pre - 1.0) * 100.0 if pre else 0.0
    except (ValueError, IndexError):
        return None
    amt_yuan = None
    if len(p) > 35 and p[35]:
        parts = p[35].split("/")
        if len(parts) >= 3:
            try:
                amt_yuan = float(parts[2])
            except ValueError:
                pass
    return name, code, cur, pct, amt_yuan


def _fetch_url_text(url: str, api_request=None) -> str:
    """api_request: Playwright APIRequestContext；为 None 时用 requests。"""
    if api_request is not None:
        resp = api_request.get(url, timeout=15_000)
        if not resp.ok:
            raise RuntimeError(f"qt.gtimg 请求失败 HTTP {resp.status} {url[:80]}")
        return resp.text()
    r = requests.get(url, timeout=12, proxies={"http": None, "https": None})
    r.raise_for_status()
    return r.text


def get_indices(api_request=None):
    url = "http://qt.gtimg.cn/q=s_sh000001,s_sz399001,s_sz399006"
    text = _fetch_url_text(url, api_request)
    out = []
    for line in text.split(";"):
        x = _qq_parse_index_line(line)
        if x:
            out.append(x)
    return out


def parse_sh000001_extended(api_request=None) -> Optional[dict]:
    """
    上证指数完整行情：现价、昨收、涨跌%、成交额（元，来自 ~ 字段35 第三段）。
    成交额口径与交易所披露可能不一致，仅作监控参考。
    """
    text = _fetch_url_text("http://qt.gtimg.cn/q=sh000001", api_request)
    for line in text.split(";"):
        if "~" not in line or '="' not in line:
            continue
        inner = line.split('="', 1)[1].split('"', 1)[0]
        p = inner.split("~")
        if len(p) < 36:
            continue
        try:
            name, code = p[1], p[2]
            cur = float(p[3])
            pre = float(p[4])
            pct = float(p[32]) if len(p) > 32 and p[32] else (
                (cur / pre - 1.0) * 100.0 if pre else 0.0
            )
            amt_yuan = None
            if len(p) > 35 and p[35] and "/" in p[35]:
                parts = p[35].split("/")
                if len(parts) >= 3:
                    amt_yuan = float(parts[2])
        except (ValueError, IndexError):
            continue
        return {
            "name": name,
            "code": code,
            "price": cur,
            "pre_close": pre,
            "pct": pct,
            "amount_yuan": amt_yuan,
        }
    return None


def gather_snapshot(
    card_path: Optional[str] = None, use_playwright: bool = False
) -> Optional[Dict[str, object]]:
    """
    拉取一次速查池行情 + 结构体 + 池内成交额前十，供结构化报告使用。
    use_playwright=True 时用 Playwright 请求（与 run_once 一致）。
    """
    stock_map, sectors, path, struct = parse_card(override_path=card_path)
    if not stock_map:
        return None
    api_request = None
    if use_playwright and _HAS_PW:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=_DEFAULT_UA)
                api_request = ctx.request
                indices = get_indices(api_request)
                rows = fetch_stocks(stock_map, api_request)
            finally:
                browser.close()
    else:
        if use_playwright and not _HAS_PW:
            pass
        indices = get_indices(None)
        rows = fetch_stocks(stock_map, None)
        api_request = None
    use_em = os.environ.get("REALTIME_USE_EM_TOP10", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    top10: Optional[List[dict]] = None
    source = "speedcard"
    if use_em:
        top10 = fetch_amount_top10_em()
        if top10:
            source = "em"
    if not top10:
        top10 = speedcard_rows_to_top10_dicts(rows)
        if top10:
            source = "speedcard"
    # 与 run_once 一致：requests 拉取即可，避免 Playwright 关闭后仍用已失效的 context
    sh_ext = parse_sh000001_extended(None)
    return {
        "stock_map": stock_map,
        "sectors": sectors,
        "struct": struct,
        "path": path,
        "indices": indices,
        "stock_rows": rows,
        "top10": top10,
        "top10_source": source,
        "sh_extended": sh_ext,
    }


def gtimg_codes_from_card(stock_map):
    codes = []
    for c in stock_map.keys():
        num = c.split(".")[0]
        if num.startswith("6"):
            codes.append(f"sh{num}")
        else:
            codes.append(f"sz{num}")
    return codes


def fetch_stocks(stock_map, api_request=None):
    if not stock_map:
        return []
    url = "http://qt.gtimg.cn/q=" + ",".join(gtimg_codes_from_card(stock_map))
    text = _fetch_url_text(url, api_request)
    rows = []
    for line in text.split(";"):
        x = _qq_parse_stock_line(line)
        if x:
            rows.append(x)
    return rows


def speedcard_rows_to_top10_dicts(stock_rows) -> List[dict]:
    """速查池内按成交额降序，最多 10 条（腾讯 amt，非全市场榜单）。"""
    ranked = []
    for r in stock_rows:
        if len(r) < 5:
            continue
        name, code, _cur, pct, amt = r
        if amt is None or amt <= 0:
            continue
        ranked.append(
            {
                "f12": code,
                "f14": name,
                "f6": amt,
                "f3": pct,
            }
        )
    ranked.sort(key=lambda d: d["f6"], reverse=True)
    return ranked[:10]


# 兼容 **名**(002990.SZ) 与 **名**(`002990.SZ`) 两种速查写法
_TS_PAIR = re.compile(r"\*\*(.+?)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)")


def parse_key_support(content: str) -> float:
    """从速查正文提取上证关键支撑，如 **3794.68** 或 上证未破 **3871.30**。"""
    m0 = re.search(
        r"(?:上证|指数|关键|支撑|守住|跌破|未破)[^\n]{0,100}?\*?\*?(\d{4}\.\d{2})\*?\*?",
        content,
    )
    if m0:
        try:
            v = float(m0.group(1))
            if 3000 < v < 5000:
                return v
        except ValueError:
            pass
    m = re.search(r"(?:守住|跌破|破)\s*\*?\*?([\d.]{4,})\*?\*?", content)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m2 = re.search(r"([\d]{4}\.[\d]{2})", content)
    if m2:
        try:
            v = float(m2.group(1))
            if 3000 < v < 5000:
                return v
        except ValueError:
            pass
    return _DEFAULT_KEY_SUPPORT


def _extract_block(content: str, start_pat: str, end_pats: tuple) -> str:
    m = re.search(start_pat, content, re.DOTALL)
    if not m:
        return ""
    start = m.end()
    rest = content[start:]
    end = len(rest)
    for ep in end_pats:
        em = re.search(ep, rest)
        if em:
            end = min(end, em.start())
    return rest[:end]


def _parse_dragon_chain(block: str) -> List[tuple]:
    """顺位表：| 龙一 | **名**(代码) |"""
    rows = []
    for line in block.splitlines():
        m = re.match(
            r"\|\s*龙([一二三四五])\s*\|\s*\*\*(.+?)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)\s*\|",
            line.strip(),
        )
        if m:
            rows.append((m.group(1), m.group(2).strip(), f"{m.group(3)}.{m.group(4)}"))
    return rows


def _extract_priority_sections(content: str, order_pattern: str) -> List[Tuple[str, str]]:
    """
    Find all '### ✅ 第X优先 ...' sections matching order_pattern.
    Returns [(title, block_text), ...] where each block_text ends at the next
    ##/### heading or --- separator; #### sub-headings do not split the block.
    """
    header_re = re.compile(rf"###\s*✅\s*{order_pattern}[^\n]*\n")
    boundary_re = re.compile(r"\n(?:---|\#{2,3}\s)")
    results = []
    for m in header_re.finditer(content):
        raw = m.group(0).strip()
        title_m = re.match(r"###\s*✅\s*(.+)", raw)
        title = title_m.group(1).strip() if title_m else raw
        start = m.end()
        end = len(content)
        bm = boundary_re.search(content, start)
        if bm:
            end = bm.start()
        results.append((title, content[start:end]))
    return results


def _extract_chain_health(block: str) -> List[Dict]:
    """
    Extract health check conditions from a priority section block.

    Handles two formats:
    (1) Line:   龙二 **大中矿业** 竞价涨幅＞0%
    (2) Inline: ⚠️ **人工智能健康度**：申通＞0%；大胜达＞-3%；...
    """
    checks: List[Dict] = []
    seen: set = set()

    for cm in re.finditer(
        r"龙[一二三四五\d]+\s*\*\*([^*]+)\*\*(?:[^>＞\n]{0,40})[>＞]\s*([+-]?[\d.]+)%",
        block,
    ):
        name = cm.group(1).strip()
        if name not in seen:
            checks.append({"name": name, "threshold": float(cm.group(2))})
            seen.add(name)

    if not checks:
        for hm in re.finditer(r"⚠️[^\n]*健康度[^：:\n]*[：:]\s*([^\n]+)", block):
            inline = hm.group(1)
            for cm in re.finditer(
                r"([^\s；；，,>＞（(]{2,8})[>＞]\s*([+-]?[\d.]+)%",
                inline,
            ):
                name = cm.group(1).strip().lstrip("*")
                if len(name) >= 2 and name not in seen:
                    checks.append({"name": name, "threshold": float(cm.group(2))})
                    seen.add(name)

    return checks


def _parse_watch_packages(content: str) -> List[dict]:
    """解析 #### 观察包一：题材 下的表格（顺位 1～5）。"""
    packages = []
    for m in re.finditer(
        r"####\s*观察包[一二三四五六七八九十\d]*\s*[：:]\s*(.+?)(?:\r?\n)", content
    ):
        title = m.group(1).strip()
        start = m.end()
        nxt = content.find("\n####", start)
        if nxt == -1:
            nxt = content.find("\n### ", start)
        if nxt == -1:
            nxt = len(content)
        block = content[start:nxt]
        stocks = []
        for line in block.splitlines():
            pm = re.match(
                r"\|\s*[^|]+\s*\|\s*(\d+)\s*\|\s*\*\*(.+?)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)\s*\|\s*([^|]*)",
                line.strip(),
            )
            if pm:
                rank = int(pm.group(1))
                name = pm.group(2).strip()
                code = f"{pm.group(3)}.{pm.group(4)}"
                role = pm.group(5).strip()
                stocks.append({"rank": rank, "name": name, "ts_code": code, "role": role})
        if stocks:
            stocks.sort(key=lambda x: x["rank"])
            packages.append({"title": title, "stocks": stocks})
    return packages


def _parse_intraday_watch_table(content: str) -> List[dict]:
    """解析 ### 📡 盘中观察 多主题合表（题材 | 顺位 | **标的**(代码) | 角色...）。

    表格行格式示例：
      || 一带一路 | 1 | **中工国际**(002051.SZ) | 龙头 | □ | □ |
    首列为空，第二列是题材名，后续为顺位/标的/角色。
    """
    m_sec = re.search(r"###\s*(?:📡\s*)?盘中观察[^\n]*\n", content)
    if not m_sec:
        return []
    start = m_sec.end()
    end_m = re.search(r"\n###\s", content[start:])
    block = content[start: start + (end_m.start() if end_m else len(content) - start)]

    theme_stocks: Dict[str, List[dict]] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        # 表格行格式：| 一带一路 | 1 | **中工国际**(002051.SZ) | 龙头 | ...
        row_m = re.match(
            r"^\|\s*([^|]{2,12}?)\s*\|\s*(\d+)\s*\|\s*\*\*(.+?)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)\s*\|",
            line,
        )
        if not row_m:
            continue
        theme = row_m.group(1).strip()
        rank = int(row_m.group(2))
        name = row_m.group(3).strip()
        code = f"{row_m.group(4)}.{row_m.group(5)}"
        theme_stocks.setdefault(theme, []).append(
            {"rank": rank, "name": name, "ts_code": code, "role": ""}
        )

    packages = []
    for theme, stocks in theme_stocks.items():
        stocks.sort(key=lambda x: x["rank"])
        packages.append({"title": theme, "stocks": stocks})
    return packages


def _parse_watch_bullets(content: str) -> List[dict]:
    """解析 ### 👀 低吸候选 下的项目符号格式：
    - **题材名**：核心：**股票**(`code`)、**股票**(`code`)...
    """
    # 严格正则：名字内不允许出现 *，避免跨越多个 **...** 块
    _strict_pair = re.compile(r"\*\*([^*]+)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)")
    m_sec = re.search(r"###\s*👀[^\n]*\n", content)
    if not m_sec:
        return []
    start = m_sec.end()
    end_m = re.search(r"\n###\s", content[start:])
    block = content[start: start + (end_m.start() if end_m else len(content) - start)]
    packages = []
    for line in block.splitlines():
        bm = re.match(r"^-\s*\*\*([^*]+)\*\*[：:]", line)
        if not bm:
            continue
        title = bm.group(1).strip()
        # 从题材名结束位置往后找股票，避免题材名本身被捡入
        rest = line[bm.end():]
        stocks = []
        for mm in _strict_pair.finditer(rest):
            stocks.append({
                "rank": len(stocks) + 1,
                "name": mm.group(1).strip(),
                "ts_code": f"{mm.group(2)}.{mm.group(3)}",
                "role": "",
            })
        if stocks:
            packages.append({"title": title, "stocks": stocks})
    return packages


def _parse_intraday_sublines(content: str) -> List[dict]:
    """解析 ### 📡 盘中观察 下的 #### 支线X：题材 小节。
    表格格式：| 顺位 | 角色 | **名**(`code`) | 备注 |
    """
    m_sec = re.search(r"###\s*(?:📡\s*)?盘中观察[^\n]*\n", content)
    if not m_sec:
        return []
    start = m_sec.end()
    end_m = re.search(r"\n##\s", content[start:])
    block = content[start: start + (end_m.start() if end_m else len(content) - start)]
    packages = []
    for m in re.finditer(r"####\s*支线[^\n]+[：:]\s*([^\n]+)\n", block):
        title = m.group(1).strip()
        sub_start = m.end()
        sub_end_m = re.search(r"\n####\s", block[sub_start:])
        sub_block = block[sub_start: sub_start + (sub_end_m.start() if sub_end_m else len(block) - sub_start)]
        stocks = []
        for line in sub_block.splitlines():
            # 格式：| 顺位 | 角色 | **名**(`code`) | 备注 |
            pm = re.match(
                r"\|\s*(\d+)\s*\|\s*[^|]+\|\s*\*\*(.+?)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)\s*\|",
                line.strip(),
            )
            if pm:
                stocks.append({
                    "rank": int(pm.group(1)),
                    "name": pm.group(2).strip(),
                    "ts_code": f"{pm.group(3)}.{pm.group(4)}",
                    "role": "",
                })
        if stocks:
            packages.append({"title": title, "stocks": stocks})
    return packages


def parse_speedcard_structure(content: str) -> dict:
    """结构化速查：所有优先链 + 盘中观察包 + 全量代码（用于拉行情）。

    支持同一优先级别下多个小节（如两个「第一优先」——军工 + 商业航天）。
    p1_chains / p2_chains 为完整多链列表；p1_chain / p2_chain 指向首链，保持向后兼容。
    """
    p1_sections = _extract_priority_sections(content, "第一")
    p2_sections = _extract_priority_sections(content, "第二")

    def _to_chain_data(sections: List[Tuple[str, str]]) -> List[Dict]:
        result = []
        for title, block in sections:
            result.append({
                "title": title,
                "chain": _parse_dragon_chain(block),
                "health": _extract_chain_health(block),
            })
        return result

    p1_chains = _to_chain_data(p1_sections)
    p2_chains = _to_chain_data(p2_sections)
    p1_chain = p1_chains[0]["chain"] if p1_chains else []
    p2_chain = p2_chains[0]["chain"] if p2_chains else []

    # 合并各来源的低吸/盘中观察包
    watch_packages = (
        _parse_watch_packages(content)
        + _parse_intraday_watch_table(content)
        + _parse_watch_bullets(content)
        + _parse_intraday_sublines(content)
    )
    pairs = _TS_PAIR.findall(content)
    stock_map = {f"{c}.{m}": n.strip() for n, c, m in pairs}
    sectors = re.findall(r"### ✅ (.+?)(?:\r?\n|$)", content)
    sectors.extend(re.findall(r"### 👀 (.+?)(?:\r?\n|$)", content))
    sectors.extend(re.findall(r"### 📡 (.+?)(?:\r?\n|$)", content))
    key_support = parse_key_support(content)
    return {
        "stock_map": stock_map,
        "sectors": sectors,
        "p1_chain": p1_chain,       # backward compat: first chain
        "p2_chain": p2_chain,       # backward compat: first chain
        "p1_chains": p1_chains,     # all chains with per-chain health
        "p2_chains": p2_chains,
        "watch_packages": watch_packages,
        "key_support": key_support,
    }


def pack_strong_signals(pack: dict, code_to_row: dict) -> tuple:
    """
    与速查「板块够强」可对齐的数据项：
    ② 包内 ≥2 只较昨收 ≥+2%
    ③ ≥1 只近涨停(≥9.45%) 且 包内 ≥2 只 ≥+5%（体现「龙头+跟风」）
    返回 (cond2_ok, cond3_ok, detail_str)
    """
    stocks = pack.get("stocks") or []
    pcts = []
    for s in stocks:
        num = s["ts_code"].split(".")[0]
        row = code_to_row.get(num)
        pcts.append(float(row[3]) if row else None)
    valid = [p for p in pcts if p is not None]
    ge2 = sum(1 for p in valid if p >= 2.0)
    ge5 = sum(1 for p in valid if p >= 5.0)
    ge95 = sum(1 for p in valid if p >= 9.45)
    cond2_ok = ge2 >= 2
    cond3_ok = ge95 >= 1 and ge5 >= 2
    detail = f"≥+2%:{ge2}只 ≥+5%:{ge5}只 ≥+9.45%:{ge95}只"
    return cond2_ok, cond3_ok, detail


def parse_card(override_path: Optional[str] = None):
    """
    读取速查 md。优先顺序：
    1) 参数 override_path（--card）
    2) 环境变量 REALTIME_CARD_PATH
    3) 当日 速查_YYYY-MM-DD.md
    4) 回退 _CARD_FALLBACK
    """
    base = str(REVIEW_DIR)
    path: Optional[str] = None
    if override_path:
        path = os.path.abspath(override_path.strip())
        if not os.path.exists(path):
            return {}, [], path, {}
    else:
        env_p = os.environ.get("REALTIME_CARD_PATH", "").strip()
        path = os.path.abspath(env_p) if env_p else None
        if not path or not os.path.exists(path):
            date_str = time.strftime("%Y-%m-%d")
            path = os.path.join(base, f"速查_{date_str}.md")
        if not os.path.exists(path):
            fb = os.path.join(base, _CARD_FALLBACK)
            if os.path.exists(fb):
                path = fb
            else:
                return {}, [], path, {}
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    struct = parse_speedcard_structure(content)
    return struct["stock_map"], struct["sectors"], path, struct


def _signal(pct: float) -> str:
    if pct > 9.4:
        return "封板"
    if pct < -9.4:
        return "跌停熔断"
    return "震荡"


def fetch_amount_top10_em() -> Optional[List[dict]]:
    """沪深 A 股（非 ST）按当日成交额排序前十，东财 push2 clist。"""
    params = {
        "fid": "f6",
        "po": 1,
        "pz": 10,
        "pn": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fs": "m:0+t:6+f:!8",
        "fields": "f12,f14,f2,f3,f6",
        "ut": _EM_UT,
    }
    proxies = {"http": None, "https": None}
    for url in (_EM_CLIST, _EM_CLIST_DELAY):
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
            if diff:
                return diff[:10]
        except Exception:
            continue
    return None


def build_vamp_note(
    stock_map: dict, top10: Optional[List[dict]], top10_source: str = "em"
) -> str:
    """吸血/分流：东财全市场前十看重合度；池内腾讯榜看首位集中度。"""
    if not top10:
        return "吸血:成交额榜单暂无(无有效成交额字段)"
    if top10_source == "speedcard":
        t0 = top10[0]
        yi = float(t0["f6"]) / 1e8
        return (
            f"吸血:池内成交额首位{t0.get('f14','?')}"
            f"({yi:.1f}亿)·非全市场排名"
        )
    nums = {c.split(".")[0] for c in stock_map.keys()}
    hit = [it for it in top10 if str(it.get("f12", "")) in nums]
    n = len(hit)
    if n == 0:
        return "吸血:速查标的无重合全市场前十;偏题材或小票博弈"
    if n >= 2:
        return f"吸血:速查{n}只入全市场成交额前十,容量票分流明显"
    h0 = hit[0]
    return f"吸血:速查仅{h0.get('f14','?')}({h0.get('f12','')})在全市场前十"


def format_top10_block(top10: Optional[List[dict]], source: str = "em") -> list:
    if not top10:
        return ["  [成交额TOP10] 暂无数据"]
    if source == "em":
        header = "  [成交额TOP10 · 东财沪深A股]"
    else:
        header = "  [成交额TOP10 · 速查池内 · 腾讯成交额·非全市场]"
    out = [header]
    for i, it in enumerate(top10, 1):
        f6 = it.get("f6") or 0
        yi = f6 / 1e8 if isinstance(f6, (int, float)) else 0.0
        pct = it.get("f3", "--")
        if isinstance(pct, (int, float)):
            ps = f"{pct:+.2f}%"
        else:
            ps = str(pct)
        out.append(
            f"  - {i}. {it.get('f14', '--')}({it.get('f12', '')}) "
            f"额{yi:.1f}亿 {ps}"
        )
    return out


def build_log_text(
    indices,
    stock_rows,
    stock_map,
    sectors,
    vamp_note="吸血/题材数据暂缓",
    top10_lines=None,
    struct=None,
):
    ts = time.strftime("%H:%M:%S")
    sh_pct = 0.0
    sh_price = None
    idx_lines = []
    for name, code, price, pct in indices:
        idx_lines.append(f"  - {name}({code}) {price:.2f} {pct:+.2f}%")
        if code == "000001":
            sh_pct = pct
            sh_price = price
    lines = [
        f"[{ts}] 综合快照 | 上证 {sh_pct:+.2f}% | ({vamp_note})",
    ]
    if top10_lines:
        lines.extend(top10_lines)
    else:
        lines.append("  [成交额TOP10] 未写入")
    lines.extend(
        [
            "  [指数]",
            *idx_lines,
        ]
    )
    if struct and struct.get("key_support") is not None and sh_price is not None:
        ks = float(struct["key_support"])
        warn = "低于速查关键支撑" if sh_price < ks else "未破速查关键支撑"
        lines.append(f"  [上证 vs 速查支撑] 现价{sh_price:.2f} vs {ks:.2f} → {warn}")
    lines.append("  [题材板块（速查）]")
    for s in sectors:
        lines.append(f"  - {s.strip()}")
    code_to_row = {(r[1]): r for r in stock_rows}
    if struct:
        if struct.get("p1_chain"):
            lines.append("  [第一优先·顺位]")
            for _tag, nm, tc in struct["p1_chain"]:
                num = tc.split(".")[0]
                row = code_to_row.get(num)
                if row:
                    lines.append(
                        f"    - {nm}({num}) {float(row[3]):+.2f}% [{_signal(float(row[3]))}]"
                    )
                else:
                    lines.append(f"    - {nm}({num}) 无行情")
        if struct.get("p2_chain"):
            lines.append("  [第二优先·顺位]")
            for _tag, nm, tc in struct["p2_chain"]:
                num = tc.split(".")[0]
                row = code_to_row.get(num)
                if row:
                    lines.append(
                        f"    - {nm}({num}) {float(row[3]):+.2f}% [{_signal(float(row[3]))}]"
                    )
                else:
                    lines.append(f"    - {nm}({num}) 无行情")
        for wp in struct.get("watch_packages") or []:
            title = wp.get("title", "")
            c2, c3, det = pack_strong_signals(wp, code_to_row)
            lines.append(
                f"  [盘中观察·{title}] 自动项: {det} | ②{'Y' if c2 else 'N'} ③{'Y' if c3 else 'N'} "
                f"(②③均满足时还需在软件里看「概念板块当日涨跌幅」是否≥+0.8%或前1/3)"
            )
            if c2 and c3:
                lines.append(
                    f"    · 提示: ②③已齐，若板块指数也强 → 按速查顺位1→2→3做分时确认"
                )
            for s in wp.get("stocks") or []:
                if s["rank"] > 3:
                    continue
                num = s["ts_code"].split(".")[0]
                row = code_to_row.get(num)
                tag = f"顺位{s['rank']}·{s.get('role','')}"
                if row:
                    lines.append(
                        f"    - {tag} {s['name']}({num}) {float(row[3]):+.2f}% [{_signal(float(row[3]))}]"
                    )
                else:
                    lines.append(f"    - {tag} {s['name']}({num}) 无行情")
    lines.append("  [全池个股 — 与速查代码对齐]")
    for code_key, name_cn in stock_map.items():
        num = code_key.split(".")[0]
        row = code_to_row.get(num)
        if not row:
            lines.append(f"  - {name_cn}({num}): 无行情 [{code_key}]")
            continue
        pct = float(row[3])
        lines.append(f"  - {row[0]}({num}): {pct:+.2f}% [{_signal(pct)}]")
    return "\n".join(lines) + "\n"


def write_log(log_file: str, text: str):
    os.makedirs(os.path.dirname(os.path.abspath(log_file)) or ".", exist_ok=True)
    with open(log_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)


def _make_snapshot_text(indices, stock_rows, stock_map, sectors, struct=None) -> str:
    """东财可选；默认可速查池内腾讯成交额 TOP10。struct 来自 parse_card 第四项。"""
    use_em = os.environ.get("REALTIME_USE_EM_TOP10", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    top10: Optional[List[dict]] = None
    source = "speedcard"
    if use_em:
        top10 = fetch_amount_top10_em()
        if top10:
            source = "em"
    if not top10:
        top10 = speedcard_rows_to_top10_dicts(stock_rows)
        if top10:
            source = "speedcard"
    vamp = build_vamp_note(
        stock_map, top10, top10_source=source if top10 else "speedcard"
    )
    tlines = format_top10_block(top10, source=source if top10 else "speedcard")
    return build_log_text(
        indices,
        stock_rows,
        stock_map,
        sectors,
        vamp_note=vamp,
        top10_lines=tlines,
        struct=struct,
    )


def run_once(
    log_file: str, use_playwright: bool = True, card_path: Optional[str] = None
) -> str:
    stock_map, sectors, path, struct = parse_card(override_path=card_path)
    if not stock_map:
        msg = f"[{time.strftime('%H:%M:%S')}] 未找到当日速查卡: {path}\n"
        write_log(log_file, msg)
        return msg

    api_request = None
    if use_playwright and _HAS_PW:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=_DEFAULT_UA)
                api_request = ctx.request
                indices = get_indices(api_request)
                rows = fetch_stocks(stock_map, api_request)
            finally:
                browser.close()
    else:
        if use_playwright and not _HAS_PW:
            print(
                "提示: 未安装 playwright，已回退到 requests。"
                " 安装: pip install playwright && playwright install chromium",
                file=sys.stderr,
            )
        indices = get_indices(None)
        rows = fetch_stocks(stock_map, None)

    text = _make_snapshot_text(indices, rows, stock_map, sectors, struct=struct)
    write_log(log_file, text)
    return text


def monitor_loop(log_file: str, use_playwright: bool = True):
    """交易时段内复用同一 Chromium，避免每分钟冷启动浏览器。"""
    if use_playwright and _HAS_PW:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=_DEFAULT_UA)
                api_request = ctx.request
                while True:
                    try:
                        now = time.localtime()
                        t = now.tm_hour * 100 + now.tm_min
                        if t < 915 or t > 1505:
                            print(
                                f"当前时间 {time.strftime('%H:%M:%S')} 非交易时段，退出循环。"
                            )
                            break
                        stock_map, sectors, path, struct = parse_card(
                            override_path=os.environ.get("REALTIME_CARD_PATH")
                            or None
                        )
                        if not stock_map:
                            msg = (
                                f"[{time.strftime('%H:%M:%S')}] 未找到当日速查卡: {path}\n"
                            )
                            write_log(log_file, msg)
                            print(msg)
                            time.sleep(60 + random.uniform(1, 5))
                            continue
                        indices = get_indices(api_request)
                        rows = fetch_stocks(stock_map, api_request)
                        text = _make_snapshot_text(
                            indices, rows, stock_map, sectors, struct=struct
                        )
                        write_log(log_file, text)
                        print(text)
                    except Exception as e:
                        write_log(log_file, f"监控异常: {e!s}")
                        print(f"监控异常: {e}", file=sys.stderr)
                    time.sleep(60 + random.uniform(1, 5))
            finally:
                browser.close()
        return

    while True:
        try:
            now = time.localtime()
            t = now.tm_hour * 100 + now.tm_min
            if t < 915 or t > 1505:
                print(f"当前时间 {time.strftime('%H:%M:%S')} 非交易时段，退出循环。")
                break
            txt = run_once(log_file, use_playwright=False)
            print(txt)
        except Exception as e:
            write_log(log_file, f"监控异常: {e!s}")
            print(f"监控异常: {e}", file=sys.stderr)
        time.sleep(60 + random.uniform(1, 5))


def main():
    _clear_proxy_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="单次写入日志后退出（任意时段）")
    ap.add_argument(
        "--http-only",
        action="store_true",
        help="仅用 requests 拉取（不走 Playwright，便于对照调试）",
    )
    ap.add_argument(
        "--card",
        default=None,
        metavar="PATH",
        help="指定速查 md 路径（不依赖系统日期；测试/复盘用）",
    )
    args = ap.parse_args()
    log_file = os.path.join(str(LOGS_DIR), "realtime_monitor_log.txt")
    use_pw = not args.http_only
    if args.once:
        txt = run_once(
            log_file, use_playwright=use_pw, card_path=args.card
        )
        try:
            sys.stdout.buffer.write(txt.encode("utf-8", errors="replace"))
        except (AttributeError, OSError, ValueError):
            print(txt, end="")
        return
    monitor_loop(log_file, use_playwright=use_pw)


if __name__ == "__main__":
    main()
