# -*- coding: utf-8 -*-
"""
速查早盘监控 · 数据层

- **腾讯 qt.gtimg**：个股/指数涨跌幅（与 realtime_engine 一致），连续竞价时段可用。
- **东财 push2 clist**：概念板块 `fs=m:90+t:3`，按 `f3` 涨跌幅降序；用于「板块排名」近似。
  - 9:15～9:25：界面多为竞价/盘前涨幅，**与收盘涨幅不一致**，仅作横向对比参考。
  - 9:25～9:30：集合竞价结束，仍非连续竞价成交价。
  - 9:30 后：与行情软件「概念板块当日涨幅」更接近，仍为**第三方快照**，非交易所官方。
- **Tushare stk_auction**（verify_daily.fetch_auction）：竞价额/竞价涨跌幅，**依赖 token**；无数据时相关项跳过或降级。

全市场封单排行、短线侠等 **无稳定 HTTP API**，脚本标注「需人工」。

请求节流：同一进程内两次东财拉取至少间隔 `_MIN_EM_INTERVAL` 秒（改为 3 秒以支持分钟级监控），同时支持 5 秒本地缓存复用。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}
_EM_CLIST = "http://push2.eastmoney.com/api/qt/clist/get"
_EM_CLIST_DELAY = "http://push2delay.eastmoney.com/api/qt/clist/get"

_MIN_EM_INTERVAL = 3.0  # 改为 3 秒限流（原 55 秒）以支持分钟级监控
_CACHE_TTL = 5.0  # 5 秒内的重复调用复用缓存
_last_em_mono = 0.0
_em_cache: Optional[Tuple[List[Tuple[str, float]], int]] = None
_em_cache_time = 0.0


def _throttle_em() -> None:
    """限流机制：同一数据源 3 秒间隔，避免反爬；同时支持 5 秒本地缓存复用。"""
    global _last_em_mono
    now = time.monotonic()
    if _last_em_mono > 0 and (now - _last_em_mono) < _MIN_EM_INTERVAL:
        time.sleep(_MIN_EM_INTERVAL - (now - _last_em_mono))
    _last_em_mono = time.monotonic()


def fetch_concept_boards_sorted(
    pz: int = 500,
) -> Tuple[List[Tuple[str, float]], int]:
    """
    拉取东财「概念」板块列表（涨幅降序）。
    返回 ( [(板块名, 涨跌幅%)...], API 报告的总条数 total )。

    缓存策略：5 秒内重复调用返回缓存；超过 5 秒重新拉取（受 3 秒限流约束）。
    """
    global _em_cache, _em_cache_time

    now = time.monotonic()
    if _em_cache is not None and (now - _em_cache_time) < _CACHE_TTL:
        return _em_cache

    _throttle_em()
    params = {
        "fid": "f3",
        "po": 1,
        "pz": min(pz, 500),
        "pn": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fs": "m:90+t:3",
        "fields": "f12,f14,f3",
        "ut": _EM_UT,
    }
    proxies = {"http": None, "https": None}
    total = 0
    for url in (_EM_CLIST_DELAY, _EM_CLIST):
        try:
            r = requests.get(
                url, params=params, headers=_EM_HEADERS, timeout=16, proxies=proxies
            )
            if r.status_code != 200:
                continue
            j = r.json()
            data = (j or {}).get("data") or {}
            diff = data.get("diff")
            total = int(data.get("total") or 0)
            if diff is None:
                continue
            if isinstance(diff, dict):
                diff = list(diff.values())
            out: List[Tuple[str, float]] = []
            for bk in diff:
                name = str(bk.get("f14") or "").strip()
                if not name:
                    continue
                p3 = bk.get("f3")
                try:
                    pf = float(p3) if p3 is not None else 0.0
                except (TypeError, ValueError):
                    pf = 0.0
                out.append((name, pf))
            if out:
                _em_cache = (out, total)
                _em_cache_time = time.monotonic()
                return out, total
        except Exception:
            continue

    if _em_cache is not None:
        return _em_cache
    return [], 0


def find_board_rank(
    rows: List[Tuple[str, float]], keywords: List[str]
) -> Optional[int]:
    """首个名称包含任一 keyword 的板块名次（1 起）；优先长关键词避免「气」误配。"""
    kws = sorted((k for k in keywords if k), key=len, reverse=True)
    for i, (name, _) in enumerate(rows):
        for kw in kws:
            if kw in name:
                return i + 1
    return None


def find_board_pct(
    rows: List[Tuple[str, float]], keywords: List[str]
) -> Optional[float]:
    kws = sorted((k for k in keywords if k), key=len, reverse=True)
    for name, pct in rows:
        for kw in kws:
            if kw in name:
                return pct
    return None


_META_COMMENT = re.compile(
    r"<!--\s*speedcard-meta\s*:\s*(\{[\s\S]*?\})\s*-->", re.I
)


def parse_embedded_meta(content: str) -> Dict[str, Any]:
    """解析速查文末 HTML 注释中的 JSON：`<!-- speedcard-meta: {...} -->`。"""
    m = _META_COMMENT.search(content)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def merge_key_support(meta: Dict[str, Any], struct_ks: float, content: str) -> float:
    """meta.key_support > 正文优先解析 > struct。"""
    if meta and isinstance(meta.get("key_support"), (int, float)):
        return float(meta["key_support"])
    v = parse_key_support_card(content)
    if v is not None:
        return v
    return float(struct_ks)


def parse_key_support_card(content: str) -> Optional[float]:
    """从速查正文提取上证关键位（优先「上证/未破/关键」邻近数字）。"""
    patterns = [
        r"(?:上证|指数|关键|支撑|守住|跌破|未破)[^\n]{0,100}?\*?\*?(\d{4}\.\d{2})\*?\*?",
        r"破\s*\*?\*?(\d{4}\.\d{2})\*?\*?",
    ]
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            try:
                v = float(m.group(1))
                if 3000 < v < 5000:
                    return v
            except ValueError:
                pass
    return None
