# -*- coding: utf-8 -*-
"""
全市场成交额 Top10：与上证指数**同一根数 N** 的 5 分钟 K，累计成交额对比。

- **昨日篮**：tushare `daily` 按 `amount` 排序取前一交易日成交额前 10（沪深 A，剔除北交所）。
- **今日篮**：东财 `clist` 当前快照成交额前 10（与 `realtime_engine.fetch_amount_top10_em` 一致）。
- **累计**：各篮 10 只个股各自拉东财 5 分 K，对前 N 根 K 的成交额字段求和后再相加；N 与
  `compute_same_period_5min_amount_ratio`（上证 5 分 K 对齐根数）一致。
- **兜底**：若个股 5 分 K 拉取失败或合计为 0，则昨日篮 = tushare 昨日该股日线成交额（千元→元）之和 ×
  上证「前 N 根/全日」占比（与 `compute_same_period` 相同 K 线回退）；今日篮 = 东财当前额 Top10 的 f6 之和。

说明：两篮标的集合通常不同；对比含义是「头部容量票同期合计成交额」相对强弱，非单票可比。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import requests

from realtime_engine import fetch_amount_top10_em

_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}
_EM_KLINE_HOSTS = (
    "http://push2his.eastmoney.com",
    "http://push2delay.eastmoney.com",
    "http://push2.eastmoney.com",
)


def _ts_code_to_secid(ts_code: str) -> str:
    n = ts_code.split(".")[0].zfill(6)
    if n.startswith("6"):
        return f"1.{n}"
    return f"0.{n}"


def _f12_to_secid(f12: str) -> str:
    n = str(f12).strip().zfill(6)
    if n.startswith("6"):
        return f"1.{n}"
    return f"0.{n}"


def fetch_em_stock_5min_klines_one_day(secid: str, ymd_dash: str) -> List[str]:
    """
    东财个股某日 5 分钟 K；单条逗号分隔，第 7 字段为成交额（元）。
    先 beg=end=YYYYMMDD；失败则用 lmt 拉最近若干根再按日期过滤（与指数 K 拉取策略一致）。
    """
    day_prefix = ymd_dash[:10]
    beg = ymd_dash.replace("-", "")[:8]
    proxies = {"http": None, "https": None}
    base_params = {
        "secid": secid,
        "klt": 5,
        "fqt": 0,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "ut": _EM_UT,
    }
    for host in _EM_KLINE_HOSTS:
        for mode in ("beg", "lmt"):
            try:
                params = dict(base_params)
                if mode == "beg":
                    params["beg"] = beg
                    params["end"] = beg
                else:
                    params["lmt"] = 500
                r = requests.get(
                    f"{host}/api/qt/stock/kline/get",
                    params=params,
                    headers=_EM_HEADERS,
                    timeout=22,
                    proxies=proxies,
                )
                if r.status_code != 200:
                    continue
                j = r.json()
                lines = (j or {}).get("data", {}).get("klines") or []
                if not lines:
                    continue
                if mode == "lmt":
                    lines = [
                        k
                        for k in lines
                        if k.split(",")[0].strip().startswith(day_prefix)
                    ]
                if lines:
                    return list(lines)
            except Exception:
                continue
    return []


def _sum_kline_amount_yuan(klines: List[str], n_bars: int) -> float:
    s = 0.0
    n_eff = min(n_bars, len(klines))
    for k in klines[:n_eff]:
        parts = k.split(",")
        if len(parts) > 6:
            try:
                s += float(parts[6])
            except ValueError:
                pass
    return s


def _fetch_yesterday_top10_ts_codes(pro: Any, trade_yyyymmdd: str) -> List[str]:
    """前一交易日 tushare daily 成交额前 10（沪深，不含北交所）。"""
    try:
        df = pro.daily(trade_date=trade_yyyymmdd)
    except Exception:
        return []
    if df is None or df.empty or "amount" not in df.columns:
        return []
    df = df.copy()
    df["ts_code"] = df["ts_code"].astype(str)
    df = df[df["ts_code"].str.endswith((".SH", ".SZ"))]
    df = df.sort_values("amount", ascending=False).head(10)
    return [str(x) for x in df["ts_code"].tolist()]


def _basket_sum_5m_amount_parallel(
    secids: List[str],
    ymd_dash: str,
    n_bars: int,
    workers: int = 8,
) -> float:
    def one(secid: str) -> float:
        kl = fetch_em_stock_5min_klines_one_day(secid, ymd_dash)
        if not kl:
            return 0.0
        return _sum_kline_amount_yuan(kl, n_bars)

    total = 0.0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, s): s for s in secids}
        for fut in as_completed(futs):
            try:
                total += fut.result()
            except Exception:
                pass
    return total


def _index_yesterday_fraction(yesterday_dash: str, n: int) -> float:
    """上证昨日：前 n 根 5 分 K 成交额 / 全日累计成交额（K 线拉取与 compute_same_period 一致）。"""
    from realtime_monitor_report import (
        fetch_em_sh_5min_klines_one_day,
        fetch_em_sh_5min_klines_lmt,
        fetch_sina_sh_5min_klines,
    )

    ky = fetch_em_sh_5min_klines_one_day(yesterday_dash)
    if not ky:
        all_k = fetch_em_sh_5min_klines_lmt(400)
        prefix_y = yesterday_dash[:10]
        ky = [k for k in all_k if k.split(",")[0].strip().startswith(prefix_y)]
    if not ky:
        all_k = fetch_sina_sh_5min_klines(500)
        prefix_y = yesterday_dash[:10]
        ky = [k for k in all_k if k.split(",")[0].strip().startswith(prefix_y)]
    if not ky:
        return 0.0
    prefix_y = yesterday_dash[:10]
    ky = [k for k in ky if k.split(",")[0].strip().startswith(prefix_y)]

    def sum_amt(klines: List[str], nb: int) -> float:
        s = 0.0
        for k in klines[: min(nb, len(klines))]:
            parts = k.split(",")
            if len(parts) > 6:
                try:
                    s += float(parts[6])
                except ValueError:
                    pass
        return s

    idx_part = sum_amt(ky, n)
    idx_full = sum_amt(ky, len(ky))
    return idx_part / idx_full if idx_full > 0 else 0.0


def _sum_daily_amount_yuan(pro: Any, codes: List[str], yyyymmdd: str) -> float:
    """tushare daily 成交额字段为千元，合计后转元。"""
    try:
        df = pro.daily(trade_date=yyyymmdd, ts_code=",".join(codes))
    except Exception:
        return 0.0
    if df is None or df.empty or "amount" not in df.columns:
        return 0.0
    return float(df["amount"].astype(float).sum()) * 1000.0


def compute_top10_5m_volume_compare(
    yesterday_dash: str,
    today_dash: str,
    pro: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    返回两篮前 N 根 5 分 K 成交额合计（元→亿）及相对变化%。
    yesterday_dash / today_dash: YYYY-MM-DD。
    优先东财个股 5 分 K；若合计为 0 则兜底：昨日篮=昨日日线额×指数同期占比，今日篮=东财 f6。
    """
    from realtime_monitor_report import compute_same_period_5min_amount_ratio
    from realtime_promotion_ts import get_tushare_pro

    sp = compute_same_period_5min_amount_ratio(yesterday_dash, today_dash)
    if not sp:
        return None
    n = int(sp["n_bars"])
    pro = pro or get_tushare_pro()
    if not pro:
        return None

    y_compact = yesterday_dash.replace("-", "")
    y_codes = _fetch_yesterday_top10_ts_codes(pro, y_compact)
    if not y_codes:
        return None

    td = fetch_amount_top10_em()
    if not td:
        return None
    t_f12 = [str(x.get("f12", "")).strip() for x in td if x.get("f12")]
    if not t_f12:
        return None

    y_secids = [_ts_code_to_secid(c) for c in y_codes]
    t_secids = [_f12_to_secid(c) for c in t_f12[:10]]

    sum_y = _basket_sum_5m_amount_parallel(y_secids, yesterday_dash, n)
    sum_t = _basket_sum_5m_amount_parallel(t_secids, today_dash, n)
    mode = "5m"
    source_note = "东财个股5分K成交额之和；N与上证同期根数一致"

    if sum_y <= 0 or sum_t <= 0:
        frac = _index_yesterday_fraction(yesterday_dash, n)
        sum_y_daily_yuan = _sum_daily_amount_yuan(pro, y_codes, y_compact)
        sum_y_fb = sum_y_daily_yuan * frac
        sum_t_fb = sum(float(x.get("f6") or 0) for x in td[:10])
        if sum_y_fb <= 0 or sum_t_fb <= 0:
            return None
        sum_y, sum_t = sum_y_fb, sum_t_fb
        mode = "fallback_daily"
        source_note = (
            "兜底：个股5分K不可用或为零；昨日篮=昨日日线成交额(元)×上证同期成交占比；"
            "今日篮=东财当前额Top10的f6(元)"
        )

    ratio = sum_t / sum_y
    return {
        "n_bars": n,
        "sum_yesterday_basket_yi": sum_y / 1e8,
        "sum_today_basket_yi": sum_t / 1e8,
        "pct_vs_yesterday": (ratio - 1.0) * 100.0,
        "yesterday_ts_codes": y_codes,
        "today_f12": t_f12[:10],
        "source_note": source_note,
        "mode": mode,
    }


