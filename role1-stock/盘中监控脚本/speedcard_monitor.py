# -*- coding: utf-8 -*-
"""
速查早盘监控（9:15～9:50，每分钟一拍）

- 读取当日或指定的 `outputs/review/速查_YYYY-MM-DD.md`
- 拉腾讯行情 + 东财概念板块排名（粗）+ 可选 Tushare 竞价快照（9:25 后）
- 不启用 REALTIME_USE_EM_TOP10；不替代 verify_daily 盘后验证
- 输出单行中文：事实分句 + 结尾「结论——…」；追加写入 outputs/logs/

可选：正文末尾 `<!-- speedcard-meta: {"key_support":3871.30,"step0":{"huawei":["华为"],"rivals":["芯片","锂电"]}} -->`

用法（在 `self-learning/role1-stock/盘中监控脚本/` 下；与 `pipeline/`、`outputs/` 同级）：
  python3 speedcard_monitor.py                    # 今日速查，进入 9:15～9:50 循环
  python3 speedcard_monitor.py --once --card ...  # 立即跑一拍（调试）
  python3 speedcard_monitor.py --once --dump-meta # 写出 JSON 快照到 outputs/cache/
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 本目录（speedcard_data）+ 上级 pipeline（_paths、realtime_engine、verify_daily）
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.normpath(os.path.join(_SELF_DIR, "..", "pipeline"))
sys.path.insert(0, _PIPELINE_DIR)
sys.path.insert(0, _SELF_DIR)

from _paths import CACHE_DIR, LOGS_DIR, REVIEW_DIR

from realtime_engine import fetch_stocks, get_indices, parse_card

from speedcard_data import (
    fetch_concept_boards_sorted,
    find_board_pct,
    find_board_rank,
    merge_key_support,
    parse_embedded_meta,
)

_TS = re.compile(r"\*\*(.+?)\*\*\(([\d.]+)\.(SZ|SH)\)")

# 竞价数据缓存：9:25 后首次成功拉取即锁定，全天复用
_AUCTION_CACHE: Optional[Dict[str, Dict]] = None

# 与 append_speedcard_auction_snapshot.py 一致，用于解析附录表「竞价成交额(亿)」= 生成速查当日（昨）竞价
_AUC_SNAP_START = "<!-- speedcard-auction-snapshot:start -->"
_AUC_SNAP_END = "<!-- speedcard-auction-snapshot:end -->"


def parse_speedcard_prev_auction_bn(content: str) -> Dict[str, float]:
    """
    从速查文末附录「竞价快照」表解析每只股票的昨日竞价额（亿元）。
    表由 append_speedcard_auction_snapshot.py 写入；列为：序号|股票|ts_code|竞价成交额(亿)|…
    返回 {ts_code.upper(): 金额亿}；解析失败则返回空 dict。
    """
    out: Dict[str, float] = {}
    sec = ""
    if _AUC_SNAP_START in content and _AUC_SNAP_END in content:
        sec = content.split(_AUC_SNAP_START, 1)[1].split(_AUC_SNAP_END, 1)[0]
    elif "## 附录：速查标的·竞价快照" in content:
        tail = content.split("## 附录：速查标的·竞价快照", 1)[1]
        stop = tail.find("\n## ")
        sec = tail[:stop] if stop >= 0 else tail
    if not sec:
        return out
    for line in sec.splitlines():
        line = line.strip()
        if not line.startswith("|") or "序号" in line or line.startswith("|:---") or "---" in line[:8]:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        if not re.match(r"^\d+$", parts[1]):
            continue
        # | 1 | 名 | `002297.SZ` | 1.436 | ...
        code_raw = parts[3].strip().strip("`").strip()
        if not re.match(r"^\d{6}\.(SH|SZ|BJ)$", code_raw, re.I):
            continue
        tc = code_raw.upper()
        amt_s = parts[4].strip()
        if amt_s in ("—", "-", "", "N/A", "n/a"):
            continue
        try:
            v = float(amt_s)
            if v >= 0:
                out[tc] = v
        except ValueError:
            continue
    return out


@dataclass
class BSwitchSpec:
    """从「切换确认」列表解析；未识别则用速查常见默认。"""

    board_keywords: List[str]
    max_rank: Optional[int] = 8
    min_board_pct: Optional[float] = None  # 「或板块涨幅≥x%」
    or_rank_or_pct: bool = False  # True: 排名 OR 涨幅达标
    pool_need: int = 2
    pool_pct: float = 3.0
    third_manual: bool = True  # 封单/短线侠
    lead_keywords: List[str] = field(default_factory=list)  # 美能能源 竞价第三项
    lead_amt_ratio: Optional[float] = None
    lead_min_pct: Optional[float] = None


@dataclass
class BCandidate:
    title: str
    stocks: List[Dict[str, Any]]
    raw_switch_block: str = ""
    switch: BSwitchSpec = field(default_factory=BSwitchSpec)


@dataclass
class ParsedCard:
    content: str
    path: str
    struct: dict
    meta: Dict[str, Any]
    single_cap_note: str
    width_names: List[str]
    wind_name: str
    wind_code: str
    wind_prev_amount_bn: Optional[float]
    key_support: float
    b_candidates: List[BCandidate]
    exclude_codes: set


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_caps_first_line(content: str) -> str:
    m = re.search(r"单票上限[：:]\s*(\d)[～~]?(\d)?\s*成", content)
    if not m:
        return "2成"
    if m.group(2):
        return f"{m.group(1)}～{m.group(2)}成"
    return f"{m.group(1)}成"


def parse_step0_wind(content: str) -> Tuple[str, str]:
    # 在前2000字符内查找，避免匹配过多内容
    search_range = content[:2000]
    m = re.search(
        r"\*\*(.+?)\*\*\(([\d.]+)\.(SZ|SH)\)[^\n]{0,100}?封单",
        search_range
    )
    if m:
        return m.group(1).strip(), f"{m.group(2)}.{m.group(3)}"
    m2 = _TS.findall(content)
    for n, c, suf in m2:
        if "中恒" in n or "电气" in n:
            return n.strip(), f"{c}.{suf}"
    return "", ""


def parse_wind_prev_amount_bn(content: str) -> Optional[float]:
    """第零步表：封单额 vs 昨日X.XX亿。"""
    m = re.search(
        r"封单额\s+vs\s+昨日([\d.]+)亿|昨日([\d.]+)亿.*?封单|封单.*?昨日([\d.]+)亿",
        content,
    )
    if not m:
        m = re.search(r"昨日([\d.]+)亿", content[:2500])
    if not m:
        return None
    for g in m.groups():
        if g:
            try:
                return float(g)
            except ValueError:
                pass
    return None


def parse_width_tickers_from_step0(content: str) -> List[str]:
    m = re.search(r"除中恒外仍有(.+?)\s*宽度", content)
    if not m:
        return ["康盛股份", "宏和科技", "润建股份"]
    part = m.group(1)
    names = re.split(r"[、,/，]", part)
    return [x.strip() for x in names if x.strip()]


def _default_switch_for_title(title: str) -> BSwitchSpec:
    t = title.lower()
    if "芯片" in title or "半导体" in title:
        return BSwitchSpec(
            board_keywords=["芯片", "半导体"],
            max_rank=8,
            pool_need=2,
            pool_pct=3.0,
            third_manual=True,
        )
    if "美伊" in title or "天然气" in title or "油气" in title:
        return BSwitchSpec(
            board_keywords=["天然气", "油气", "页岩气", "燃气", "石油石化"],
            max_rank=10,
            min_board_pct=1.2,
            or_rank_or_pct=True,
            pool_need=2,
            pool_pct=2.5,
            third_manual=False,
            lead_keywords=["美能能源"],
            lead_amt_ratio=0.8,
            lead_min_pct=2.0,
        )
    return BSwitchSpec(board_keywords=[], max_rank=None, pool_need=2, pool_pct=3.0)


def parse_switch_spec(block: str, title: str) -> BSwitchSpec:
    spec = _default_switch_for_title(title)
    # 覆盖：前 N 名
    m = re.search(r"排名\*?\*?前(\d+)|前(\d+)\s*名|前(\d+)\]", block)
    if m:
        for g in m.groups():
            if g:
                spec.max_rank = int(g)
                break
    m2 = re.search(
        r"≥\s*(\d+)\s*只.*?≥\+([\d.]+)%|题材内.*?≥(\d+)\s*只.*?≥\+([\d.]+)%",
        block,
    )
    if m2:
        g = m2.groups()
        try:
            spec.pool_need = int(g[0] or g[2])
            spec.pool_pct = float(g[1] or g[3])
        except (TypeError, ValueError, IndexError):
            pass
    if re.search(r"≥\+([\d.]+)%\s*[）\)]?\s*（|板块当日涨幅", block):
        mp = re.search(r"板块当日涨幅≥\+([\d.]+)%", block)
        if mp:
            try:
                spec.min_board_pct = float(mp.group(1))
            except ValueError:
                pass
            spec.or_rank_or_pct = True
    if re.search(r"短线侠|封单前", block):
        spec.third_manual = True
    # 美能：竞价额≥昨×0.8
    m3 = re.search(
        r"\*\*([^*]+)\*\*.*?竞价额≥昨×([\d.]+)|昨×([\d.]+).*?美能",
        block,
    )
    if m3:
        if m3.group(1) and "美能" in m3.group(1):
            spec.lead_keywords = [m3.group(1).strip()]
        rr = m3.group(2) or m3.group(3)
        if rr:
            try:
                spec.lead_amt_ratio = float(rr)
            except ValueError:
                pass
    m4 = re.search(r"涨幅≥\+([\d.]+)%", block)
    if m4 and spec.lead_min_pct is None:
        try:
            spec.lead_min_pct = float(m4.group(1))
        except ValueError:
            pass
    # 显式「芯片/半导体」（勿覆盖油气支线默认关键词）
    mk = re.search(
        r"([\u4e00-\u9fa5/、]+)板块东财|东财.*?([\u4e00-\u9fa5/、]+)板块",
        block,
    )
    if mk and not spec.or_rank_or_pct:
        raw = (mk.group(1) or mk.group(2) or "").strip()
        parts = re.split(r"[、/]", raw)
        kws = [p.strip() for p in parts if p.strip() and len(p.strip()) <= 6]
        if kws:
            spec.board_keywords = kws
    return spec


def parse_b_candidates(content: str) -> List[BCandidate]:
    out: List[BCandidate] = []
    for m in re.finditer(
        r"###\s*候选([一二两\d]+)[：:]\s*([^\n]+)",
        content,
    ):
        title = m.group(2).strip()
        start = m.end()
        nxt = content.find("\n### ", start)
        if nxt == -1:
            nxt = len(content)
        block = content[start:nxt]
        stocks = []
        for line in block.splitlines():
            mm = re.match(
                r"\|\s*(\d+)\s*\|\s*\*\*(.+?)\*\*\(\s*`?([\d.]+)\.(SZ|SH)`?\s*\)\s*\|",
                line.strip(),
            )
            if mm:
                stocks.append(
                    {
                        "rank": int(mm.group(1)),
                        "name": mm.group(2).strip(),
                        "ts_code": f"{mm.group(3)}.{mm.group(4)}",
                        "role": "",
                    }
                )
        sw = ""
        sm = re.search(r">\s*\*\*切换确认.*?\*\*", block, re.DOTALL)
        if sm:
            sw = block[sm.start() : sm.end() + 400]
        switch = parse_switch_spec(sw or block, title)
        out.append(
            BCandidate(
                title=title,
                stocks=stocks,
                raw_switch_block=sw,
                switch=switch,
            )
        )
    return out


def parse_stock_prev_bn_from_block(block: str, stock_name: str) -> Optional[float]:
    """表格或切换区「昨X.XX亿」与股票名邻近匹配（粗）。"""
    if not block or not stock_name:
        return None
    i = block.find(stock_name)
    if i < 0:
        return None
    chunk = block[i : i + 400]
    m = re.search(r"昨([\d.]+)亿", chunk)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def parse_exclude_block(content: str) -> set:
    ex = set()
    sec = re.search(
        r"###\s*❌\s*不做.*?\n(.*?)(?=\n###|\n---|\Z)",
        content,
        re.DOTALL,
    )
    if not sec:
        return ex
    for n, c, suf in _TS.findall(sec.group(1)):
        ex.add(f"{c}.{suf}")
    return ex


def _codes_from_chains(struct: dict) -> set:
    s = set()
    for key in ("p1_chain", "p2_chain"):
        for _a, _b, tc in struct.get(key) or []:
            s.add(tc)
    # Also collect codes from additional chains (multi-chain support)
    for chains_key in ("p1_chains", "p2_chains"):
        for chain_data in struct.get(chains_key) or []:
            for _a, _b, tc in chain_data.get("chain") or []:
                s.add(tc)
    return s


def build_parsed_card(card_path: Optional[str]) -> Optional[ParsedCard]:
    stock_map, sectors, path, struct = parse_card(override_path=card_path)
    if not stock_map:
        return None
    content = _read_file(path)
    meta = parse_embedded_meta(content)
    caps = parse_caps_first_line(content)
    wind_name, wind_code = parse_step0_wind(content)
    width_names = parse_width_tickers_from_step0(content)
    ks_struct = float(struct.get("key_support") or 3870)
    ks = merge_key_support(meta, ks_struct, content)
    wprev = parse_wind_prev_amount_bn(content)
    b = parse_b_candidates(content)
    ex = parse_exclude_block(content)
    return ParsedCard(
        content=content,
        path=path,
        struct=struct,
        meta=meta,
        single_cap_note=caps,
        width_names=width_names,
        wind_name=wind_name,
        wind_code=wind_code,
        wind_prev_amount_bn=wprev,
        key_support=ks,
        b_candidates=b,
        exclude_codes=ex,
    )


def rows_to_code_map(rows) -> Dict[str, Tuple]:
    out = {}
    for r in rows:
        if len(r) >= 5:
            out[str(r[1])] = r
    return out


def sh_price_from_indices(indices) -> Optional[float]:
    for name, code, price, pct in indices:
        if code == "000001":
            return float(price)
    return None


def try_fetch_auction_today() -> Optional[Dict[str, Dict]]:
    """拉取竞价数据，直接调用（已足够快）。"""
    try:
        from verify_daily import fetch_auction
        td = time.strftime("%Y%m%d")
        auc_data = fetch_auction(td)
        return auc_data if auc_data else None
    except Exception:
        # 静默失败，不中断主流程
        return None


def get_cached_auction(hm: int) -> Optional[Dict[str, Dict]]:
    """9:25 后返回竞价数据（首次拉取后缓存，全天复用）。"""
    global _AUCTION_CACHE
    if hm < 925:
        return None
    if _AUCTION_CACHE is not None:
        return _AUCTION_CACHE
    result = try_fetch_auction_today()
    if result:
        _AUCTION_CACHE = result
    return result


def count_width_ok(
    width_names: List[str],
    stock_map: Dict[str, str],
    code_to_row: Dict[str, Tuple],
    threshold: float = 3.0,
) -> Tuple[int, int]:
    hits = 0
    total = 0
    for nm in width_names:
        code_full = None
        for k, v in stock_map.items():
            if nm in v or v in nm:
                code_full = k
                break
        if not code_full:
            continue
        num = code_full.split(".")[0]
        row = code_to_row.get(num)
        if not row:
            continue
        total += 1
        if float(row[3]) >= threshold:
            hits += 1
    return hits, total


def parse_all_health_conditions(content: str) -> Dict[str, List[Dict[str, Any]]]:
    """从速查正文全局顺序提取健康度验证块，映射为 p1, p2（用于无 struct 时的回退）。
    每条：{"name": str, "threshold": float}
    优先从 struct chain-level health 读取；此函数仅作为 struct 缺失时的兜底。
    """
    result: Dict[str, List] = {}
    keys = ["p1", "p2"]
    idx = 0
    # 宽松匹配：含「健康度」字样的 ⚠️ 块（含「验证」或不含）
    for m in re.finditer(
        r"⚠️[^\n]*健康度[^\n]*[：:](.*?)(?=####|\n\n[^>]|\Z)",
        content,
        re.DOTALL,
    ):
        if idx >= len(keys):
            break
        block = m.group(0)
        checks: List[Dict[str, Any]] = []
        # 行格式：龙X **Name** [竞价涨幅] > threshold%
        for cm in re.finditer(
            r"龙[一二三四五\d]+\s*\*\*([^*]+)\*\*(?:[^>＞\n]{0,40})[>＞]\s*([+-]?[\d.]+)%",
            block,
        ):
            checks.append({"name": cm.group(1).strip(), "threshold": float(cm.group(2))})
        # 内联格式：Name＞threshold% （行格式未匹配时）
        if not checks:
            for cm in re.finditer(
                r"([^\s；；，,>＞（(]{2,8})[>＞]\s*([+-]?[\d.]+)%",
                block,
            ):
                nm = cm.group(1).strip().lstrip("*")
                if len(nm) >= 2:
                    checks.append({"name": nm, "threshold": float(cm.group(2))})
        if checks:
            result[keys[idx]] = checks
            idx += 1
    return result


def eval_health_check(
    checks: List[Dict[str, Any]],
    stock_map: Dict[str, str],
    code_to_row: Dict[str, Tuple],
    required: int = 2,
) -> Dict[str, Any]:
    """评估健康度验证条件，返回结构化结果供 Web 前端消费。"""
    detail: List[Dict[str, Any]] = []
    for c in checks:
        name, thr = c["name"], c["threshold"]
        ts_code = next(
            (k for k, v in stock_map.items() if name in v or v in name), None
        )
        pct: Optional[float] = None
        if ts_code:
            row = code_to_row.get(ts_code.split(".")[0])
            if row:
                pct = float(row[3])
        passed = pct is not None and pct > thr
        thr_str = f">+{thr:.1f}%" if thr >= 0 else f">{thr:.1f}%"
        detail.append({
            "name": name,
            "ts_code": ts_code or "",
            "thr_str": thr_str,
            "pct": round(pct, 2) if pct is not None else None,
            "pct_str": f"{pct:+.2f}%" if pct is not None else "—",
            "pass": bool(passed),
        })
    ok = sum(1 for d in detail if d["pass"])
    return {"required": required, "ok_count": ok, "passed": ok >= required, "checks": detail}


def eval_b_switch_json(bc: "BCandidate", code_to_row: Dict[str, Tuple]) -> Dict[str, Any]:
    """计算 B 候选切换确认状态（可自动化部分：池内强度）。"""
    spec = bc.switch
    pool_hits = 0
    for s in bc.stocks:
        row = code_to_row.get(s["ts_code"].split(".")[0])
        if row and float(row[3]) >= spec.pool_pct:
            pool_hits += 1
    pool_ok = pool_hits >= spec.pool_need
    board_desc = f"板块排名前{spec.max_rank}（人工）" if spec.max_rank else "板块排名（人工）"
    checks = [
        {"desc": board_desc, "auto": False, "pass": None},
        {
            "desc": f"池内≥{spec.pool_need}只≥{spec.pool_pct:+.1f}%  当前{pool_hits}只",
            "auto": True,
            "pass": pool_ok,
        },
        {
            "desc": "封单/龙头确认（人工）" if spec.third_manual else "龙头竞价额",
            "auto": False,
            "pass": None,
        },
    ]
    return {
        "required": 2,
        "auto_ok_count": 1 if pool_ok else 0,
        "pool_ok": pool_ok,
        "pool_detail": f"{pool_hits}/{len(bc.stocks)}只≥{spec.pool_pct:+.1f}%",
        "checks": checks,
    }


def eval_b_pool_strength(
    stocks: List[dict], code_to_row: Dict[str, Tuple], pct_min: float
) -> Tuple[int, int]:
    ok = 0
    n = 0
    for s in stocks:
        num = s["ts_code"].split(".")[0]
        row = code_to_row.get(num)
        if not row:
            continue
        n += 1
        if float(row[3]) >= pct_min:
            ok += 1
    return ok, n


def extract_chain_title(content: str, order: str) -> str:
    """从速查内容动态提取「第X优先（概念名）」中的概念名"""
    m = re.search(rf"###\s*✅\s*{order}优先[（(]([^）)]+)[）)]", content)
    return m.group(1) if m else f"{order}优先"


def chain_stock_status(
    chain: List[tuple],
    code_to_row: Dict[str, Tuple]
) -> List[Tuple[str, Optional[float], str]]:
    """
    返回链内前3龙（龙一～龙三）的 (显示名, 涨幅%, 操作建议)
    - 显示名：龙一·中恒电气
    - 涨幅：实时数据（None表示无数据）
    - 建议：⚠封板 / ✓可操作 / →观望 / ↘低开 / 暂无数据
    """
    result = []
    for rank_ch, name, tc in chain[:3]:
        num = tc.split(".")[0]
        row = code_to_row.get(num)
        pct = float(row[3]) if row else None

        if pct is None:
            suggestion = "暂无数据"
        elif pct >= 9.5:
            suggestion = "⚠封板"
        elif pct >= 3.0:
            suggestion = "✓可操作"
        elif pct >= 0:
            suggestion = "→观望"
        else:
            suggestion = "↘低开"

        display_name = f"龙{rank_ch}·{name}"
        result.append((display_name, pct, suggestion))

    return result


def get_candidate_operable_stocks(
    bc: BCandidate,
    code_to_row: Dict[str, Tuple]
) -> List[Tuple[str, Optional[float]]]:
    """从备选方案的股票中提取可操作的（涨幅≥3.0%）"""
    result = []
    for stock in bc.stocks:
        num = stock["ts_code"].split(".")[0]
        row = code_to_row.get(num)
        pct = float(row[3]) if row else None
        if pct is not None and pct >= 3.0:
            result.append((stock["name"], pct))
    return result


def format_sig2_label(s: str, hm: int, wind_name: str = "", auc_amt: Optional[float] = None) -> str:
    """
    格式化信号2（封单额）的描述。
    - ok: ✓ 封单健康（金额）
    - fail: ✗ 封单萎缩（金额）
    - fuzzy + 有金额: → 封单中等（金额）
    - fuzzy + 无金额: —（无竞价数据）
    - hm<925: 竞价进行中
    """
    wind_part = f"，{wind_name}" if wind_name and wind_name != "—" else ""
    amt_part = f"({auc_amt:.2f}亿)" if auc_amt is not None and auc_amt > 0 else ""

    if s == "ok":
        return f"✓ 封单健康 {amt_part}{wind_part}"
    elif s == "fail":
        return f"✗ 封单萎缩 {amt_part}{wind_part}"
    elif hm < 925:
        return f"竞价进行中（{wind_name}）"
    elif auc_amt is not None and auc_amt > 0:
        return f"→ 封单中等 {amt_part}{wind_part}"
    else:
        return f"—（无竞价数据，{wind_name}）"


def health_chain(
    chain: List[tuple],
    checks: List[Tuple[str, float]],
    code_to_row: Dict[str, Tuple],
) -> Tuple[int, int]:
    ok = 0
    for name_need, thr in checks:
        for _t, nm, tc in chain:
            if name_need in nm:
                num = tc.split(".")[0]
                row = code_to_row.get(num)
                if row and float(row[3]) > thr:
                    ok += 1
                break
    return ok, len(checks)


def health_p1(struct: dict, code_to_row: Dict[str, Tuple]) -> Tuple[int, int]:
    chain = struct.get("p1_chain") or []
    # 动态取龙二、龙三、龙四，统一阈值 0.0（红盘即健康）
    checks = [(nm, 0.0) for _r, nm, _tc in chain[1:4]]
    return health_chain(chain, checks, code_to_row)


def health_p2(struct: dict, code_to_row: Dict[str, Tuple]) -> Tuple[int, int]:
    chain = struct.get("p2_chain") or []
    # 动态取龙二、龙三、龙四，统一阈值 0.0（红盘即健康）
    checks = [(nm, 0.0) for _r, nm, _tc in chain[1:4]]
    return health_chain(chain, checks, code_to_row)


def count_other_theme_hot(
    stock_map: Dict[str, str],
    code_to_row: Dict[str, Tuple],
    exclude_codes: set,
    wind_code: str,
    pct_line: float = 5.0,
) -> int:
    """第零步第4行：其它票竞价涨幅≥pct_line（排除主线链与❌不做）。"""
    ex = set(exclude_codes)
    if wind_code:
        ex.add(wind_code)
    n = 0
    for ts_c in stock_map:
        if ts_c in ex:
            continue
        num = ts_c.split(".")[0]
        row = code_to_row.get(num)
        if row and float(row[3]) >= pct_line:
            n += 1
    return n


def eval_b_switch_auto(
    bc: BCandidate,
    spec: BSwitchSpec,
    em_rows: List[Tuple[str, float]],
    em_total: int,
    auc_map: Optional[Dict[str, Dict]],
    code_to_row: Dict[str, Tuple],
    card_content: str,
) -> Tuple[int, int, List[str]]:
    """返回 (命中数, 自动化项数, 说明片段)。不再判断题材竞价排名。"""
    parts: List[str] = []
    hits = 0
    # 注：移除板块竞价排名判断，只保留池内强度和龙头竞价

    # 条件1：池内强度（龙头涨幅）
    okn, _ = eval_b_pool_strength(bc.stocks, code_to_row, spec.pool_pct)
    pool_ok = okn >= spec.pool_need
    if pool_ok:
        hits += 1
    parts.append(f"题材内≥{spec.pool_pct}%:{okn}只")

    # 条件2：龙头竞价（可选）
    if not spec.third_manual and spec.lead_keywords and auc_map:
        for s in bc.stocks:
            for kw in spec.lead_keywords:
                if kw in s["name"]:
                    a = auc_map.get(s["ts_code"])
                    if a:
                        pct = a.get("pct") or 0
                        amt = a.get("amount_bn") or 0
                        ok_lead = spec.lead_min_pct is None or pct >= spec.lead_min_pct
                        if spec.lead_amt_ratio is not None:
                            prev_bn = parse_stock_prev_bn_from_block(
                                card_content, s["name"]
                            )
                            if prev_bn and prev_bn > 0:
                                ok_lead = ok_lead and amt >= prev_bn * spec.lead_amt_ratio
                        if ok_lead and amt > 0:
                            hits += 1
                            parts.append(f"{kw}竞价{pct:+.2f}%额{amt:.2f}亿")
                    break

    # 条件3：人工判断（封单等，始终不算在自动化内）
    auto_used = 2 if spec.third_manual else min(2, hits)
    return hits, auto_used, parts


def step0_signal_states(
    em_rows: List[Tuple[str, float]],
    em_total: int,
    meta: Dict[str, Any],
    auc_map: Optional[Dict[str, Dict]],
    wind_code: str,
    wind_prev_bn: Optional[float],
    width_hits: int,
    width_total: int,
    other_hot_n: int,
    hm: int,
) -> Tuple[List[str], List[str], List[str]]:
    """
    返回三态列表 s1,s2,s3,s4 每项为 'ok'|'fail'|'fuzzy'
    """
    step0_cfg = (meta.get("step0") or {}) if meta else {}
    hw_kw = step0_cfg.get("huawei") or step0_cfg.get("main_keywords") or ["华为"]
    rival_kw = step0_cfg.get("rivals") or ["芯片", "锂电"]

    def _tri(hr: Optional[int], total: int) -> str:
        if hr is None or total <= 0:
            return "fuzzy"
        third = max(1, total // 3)
        half = max(1, total // 2)
        chip_r = find_board_rank(em_rows, ["芯片", "半导体"])
        li_r = find_board_rank(em_rows, ["锂电", "锂电池"])
        overt = False
        for r in (chip_r, li_r):
            if r is not None and hr is not None and r < hr:
                overt = True
                break
        if hr > half or overt:
            return "fail"
        if hr <= third:
            return "ok"
        return "fuzzy"

    hr = find_board_rank(em_rows, list(hw_kw)) if em_rows else None
    s1 = _tri(hr, em_total or len(em_rows))

    s2 = "fuzzy"
    if hm < 925:
        s2 = "fuzzy"
    elif auc_map and wind_code:
        a = auc_map.get(wind_code)
        if a and wind_prev_bn and wind_prev_bn > 0:
            amt = a.get("amount_bn") or 0
            if amt >= wind_prev_bn * 0.7:
                s2 = "ok"
            elif amt < wind_prev_bn * 0.5:
                s2 = "fail"
            else:
                s2 = "fuzzy"
        elif a and (not wind_prev_bn):
            s2 = "fuzzy"
    else:
        s2 = "fuzzy"

    if width_total > 0:
        s3 = "ok" if width_hits >= 2 else "fail"
    else:
        s3 = "fuzzy"

    s4 = "ok" if other_hot_n < 2 else "fail"

    return [s1, s2, s3, s4], [hw_kw, rival_kw], [str(hr or "—"), str(wind_prev_bn or "—")]


def decide_mode(
    s123: List[str],
) -> Tuple[str, str]:
    """
    前 3 条：全 ok -> A；≥2 fail -> B；其余模糊。
    """
    first3 = s123[:3]
    fails = sum(1 for x in first3 if x == "fail")
    oks = sum(1 for x in first3 if x == "ok")
    if fails >= 2:
        return "选择模式B", "B"
    if oks == 3:
        return "选择模式A", "A"
    return "信号模糊·偏空仓", "FUZZY"


def build_one_line(
    pc: ParsedCard,
    sh_price: Optional[float],
    ks: float,
    fact_parts: List[str],
    mode_label: str,
    actions: List[str],
    hm: int,
) -> str:
    tail = f"结论——{mode_label}"
    if actions:
        tail += "；" + "；".join(actions)
    else:
        tail += "；观望"
    return (
        f"{hm // 100:02d}:{hm % 100:02d}——"
        + "；".join(fact_parts)
        + "；"
        + tail
        + "；"
    )


def _stock_to_dict(
    label: str,
    tc: str,
    code_to_row: Dict[str, Tuple],
    thresholds: Dict[str, Tuple[Optional[float], Optional[float]]],
    auc: Optional[Dict],
    prev_auc_map: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """将单股实时数据转为 JSON 可序列化字典，供 Web 仪表盘消费。"""
    num = tc.split(".")[0]
    row = code_to_row.get(num)
    pct = float(row[3]) if row else None
    pct_thr, amt_thr = thresholds.get(tc, (None, None))
    default_thr = pct_thr if pct_thr is not None else 3.0

    if pct is None:
        status_type, status_text = "nodata", "无数据"
    elif pct >= 9.5:
        status_type, status_text = "sealed", "⚠封死"
    elif pct >= default_thr:
        thr_label = f"≥{pct_thr:.2f}%" if pct_thr else "≥3.0%"
        status_type, status_text = "ok", f"✓ 涨幅 ({thr_label})"
    elif pct >= 0:
        thr_label = f"需≥{pct_thr:.2f}%" if pct_thr else "需≥3.0%"
        status_type, status_text = "watch", f"→ 观望 ({thr_label})"
    else:
        status_type, status_text = "drop", "↘ 低开"

    d: Dict[str, Any] = {
        "label": label,
        "ts_code": tc,
        "pct": pct,
        "pct_str": f"{pct:+.2f}%" if pct is not None else "—",
        "pct_thr": pct_thr,
        "amt_thr": amt_thr,
        "status_type": status_type,
        "status_text": status_text,
        "has_auc": False,
        "auc_amt": None,
        "auc_ok": None,
        "prev_auc_bn": None,
        "auc_ratio": None,
    }

    if prev_auc_map:
        pv = prev_auc_map.get(tc)
        if pv is not None and pv > 0:
            d["prev_auc_bn"] = round(pv, 4)

    if auc:
        a = auc.get(tc)
        if a:
            amt = a.get("amount_bn") or 0
            if amt > 0:
                d["has_auc"] = True
                d["auc_amt"] = round(amt, 2)
                if amt_thr is not None:
                    d["auc_ok"] = amt >= amt_thr
                pbn = d.get("prev_auc_bn")
                if pbn and pbn > 0:
                    d["auc_ratio"] = round(amt / pbn, 4)
    return d


def build_dashboard_json(
    hm: int,
    sh: Optional[float],
    ks: float,
    p1_title: str,
    p1_chain: List[tuple],
    p2_title: str,
    p2_chain: List[tuple],
    b_candidates: List,
    watch_packages: List[dict],
    code_to_row: Dict[str, Tuple],
    thresholds: Dict[str, Tuple[Optional[float], Optional[float]]],
    auc: Optional[Dict],
    p1_health: Optional[Dict] = None,
    p2_health: Optional[Dict] = None,
    p1_chains_data: Optional[List[Dict]] = None,
    p2_chains_data: Optional[List[Dict]] = None,
    stock_map: Optional[Dict[str, str]] = None,
    prev_auc_map: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """构建供 Web 仪表盘消费的完整 JSON 数据结构。"""
    hh, mm = hm // 100, hm % 100

    def _build_chains_section(chains_data: Optional[List[Dict]]) -> List[Dict]:
        if not chains_data:
            return []
        result = []
        for c in chains_data:
            chain_stocks = [
                _stock_to_dict(f"龙{r}·{n}", tc, code_to_row, thresholds, auc, prev_auc_map)
                for r, n, tc in c.get("chain") or []
            ]
            health_checks = c.get("health") or []
            health = (
                eval_health_check(health_checks, stock_map or {}, code_to_row)
                if health_checks else {}
            )
            result.append({
                "title": c.get("title", ""),
                "stocks": chain_stocks,
                "health": health,
            })
        return result

    return {
        "tick_time": f"{hh:02d}:{mm:02d}",
        "sh_price": sh,
        "sh_price_str": f"{sh:.2f}" if sh is not None else "—",
        "key_support": ks,
        "sh_ok": sh is not None and sh >= ks,
        "p1_title": p1_title,
        "p1_health": p1_health or {},
        "p1": [
            _stock_to_dict(f"龙{r}·{n}", tc, code_to_row, thresholds, auc, prev_auc_map)
            for r, n, tc in p1_chain
        ],
        "p1_chains": _build_chains_section(p1_chains_data),
        "p2_title": p2_title,
        "p2_health": p2_health or {},
        "p2": [
            _stock_to_dict(f"龙{r}·{n}", tc, code_to_row, thresholds, auc, prev_auc_map)
            for r, n, tc in p2_chain
        ],
        "p2_chains": _build_chains_section(p2_chains_data),
        "b_candidates": [
            {
                "title": bc.title,
                "switch_eval": eval_b_switch_json(bc, code_to_row),
                "stocks": [
                    _stock_to_dict(
                        f"{s['rank']}·{s['name']}", s["ts_code"],
                        code_to_row, thresholds, auc, prev_auc_map,
                    )
                    for s in bc.stocks
                ],
            }
            for bc in b_candidates
        ],
        "watch_packages": [
            {
                "title": wp["title"],
                "stocks": [
                    _stock_to_dict(
                        f"{s['rank']}·{s['name']}", s["ts_code"],
                        code_to_row, thresholds, auc, prev_auc_map,
                    )
                    for s in wp.get("stocks") or []
                ],
            }
            for wp in watch_packages
        ],
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # 前端据此判断是否与上一拍不同（秒级时间戳在快速连写时可能重复）
        "push_id": time.time_ns(),
    }


def _write_dashboard_json(data: Dict[str, Any]) -> None:
    """将仪表盘 JSON 写入 dashboard_latest.json 及 dashboard_YYYYMMDD.json（历史快照）。"""
    try:
        os.makedirs(str(CACHE_DIR), exist_ok=True)
        out_path = os.path.join(str(CACHE_DIR), "dashboard_latest.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 同时写当日快照（覆盖同一天的上一次），供历史回看
        date_str = time.strftime("%Y%m%d")
        snap_path = os.path.join(str(CACHE_DIR), f"dashboard_{date_str}.json")
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def parse_stock_thresholds(content: str) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """从速查票池表格解析每只股票的买入条件。

    返回 {ts_code: (涨幅阈值%, 竞价额阈值亿)}，任一未找到则为 None。
    表格行示例：
      | **圣阳股份**(002580.SZ) | 龙二 | 涨幅≥+3.98%+今日竞价≥1.37亿（昨1.37亿×1.0） | 低开无承接 |
    """
    thresholds: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for m in _TS.finditer(content):
        code = f"{m.group(2)}.{m.group(3)}"
        line_start = content.rfind("\n", 0, m.start()) + 1
        line_end = content.find("\n", m.end())
        line = content[line_start: (line_end if line_end >= 0 else len(content))]

        pct_thr: Optional[float] = None
        amt_thr: Optional[float] = None

        pm = re.search(r"涨幅≥\+([\d.]+)%", line)
        if pm:
            try:
                pct_thr = float(pm.group(1))
            except ValueError:
                pass

        # 匹配多种写法：今日竞价≥ / 今日竞价额≥ / 今日竞价成交额≥ / 今日≥
        am = re.search(r"今日(?:竞价(?:成交额|额)?)?≥\s*([\d.]+)\s*亿", line)
        if am:
            try:
                amt_thr = float(am.group(1))
            except ValueError:
                pass
        # 回退：「昨 X.XX 亿×1.0」写法中直接取昨日绝对值作为参考阈值
        if amt_thr is None:
            am2 = re.search(r"昨\s*([\d.]+)\s*亿\s*[×x×]", line)
            if am2:
                try:
                    amt_thr = float(am2.group(1))
                except ValueError:
                    pass

        if pct_thr is not None or amt_thr is not None:
            # 同一个股票可能出现在多行，取第一条有效值
            if code not in thresholds:
                thresholds[code] = (pct_thr, amt_thr)
    return thresholds


def _fmt_stock_row(
    label: str,
    tc: str,
    code_to_row: Dict[str, Tuple],
    thresholds: Dict[str, Tuple[Optional[float], Optional[float]]],
    auc: Optional[Dict],
    indent: str = "  ",
) -> str:
    """格式化单只股票的监控行，包含涨幅状态与竞价额核验。"""
    num = tc.split(".")[0]
    row = code_to_row.get(num)
    pct = float(row[3]) if row else None
    pct_thr, amt_thr = thresholds.get(tc, (None, None))
    default_thr = pct_thr if pct_thr is not None else 3.0

    # 涨幅状态
    if pct is None:
        pct_str = "  —  "
        status = "无数据"
    elif pct >= 9.5:
        pct_str = f"{pct:+.2f}%"
        status = "⚠封死"
    elif pct >= default_thr:
        pct_str = f"{pct:+.2f}%"
        thr_label = f"≥{pct_thr:.2f}%" if pct_thr else "≥3.0%"
        status = f"✓涨幅({thr_label})"
    elif pct >= 0:
        pct_str = f"{pct:+.2f}%"
        thr_label = f"需≥{pct_thr:.2f}%" if pct_thr else "需≥3.0%"
        status = f"→观望({thr_label})"
    else:
        pct_str = f"{pct:+.2f}%"
        status = "↘低开"

    # 竞价额（9:25后有缓存时展示）
    amt_str = ""
    if auc:
        a = auc.get(tc)
        if a:
            amt = a.get("amount_bn") or 0
            if amt > 0:
                if amt_thr is not None:
                    mark = "✓" if amt >= amt_thr else "✗"
                    amt_str = f"  竞价{amt:.2f}亿{mark}(需≥{amt_thr:.2f})"
                else:
                    amt_str = f"  竞价{amt:.2f}亿"

    return f"{indent}{label:<12} {pct_str:>8}  {status}{amt_str}"


def build_stock_output(
    hm: int,
    sh: Optional[float],
    ks: float,
    p1_title: str,
    p1_chain: List[tuple],
    p2_title: str,
    p2_chain: List[tuple],
    b_candidates: List,
    watch_packages: List[dict],
    code_to_row: Dict[str, Tuple],
    thresholds: Dict[str, Tuple[Optional[float], Optional[float]]],
    auc: Optional[Dict],
) -> str:
    """直接展示各链条股票数据，不做第零步判断。"""
    hh, mm = hm // 100, hm % 100
    out = []
    W = 54

    # ── 顶栏：时间 + 上证 ──────────────────────────────
    idx_ok = sh is not None and sh >= ks
    idx_tag = "守住" if idx_ok else "⚠破位"
    sh_str = f"{sh:.2f}" if sh is not None else "无数据"
    out.append("═" * W)
    out.append(f"  {hh:02d}:{mm:02d}   上证 {sh_str}  [{idx_tag} {ks:.2f}]")
    out.append("─" * W)

    # ── 第一优先 ──────────────────────────────────────
    out.append(f"  ① {p1_title}")
    if p1_chain:
        for rank_ch, name, tc in p1_chain:
            out.append(_fmt_stock_row(f"龙{rank_ch}·{name}", tc, code_to_row, thresholds, auc))
    else:
        out.append("    （未解析到链条）")
    out.append("─" * W)

    # ── 第二优先 ──────────────────────────────────────
    out.append(f"  ② {p2_title}")
    if p2_chain:
        for rank_ch, name, tc in p2_chain:
            out.append(_fmt_stock_row(f"龙{rank_ch}·{name}", tc, code_to_row, thresholds, auc))
    else:
        out.append("    （未解析到链条）")
    out.append("─" * W)

    # ── B备选 ─────────────────────────────────────────
    out.append("  B 备选（切换候选）")
    if b_candidates:
        for bc in b_candidates:
            out.append(f"    • {bc.title}")
            for s in bc.stocks:
                tc = s["ts_code"]
                label = f"  {s['rank']}·{s['name']}"
                out.append(_fmt_stock_row(label, tc, code_to_row, thresholds, auc, indent="      "))
    else:
        out.append("    （无B备选）")
    out.append("─" * W)

    # ── 低吸候选（盘中观察） ───────────────────────────
    out.append("  低吸候选（盘中观察）")
    if watch_packages:
        for wp in watch_packages:
            out.append(f"    [{wp['title']}]")
            for s in wp.get("stocks") or []:
                tc = s["ts_code"]
                label = f"  {s['rank']}·{s['name']}"
                out.append(_fmt_stock_row(label, tc, code_to_row, thresholds, auc, indent="      "))
    else:
        out.append("    （池内暂无数据）")
    out.append("═" * W)

    return "\n".join(out)


def _chain_display_title(chains_data: List[Dict]) -> str:
    """Derive a clean display title from multi-chain data (topic name after '—' dash)."""
    if not chains_data:
        return ""
    titles = []
    for c in chains_data:
        t = c.get("title", "")
        m = re.search(r'[—–]\s*([^（(\n]+)', t)
        if m:
            titles.append(m.group(1).strip())
        elif t:
            titles.append(t)
    return " / ".join(titles) if titles else ""


def run_tick(pc: ParsedCard, hm: int) -> str:
    stock_map = pc.struct.get("stock_map") or {}
    indices = get_indices(None)
    rows = fetch_stocks(stock_map, None)
    code_to_row = rows_to_code_map(rows)
    sh = sh_price_from_indices(indices)
    auc = get_cached_auction(hm)

    thresholds = parse_stock_thresholds(pc.content)
    prev_auc_map = parse_speedcard_prev_auction_bn(pc.content)

    # 优先使用 struct 中按小节归属的多链数据
    p1_chains_data = pc.struct.get("p1_chains") or []
    p2_chains_data = pc.struct.get("p2_chains") or []

    p1_title = _chain_display_title(p1_chains_data) or extract_chain_title(pc.content, "第一")
    p2_title = _chain_display_title(p2_chains_data) or extract_chain_title(pc.content, "第二")

    # 取首链用于文本输出（保持向后兼容）
    p1_chain = p1_chains_data[0]["chain"] if p1_chains_data else (pc.struct.get("p1_chain") or [])
    p2_chain = p2_chains_data[0]["chain"] if p2_chains_data else (pc.struct.get("p2_chain") or [])
    watch_packages = pc.struct.get("watch_packages") or []

    # 健康度从各链自身 block 提取（正确归属），全局顺序回退仅在无数据时使用
    p1_health_checks = p1_chains_data[0]["health"] if p1_chains_data else []
    p2_health_checks = p2_chains_data[0]["health"] if p2_chains_data else []
    if not p1_health_checks or not p2_health_checks:
        all_hc = parse_all_health_conditions(pc.content)
        p1_health_checks = p1_health_checks or all_hc.get("p1", [])
        p2_health_checks = p2_health_checks or all_hc.get("p2", [])

    p1_health = eval_health_check(p1_health_checks, stock_map, code_to_row)
    p2_health = eval_health_check(p2_health_checks, stock_map, code_to_row)

    # 写出仪表盘 JSON（供 Web 前端消费）
    _write_dashboard_json(build_dashboard_json(
        hm, sh, pc.key_support,
        p1_title, p1_chain,
        p2_title, p2_chain,
        pc.b_candidates, watch_packages,
        code_to_row, thresholds, auc,
        p1_health=p1_health,
        p2_health=p2_health,
        p1_chains_data=p1_chains_data,
        p2_chains_data=p2_chains_data,
        stock_map=stock_map,
        prev_auc_map=prev_auc_map,
    ))

    return build_stock_output(
        hm, sh, pc.key_support,
        p1_title, p1_chain,
        p2_title, p2_chain,
        pc.b_candidates,
        watch_packages,
        code_to_row, thresholds, auc,
    )


def build_snapshot_dict(
    pc: ParsedCard,
    line: str,
    hm: int,
    extra: Optional[Dict[str, Any]] = None,
) -> dict:
    out: Dict[str, Any] = {
        "time_hm": hm,
        "card_path": pc.path,
        "key_support": pc.key_support,
        "wind_code": pc.wind_code,
        "wind_prev_amount_bn": pc.wind_prev_amount_bn,
        "meta_embedded": pc.meta,
        "line": line,
    }
    if extra:
        out.update(extra)
    return out


def append_log(date_str: str, text: str) -> None:
    p = os.path.join(LOGS_DIR, f"speedcard_monitor_{date_str}.log")
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def in_window(hm: int) -> bool:
    return 915 <= hm <= 950


def wait_until_915():
    while True:
        t = time.localtime()
        hm = t.tm_hour * 100 + t.tm_min
        if hm >= 915:
            return
        time.sleep(5)


def main():
    ap = argparse.ArgumentParser(description="速查 9:15～9:50 早盘监控")
    ap.add_argument("--card", type=str, default="", help="速查 md 路径")
    ap.add_argument(
        "--once",
        action="store_true",
        help="立即跑一拍并退出（不校验是否在 9:15～9:50）",
    )
    ap.add_argument(
        "--test",
        action="store_true",
        help="测试模式：禁用时间限制，打印到控制台，不写入日志",
    )
    ap.add_argument(
        "--dump-meta",
        action="store_true",
        help="将快照写入 outputs/cache/speedcard_snapshot_YYYY-MM-DD.json",
    )
    args = ap.parse_args()

    pc = build_parsed_card(args.card.strip() or None)
    if not pc:
        print("未找到速查文件", file=sys.stderr)
        sys.exit(1)

    date_str = time.strftime("%Y-%m-%d")

    if args.once:
        hm = time.localtime().tm_hour * 100 + time.localtime().tm_min
        line = run_tick(pc, hm)
        print(line)
        append_log(date_str, line)
        if args.dump_meta:
            snap = build_snapshot_dict(
                pc,
                line,
                hm,
                extra={"note": "东财概念板块为快照；竞价封单等见本目录 README.md"},
            )
            outp = os.path.join(
                str(CACHE_DIR), f"speedcard_snapshot_{date_str}.json"
            )
            with open(outp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            print(f"[meta] 已写入 {outp}", file=sys.stderr)
        return

    if args.test:
        print(f"已加载速查: {pc.path} | [测试模式] 每分钟一条；Ctrl+C 结束")
    else:
        print(f"已加载速查: {pc.path} | 9:15～9:50 每分钟一条；Ctrl+C 结束")
        wait_until_915()

    while True:
        t = time.localtime()
        hm = t.tm_hour * 100 + t.tm_min

        # 检查是否在监控时间段外（测试模式下跳过）
        if not args.test:
            if hm > 950:
                print(time.strftime("%H:%M:%S"), "已逾9:50，结束。")
                break
            if hm < 915:
                time.sleep(30)
                continue

        # 执行一拍
        try:
            line = run_tick(pc, hm)
            print(line)
            if not args.test:  # 仅非测试模式写入日志
                append_log(date_str, line)
        except Exception as e:
            err = f"{time.strftime('%H:%M:%S')} 异常: {e}"
            print(err, file=sys.stderr)
            if not args.test:  # 仅非测试模式写入日志
                append_log(date_str, err)
        
        # 测试模式下直接退出，不等待
        if args.test:
            break

        # 等待到下一分钟（关键改动）
        # 计算还需要等待多少秒才能到达下一分钟
        now = time.time()
        next_minute = int(now // 60) * 60 + 60  # 下一分钟的开始时间（秒级时间戳）
        wait_seconds = next_minute - now

        print(f"[等待 {wait_seconds:.1f} 秒至下一分钟...]", file=sys.stderr)
        time.sleep(wait_seconds + 1)  # +1 确保确实到了下一分钟



def build_readable_output(
    hm: int, sh_price: Optional[float], ks: float,
    sig_descs: List[str], judge_label: str,
    p1_title: str, p1_ok: int, p1_stocks: List[Tuple[str, Optional[float], str]],
    p2_title: str, p2_ok: int, p2_stocks: List[Tuple[str, Optional[float], str]],
    b_data: List[Tuple[str, int, int, List[Tuple[str, Optional[float]]], bool]],
    watch_stocks: List[Tuple[str, str, Optional[float]]],
    actions: List[str],
    mode_label: str
) -> str:
    """易读树形输出，完整显示所有区块（第一/二优先、B备选、低吸候选）"""
    out = []
    hh, mm = hm // 100, hm % 100

    # 时间 + 上证指数
    index_status = "守住" if (sh_price is not None and sh_price >= ks) else "⚠破位"
    if sh_price is not None:
        out.append(
            f"{'═' * 50}\n"
            f"{hh:02d}:{mm:02d}  上证 {sh_price:.2f}  [{index_status} {ks:.2f}]"
        )
    else:
        out.append(f"{'═' * 50}\n{hh:02d}:{mm:02d}  上证 无数据")

    # 第零步信号
    out.append("┌─ 第零步：主线存活判断")
    for i, desc in enumerate(sig_descs):
        prefix = "├──" if i < len(sig_descs) - 1 else "├──"
        out.append(f"│  {prefix} {desc}")
    out.append(f"│  └── 判定：{judge_label}")

    # 第一优先
    out.append(f"├─ ① {p1_title}：")
    if p1_ok >= 2:
        out.append("│  ├── 健康度：✓ 满足")
        if p1_stocks:
            for i, (name, pct, _) in enumerate(p1_stocks):
                is_last = (i == len(p1_stocks) - 1)
                prefix = "│  └──" if is_last else "│  ├──"
                pct_str = f"{pct:+.2f}%" if pct is not None else "—"
                out.append(f"{prefix} {name}  {pct_str}  ← 可操作")
        else:
            out.append("│  └── 健康度满足，但无涨幅达标龙头")
    else:
        out.append("│  └── 健康度 ✗ 不足 → 暂不参与")

    # 第二优先
    out.append(f"├─ ② {p2_title}：")
    if p2_ok >= 2:
        out.append("│  ├── 健康度：✓ 满足")
        if p2_stocks:
            for i, (name, pct, _) in enumerate(p2_stocks):
                is_last = (i == len(p2_stocks) - 1)
                prefix = "│  └──" if is_last else "│  ├──"
                pct_str = f"{pct:+.2f}%" if pct is not None else "—"
                out.append(f"{prefix} {name}  {pct_str}  ← 可操作")
        else:
            out.append("│  └── 健康度满足，但无涨幅达标龙头")
    else:
        out.append("│  └── 健康度 ✗ 不足 → 暂不参与")

    # B模式备选（全部显示，含未确认的）
    out.append("├─ B备选（切换确认）：")
    if b_data:
        for i, item in enumerate(b_data):
            title, hits, total, operable, confirmed = item
            is_last = (i == len(b_data) - 1)
            branch = "│  └──" if is_last else "│  ├──"
            tail = "│     " if not is_last else "│     "
            if confirmed:
                status = f"✓ 已确认（{hits}/{total} 自动条件满足）"
            else:
                status = f"✗ 未达标（{hits}/{total} 自动条件）"
            out.append(f"{branch} {title}：{status}")
            if operable:
                label = "可操作：" if confirmed else "当前涨幅达标："
                for j, (name, pct) in enumerate(operable):
                    last_s = (j == len(operable) - 1)
                    sp = f"{tail}   └──" if last_s else f"{tail}   ├──"
                    pct_str = f"{pct:+.2f}%" if pct is not None else "—"
                    mark = "  ← 可买" if confirmed else "  （待确认）"
                    out.append(f"{sp} {name}  {pct_str}{mark}")
    else:
        out.append("│  └── 无B候选数据")

    # 低吸候选（盘中观察池）
    out.append("├─ 低吸候选（盘中观察）：")
    if watch_stocks:
        for i, (theme, name, pct) in enumerate(watch_stocks):
            is_last = (i == len(watch_stocks) - 1)
            prefix = "│  └──" if is_last else "│  ├──"
            pct_str = f"{pct:+.2f}%" if pct is not None else "—"
            out.append(f"{prefix} [{theme}] {name}  {pct_str}")
    else:
        out.append("│  └── 池内暂无涨幅≥3%标的")

    # 最终结论
    conclusion_parts = [mode_label]
    if actions:
        conclusion_parts.extend(actions)
    out.append(f"└─ 【结论】{'  |  '.join(conclusion_parts)}")

    return "\n".join(out)


if __name__ == "__main__":
    main()
