# -*- coding: utf-8 -*-
"""
全市场「昨日涨停 / 昨日首板 → 今日继续涨停」晋级率（盘中可用）。

数据：
- 昨日涨停名单：tushare/chinadata `limit_list_d(limit_type='U')`（与复盘脚本一致）。
- 今日是否仍涨停：优先当日 `limit_list_d`；若为空或不全，用东财 ulist 批量现价涨跌幅，
  按板块使用 10%/20% 等涨停阈值判定（与交易所规则一致）。

环境变量：TUSHARE_TOKEN（可选；不设时与同目录 generate_review_from_tushare 内 TOKEN 一致，便于本机直接跑）。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

_EM_UT = "b2884a393a59ad64002292a3e90d46a5"
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}
_EM_ULIST = "http://push2delay.eastmoney.com/api/qt/ulist.np/get"


# 与 verify_daily / generate_review_from_tushare 一致；优先用环境变量覆盖
_DEFAULT_TUSHARE_TOKEN = "y64bdbe41e69304578e024369ab0ccbae88"


def _tushare_token() -> str:
    return os.environ.get("TUSHARE_TOKEN", "").strip() or _DEFAULT_TUSHARE_TOKEN


def _get_pro() -> Optional[Any]:
    token = _tushare_token()
    try:
        import chinadata.ca_data as ts  # type: ignore

        if token:
            ts.set_token(token)
        return ts.pro_api()
    except Exception:
        pass
    try:
        import tushare as ts  # type: ignore

        if token:
            ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def get_tushare_pro() -> Optional[Any]:
    """供 realtime_top10_5m_compare 等模块复用。"""
    return _get_pro()


def _exclude_stock(ts_code: str, name: str) -> bool:
    """与复盘脚本一致：剔除 ST、北交所（北交所涨跌停幅度不同，单独统计易误解）。"""
    c = str(ts_code or "")
    n = str(name or "")
    if "ST" in n.upper():
        return True
    if c.endswith(".BJ"):
        return True
    return False


def _cal_today_prev_trade_days(pro: Any, cal_date_yyyymmdd: str) -> Tuple[Optional[str], Optional[str]]:
    """
    返回 (今日交易日, 昨日交易日) 均为 YYYYMMDD。
    cal_date 为自然日；若当日休市，则「今日交易日」取不晚于 cal_date 的最近开市日。
    """
    try:
        start = (datetime.strptime(cal_date_yyyymmdd, "%Y%m%d") - timedelta(days=60)).strftime("%Y%m%d")
        df = pro.trade_cal(exchange="SSE", start_date=start, end_date=cal_date_yyyymmdd, is_open="1")
    except Exception:
        return None, None
    if df is None or df.empty:
        return None, None
    opens = sorted(str(x) for x in df["cal_date"].tolist())
    if not opens:
        return None, None
    # 不超过 cal_date 的最后一个交易日 = 作为「当前监控日」
    today_td = None
    for d in reversed(opens):
        if d <= cal_date_yyyymmdd:
            today_td = d
            break
    if today_td is None:
        today_td = opens[-1]
    if today_td not in opens:
        return None, None
    idx = opens.index(today_td)
    if idx <= 0:
        return today_td, None
    return today_td, opens[idx - 1]


def _load_limit_up(pro: Any, trade_date: str) -> List[Dict[str, Any]]:
    try:
        df = pro.limit_list_d(trade_date=trade_date, limit_type="U")
    except Exception:
        df = None
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        code = str(r.get("ts_code") or "").strip()
        name = str(r.get("name") or "").strip()
        if not code:
            continue
        if _exclude_stock(code, name):
            continue
        lt = r.get("limit_times")
        try:
            limit_times = int(float(lt)) if lt is not None and str(lt) != "nan" else 1
        except (TypeError, ValueError):
            limit_times = 1
        rows.append({"ts_code": code, "name": name, "limit_times": limit_times})
    return rows


def _ts_code_to_secid(ts_code: str) -> str:
    num = ts_code.split(".")[0]
    if num.startswith("6"):
        return f"1.{num}"
    return f"0.{num}"


def _limit_threshold_pct(ts_code: str) -> float:
    """近似涨停阈值（%），用于盘中东财 f3 与现价对比。"""
    n = ts_code.split(".")[0]
    if n.startswith(("300", "301", "688", "689")):
        return 19.5
    if n.startswith(("8", "43", "87", "92")):
        return 29.5
    return 9.45


def _em_pct_map(ts_codes: List[str]) -> Dict[str, float]:
    """东财 ulist 批量拉 f3（涨跌幅%）。"""
    out: Dict[str, float] = {}
    if not ts_codes:
        return out
    proxies = {"http": None, "https": None}
    # 去重保序
    seen: Set[str] = set()
    uniq: List[str] = []
    for c in ts_codes:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    chunk = 120
    for i in range(0, len(uniq), chunk):
        part = uniq[i : i + chunk]
        secids = ",".join(_ts_code_to_secid(c) for c in part)
        try:
            r = requests.get(
                _EM_ULIST,
                params={
                    "secids": secids,
                    "fields": "f12,f14,f3",
                    "fltt": 2,
                    "invt": 2,
                    "ut": _EM_UT,
                },
                headers=_EM_HEADERS,
                timeout=20,
                proxies=proxies,
            )
            if r.status_code != 200:
                continue
            j = r.json() or {}
            diff = (j.get("data") or {}).get("diff")
            if diff is None:
                continue
            if isinstance(diff, dict):
                diff = list(diff.values())
            for it in diff:
                f12 = str(it.get("f12") or "").strip()
                f3 = it.get("f3")
                if not f12:
                    continue
                suf = ".SH" if f12.startswith("6") else ".SZ"
                tc = f"{f12.zfill(6)}{suf}"
                try:
                    pct = float(f3) if f3 is not None else 0.0
                except (TypeError, ValueError):
                    pct = 0.0
                out[tc] = pct
        except Exception:
            continue
    return out


def fetch_promotion_rates(cal_date_yyyymmdd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    计算全市场：
    - 昨日涨停 → 今日继续涨停 晋级率
    - 昨日首板 → 今日继续涨停 晋级率

    返回 dict 或 None（接口失败/无数据）。
    """
    pro = _get_pro()
    if not pro:
        return None
    if not cal_date_yyyymmdd:
        cal_date_yyyymmdd = datetime.now().strftime("%Y%m%d")
    today_td, prev_td = _cal_today_prev_trade_days(pro, cal_date_yyyymmdd)
    if not today_td or not prev_td:
        return None
    if today_td == prev_td:
        return None

    prev_rows = _load_limit_up(pro, prev_td)
    if not prev_rows:
        return {
            "today_trade": today_td,
            "prev_trade": prev_td,
            "n_prev_zt": 0,
            "n_prev_sb": 0,
            "n_promoted_zt": 0,
            "n_promoted_sb": 0,
            "rate_zt_pct": None,
            "rate_sb_pct": None,
            "note": "昨日无涨停样本（或接口为空）",
            "source": "tushare_limit_list_d+em",
        }

    prev_zt_codes = [r["ts_code"] for r in prev_rows]
    prev_sb_codes = [r["ts_code"] for r in prev_rows if int(r.get("limit_times") or 1) == 1]
    prev_zt_set = set(prev_zt_codes)

    today_list_codes: Set[str] = set()
    try:
        df_today = pro.limit_list_d(trade_date=today_td, limit_type="U")
        if df_today is not None and not df_today.empty:
            for _, r in df_today.iterrows():
                c = str(r.get("ts_code") or "").strip()
                n = str(r.get("name") or "")
                if c and not _exclude_stock(c, n):
                    today_list_codes.add(c)
    except Exception:
        pass

    pct_map = _em_pct_map(prev_zt_codes)

    def is_still_limit_up(ts_code: str) -> bool:
        if ts_code in today_list_codes:
            return True
        pct = pct_map.get(ts_code)
        if pct is None:
            return False
        return pct >= _limit_threshold_pct(ts_code) - 1e-6

    pz = sum(1 for c in prev_zt_set if is_still_limit_up(c))
    sb_set = set(prev_sb_codes)
    ps = sum(1 for c in sb_set if is_still_limit_up(c))

    nz = len(prev_zt_set)
    ns = len(sb_set)
    rate_zt = (pz / nz * 100.0) if nz else None
    rate_sb = (ps / ns * 100.0) if ns else None

    note_parts = []
    if today_list_codes:
        note_parts.append(f"今日涨停池已匹配 {len(today_list_codes & prev_zt_set)}/{nz} 只")
    else:
        note_parts.append("今日涨停池接口暂无或未更新，晋级以东财涨跌幅阈值为主")
    note = "；".join(note_parts)

    return {
        "today_trade": today_td,
        "prev_trade": prev_td,
        "n_prev_zt": nz,
        "n_prev_sb": ns,
        "n_promoted_zt": pz,
        "n_promoted_sb": ps,
        "rate_zt_pct": rate_zt,
        "rate_sb_pct": rate_sb,
        "note": note,
        "source": "tushare_limit_list_d+em_ulist",
    }