def format_top10_vol_line(tv: Optional[Dict[str, Any]]) -> str:
    if not tv:
        return "全市场Top10同期成交额对比：—（未算出）"
    n = tv.get("n_bars", 0)
    sy = float(tv.get("sum_yesterday_basket_yi") or 0)
    st = float(tv.get("sum_today_basket_yi") or 0)
    pv = float(tv.get("pct_vs_yesterday") or 0)
    return (
        f"全市场Top10同期（前{n}根5分K或等价口径）额合计：今日篮{st:.1f}亿 vs 昨日篮{sy:.1f}亿，"
        f"相对{pv:+.1f}%（今日篮=东财当前额Top10；昨日篮=tushare昨日额Top10）"
    )


def top10_vol_md_rows(tv: Optional[Dict[str, Any]]) -> List[str]:
    if not tv:
        return [
            "| Top10 同期 5 分 K 成交额 | — | 计算失败（见脚本 realtime_top10_5m_compare） |"
        ]
    n = tv.get("n_bars", 0)
    sy = float(tv.get("sum_yesterday_basket_yi") or 0)
    st = float(tv.get("sum_today_basket_yi") or 0)
    pv = float(tv.get("pct_vs_yesterday") or 0)
    note = tv.get("source_note", "")
    return [
        f"| Top10 前 **{n}** 根 5 分 K 额合计 | 今日篮 **{st:.1f}** 亿 / 昨日篮 **{sy:.1f}** 亿 | "
        f"相对 **{pv:+.1f}%**；{note} |"
    ]
