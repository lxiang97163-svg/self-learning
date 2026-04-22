# -*- coding: utf-8 -*-
"""
首板池专用数据拉取：只请求池内标的，避免全市场 stk_auction / daily_basic / daily 大查询。

invoke：由调用方传入，与各自脚本的 retry / retry_call 对齐，签名为 invoke(api, *args, **kwargs)。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

import pandas as pd

# 竞价接口在过高并发下会返回仅含 error 列的非空表；压低并行并在兜底时退避重试。
AUCTION_PARALLEL_WORKERS = 6


def is_valid_auction_frame(df: Optional[pd.DataFrame]) -> bool:
    if df is None or df.empty:
        return False
    need = ("ts_code", "pre_close", "price", "amount")
    if not all(c in df.columns for c in need):
        return False
    return True


def _auction_with_derived(auc: pd.DataFrame) -> pd.DataFrame:
    if "turnover_rate" not in auc.columns:
        auc = auc.copy()
        auc["turnover_rate"] = 0.0
    auc = auc[["ts_code", "pre_close", "price", "amount", "turnover_rate"]].copy()
    auc["auction_pct"] = (auc["price"] / auc["pre_close"] - 1) * 100
    auc["auction_amount_yi"] = auc["amount"] / 1e8
    auc["turnover_rate"] = pd.to_numeric(auc["turnover_rate"], errors="coerce").fillna(0.0)
    for col in ("price", "pre_close", "amount", "auction_pct", "auction_amount_yi"):
        auc[col] = pd.to_numeric(auc[col], errors="coerce")
    return auc


def fetch_auction_pool_only(
    pro_min: Any,
    trade_date: str,
    pool_codes: list[str],
    invoke: Callable[..., Any],
    *,
    log_fallback: bool = True,
) -> pd.DataFrame:
    """只保留池内竞价：优先单次全市场（一次 HTTP，避免先并发按代码刷屏限流）；不足再低并发按代码补。"""
    if not pool_codes:
        return pd.DataFrame()

    pool_set = set(pool_codes)
    need_n = max(1, len(pool_codes) // 4)

    def try_full_market() -> Optional[pd.DataFrame]:
        for attempt in range(5):
            if attempt:
                time.sleep(2.5 * attempt)
            raw = invoke(pro_min.stk_auction, trade_date=trade_date)
            if is_valid_auction_frame(raw):
                return raw
        return None

    def one(code: str) -> Optional[pd.DataFrame]:
        try:
            df = invoke(pro_min.stk_auction, trade_date=trade_date, ts_code=code)
            if is_valid_auction_frame(df):
                return df
        except TypeError:
            return None
        except Exception:
            return None
        return None

    auc_full = try_full_market()
    if auc_full is not None:
        sub = auc_full[auc_full["ts_code"].isin(pool_set)].copy()
        if len(sub) >= need_n:
            if log_fallback:
                print(f"  [竞价] 全市场一次拉取，池内命中 {len(sub)}/{len(pool_codes)}")
            return _auction_with_derived(sub)

    time.sleep(1.5)
    parts: list[pd.DataFrame] = []
    max_w = min(AUCTION_PARALLEL_WORKERS, max(1, len(pool_codes)))
    with ThreadPoolExecutor(max_workers=max_w) as ex:
        futs = [ex.submit(one, c) for c in pool_codes]
        for fut in as_completed(futs):
            d = fut.result()
            if d is not None and is_valid_auction_frame(d):
                parts.append(d)

    if parts:
        merged = pd.concat(parts, ignore_index=True)
        if is_valid_auction_frame(merged):
            merged = merged.drop_duplicates(subset=["ts_code"], keep="last")
            if len(merged) >= need_n:
                if log_fallback:
                    print(f"  [竞价] 按代码低并发合并 {len(merged)}/{len(pool_codes)}")
                return _auction_with_derived(merged)
            if len(merged) > 0:
                if log_fallback:
                    print(
                        f"  [竞价] 按代码仅命中 {len(merged)}/{len(pool_codes)}，低于阈值仍采用"
                    )
                return _auction_with_derived(merged)

    if auc_full is not None:
        sub = auc_full[auc_full["ts_code"].isin(pool_set)].copy()
        if not sub.empty:
            if log_fallback:
                print(
                    f"  [竞价] 全市场结果池内仅 {len(sub)} 只（低于 {need_n} 阈值仍采用）"
                )
            return _auction_with_derived(sub)

    if log_fallback:
        print("  [竞价] 拉取失败（可能限流或池内无竞价数据），可稍后重试")
    return pd.DataFrame()


def fetch_daily_basic_pool(
    pro: Any,
    prev_d: str,
    pool_codes: list[str],
    invoke: Callable[..., Any],
) -> pd.DataFrame:
    """仅首板池 daily_basic，并行按代码请求。"""
    if not pool_codes:
        return pd.DataFrame(columns=["ts_code", "circ_mv_yi", "prev_close"])

    def one(code: str) -> Optional[pd.DataFrame]:
        try:
            return invoke(
                pro.daily_basic,
                ts_code=code,
                trade_date=prev_d,
                fields="ts_code,circ_mv,close",
            )
        except Exception:
            return None

    parts: list[pd.DataFrame] = []
    max_w = min(16, max(1, len(pool_codes)))
    with ThreadPoolExecutor(max_workers=max_w) as ex:
        futs = [ex.submit(one, c) for c in pool_codes]
        for fut in as_completed(futs):
            d = fut.result()
            if d is not None and not d.empty:
                parts.append(d)

    if not parts:
        return pd.DataFrame(columns=["ts_code", "circ_mv_yi", "prev_close"])
    basic = pd.concat(parts, ignore_index=True)
    basic["circ_mv_yi"] = pd.to_numeric(basic["circ_mv"], errors="coerce") / 10000
    basic["prev_close"] = pd.to_numeric(basic["close"], errors="coerce")
    return basic[["ts_code", "circ_mv_yi", "prev_close"]]


def fetch_hist_pool_parallel(
    pro: Any,
    pool_codes: list[str],
    start_hist: str,
    prev_d: str,
    invoke: Callable[..., Any],
    *,
    progress: bool = True,
) -> pd.DataFrame:
    """首板池历史特征，并行 daily。"""

    def one(code: str) -> dict:
        hist = invoke(
            pro.daily,
            ts_code=code,
            start_date=start_hist,
            end_date=prev_d,
            fields="ts_code,trade_date,high,close",
        )
        h5 = h10 = high20 = high60 = None
        if hist is not None and not hist.empty:
            hist = hist.sort_values("trade_date").reset_index(drop=True)
            last_c = float(hist.iloc[-1]["close"])
            if len(hist) >= 6:
                h5 = (last_c / float(hist.iloc[-6]["close"]) - 1) * 100
            if len(hist) >= 11:
                h10 = (last_c / float(hist.iloc[-11]["close"]) - 1) * 100
            if len(hist) >= 20:
                high20 = float(hist.tail(20)["high"].max())
            if len(hist) >= 60:
                high60 = float(hist.tail(60)["high"].max())
        return {"ts_code": code, "prev_5d": h5, "prev_10d": h10, "high20": high20, "high60": high60}

    rows: list[dict] = []
    max_w = min(12, max(1, len(pool_codes)))
    with ThreadPoolExecutor(max_workers=max_w) as ex:
        futs = [ex.submit(one, c) for c in pool_codes]
        for i, fut in enumerate(as_completed(futs)):
            rows.append(fut.result())
            if progress and (i + 1) % 20 == 0:
                print(f"    历史进度: {i+1}/{len(pool_codes)}", end="\r")
    return pd.DataFrame(rows)


def fetch_close_pool_parallel(
    pro: Any,
    trade_date: str,
    pool_codes: list[str],
    invoke: Callable[..., Any],
) -> dict[str, dict]:
    """仅池内当日收盘（事后验证），禁止不带 ts_code 的 daily(trade_date) 全市场。"""

    def one(code: str) -> tuple[str, Optional[dict]]:
        try:
            d = invoke(
                pro.daily,
                ts_code=code,
                trade_date=trade_date,
                fields="ts_code,open,close,pct_chg",
            )
            if d is None or d.empty:
                return code, None
            row = d.iloc[0]
            return code, {
                "close": float(row.close),
                "open": float(row.open),
                "pct_chg": float(row.pct_chg),
            }
        except Exception:
            return code, None

    close_map: dict[str, dict] = {}
    max_w = min(16, max(1, len(pool_codes)))
    with ThreadPoolExecutor(max_workers=max_w) as ex:
        futs = [ex.submit(one, c) for c in pool_codes]
        for fut in as_completed(futs):
            code, info = fut.result()
            if info is not None:
                close_map[code] = info
    return close_map


# ── chinamindata.stk_auction 兼容：API 单条返回 dict 时原库 pd.DataFrame(data) 会报错 ──
def _patch_chinamindata_stk_auction() -> None:
    try:
        import requests
        import chinamindata.china_min_now as cm
        import chinamindata.min as tsm
    except ImportError:
        return

    def stk_auction_1(**kwargs):
        from chinamindata.c_min import get_token
        from chinamindata.china_list import url2

        url = "http://" + url2 + ":9002/c_min_now/" + get_token()
        response = requests.get(url, params=kwargs, timeout=120)
        if response.status_code == 200:
            try:
                data = response.json()
                if data == "token无效或已超期,请重新购买":
                    return data
                if isinstance(data, dict):
                    return pd.DataFrame([data])
                return pd.DataFrame(data)
            except ValueError as e:
                print("Error parsing JSON response:", e)
                return None
        else:
            print(f"Failed to fetch data. Status code: {response.status_code}")
            print(response.text)
            return None

    cm.stk_auction_1 = stk_auction_1
    tsm.stk_auction_1 = stk_auction_1


_patch_chinamindata_stk_auction()