def promotion_md_rows(promo: Optional[Dict[str, Any]]) -> List[str]:
    """Markdown 表行（无表头）。"""
    if not promo:
        return [
            "| 全市场涨停晋级 / 首板晋级 | — | `fetch_promotion_rates` 失败（tushare/网络） |"
        ]
    if promo.get("n_prev_zt") == 0:
        return [
            f"| 全市场涨停晋级 / 首板晋级 | — | {promo.get('note', '无样本')} |"
        ]
    rz = promo.get("rate_zt_pct")
    rs = promo.get("rate_sb_pct")
    prev = promo.get("prev_trade", "")
    pz, nz = promo.get("n_promoted_zt"), promo.get("n_prev_zt")
    ps, ns = promo.get("n_promoted_sb"), promo.get("n_prev_sb")
    note = promo.get("note", "")
    out: List[str] = []
    if rz is not None:
        out.append(
            f"| 涨停晋级（昨涨停→今仍涨停） | **{pz}/{nz}={rz:.1f}%** | "
            f"基准 {prev}；{note}；{promo.get('source', '')} |"
        )
    if rs is not None and ns:
        out.append(
            f"| 首板晋级（昨首板→今仍涨停） | **{ps}/{ns}={rs:.1f}%** | "
            "样本为昨日 limit_list_d 中 limit_times=1；剔除 ST、北交所 |"
        )
    return out if out else [
        "| 全市场涨停晋级 / 首板晋级 | — | 数据异常 |"
    ]


def format_promotion_line(promo: Optional[Dict[str, Any]]) -> str:
    """供简报一行展示。"""
    if not promo:
        return "昨日首板/涨停晋级率：拉取失败（请检查 tushare/chinadata 与网络）"
    if promo.get("n_prev_zt") == 0:
        return f"昨日首板/涨停晋级率：—（{promo.get('note', '无样本')}）"
    rz = promo.get("rate_zt_pct")
    rs = promo.get("rate_sb_pct")
    pz = promo.get("n_promoted_zt")
    nz = promo.get("n_prev_zt")
    ps = promo.get("n_promoted_sb")
    ns = promo.get("n_prev_sb")
    prev_d = promo.get("prev_trade", "")
    if rz is None:
        return "昨日首板/涨停晋级率：—"
    zt_s = f"涨停晋级 {pz}/{nz}={rz:.1f}%（基准日{prev_d}）"
    if ns and rs is not None:
        sb_s = f"首板晋级 {ps}/{ns}={rs:.1f}%"
        return f"昨日首板/涨停晋级率：{zt_s}；{sb_s}"
    return f"昨日首板/涨停晋级率：{zt_s}"
