# -*- coding: utf-8 -*-
"""
一进二盘前准备（参数缓存）
运行时机：09:00~09:20，竞价开始前
用法：python 928_prepare.py
      python 928_prepare.py --date 20260415   # 回测/补跑

输出：928_cache_YYYYMMDD.json（同目录），供 928_run.py 读取
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

import chinadata.ca_data as ts
import chinamindata.min as tss

from first_board_pool_data import (
    fetch_auction_pool_only,
    fetch_daily_basic_pool,
    fetch_hist_pool_parallel,
)

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"
TOKEN_MIN = "ne34e6697159de73c228e34379b510ec554"

DIR = os.path.dirname(os.path.abspath(__file__))

# ── 参考样本（全部为锚定）──────────────────────────────────────
ANCHORS = [
    {"trade_date": "20260410", "ts_code": "600743.SH", "name": "华远控股"},
    {"trade_date": "20260410", "ts_code": "002824.SZ", "name": "和胜股份"},
    {"trade_date": "20260413", "ts_code": "002418.SZ", "name": "康盛股份"},
    {"trade_date": "20260415", "ts_code": "600664.SH", "name": "哈药股份"},
    {"trade_date": "20260417", "ts_code": "605388.SH", "name": "均瑶健康"},
    {"trade_date": "20260420", "ts_code": "002217.SZ", "name": "合力泰"},
    {"trade_date": "20260421", "ts_code": "002081.SZ", "name": "金螳螂"},
    {"trade_date": "20260422", "ts_code": "600103.SH", "name": "青山纸业"},
    {"trade_date": "20260422", "ts_code": "603178.SH", "name": "圣龙股份"},
]
REFERENCE_CASES = ANCHORS
ROUND_STEP = {"pct": 0.1, "amount": 0.01, "turn": 0.01}
LOOSE_LOWER = 0.30
LOOSE_UPPER = 0.50
PROTOTYPE_FEATURES = [
    "auction_pct",
    "auction_amount_yi",
    "turnover_rate",
    "pct_rank_ratio",
    "turn_rank_ratio",
    "amt_rank_ratio",
    "prev_5d",
    "prev_10d",
]


# ── 工具 ────────────────────────────────────────────────────
def retry(fn, *a, n=4, sleep=1.5, **kw):
    last = None
    for i in range(n):
        try:
            return fn(*a, **kw)
        except Exception as e:
            last = e
            time.sleep(sleep * (i + 1))
    raise last


def _invoke(fn, *args, **kwargs):
    return retry(fn, *args, **kwargs)


def is_mainboard(code: str) -> bool:
    if code.endswith(".BJ"):
        return False
    c = code.split(".")[0]
    return not c.startswith(("300", "301", "688", "689"))


def get_trade_dates(pro, dates: list[str]) -> list[str]:
    all_dt = sorted(dates)
    start = (datetime.strptime(all_dt[0], "%Y%m%d") - timedelta(days=90)).strftime("%Y%m%d")
    end = all_dt[-1]
    cal = retry(pro.trade_cal, exchange="SSE", start_date=start, end_date=end, fields="cal_date,is_open")
    return sorted(cal[cal["is_open"] == 1]["cal_date"].astype(str).tolist())


def prev_dates(trade_dates: list[str], date: str) -> tuple[str, str]:
    pos = trade_dates.index(date)
    if pos < 2:
        raise ValueError(f"{date} 前方交易日不足 2 个")
    return trade_dates[pos - 1], trade_dates[pos - 2]


def get_name_st_maps(pro):
    df = retry(pro.stock_basic, exchange="", list_status="L", fields="ts_code,name")
    name_map = dict(zip(df["ts_code"], df["name"]))
    st_set = {
        r.ts_code
        for r in df.itertuples(index=False)
        if "ST" in str(r.name).upper() or "*" in str(r.name)
    }
    return name_map, st_set


# ── 参考日：全量拉取（含竞价），用于推导参数 ─────────────────────
def collect_reference_day(
    pro, pro_min, trade_dates, name_map, st_set, trade_date
) -> Optional[dict[str, Any]]:
    prev_d, prev2_d = prev_dates(trade_dates, trade_date)
    zt_prev = retry(pro.limit_list_d, trade_date=prev_d, limit_type="U")
    zt_prev2 = retry(pro.limit_list_d, trade_date=prev2_d, limit_type="U")
    prev2_set = set(zt_prev2["ts_code"]) if zt_prev2 is not None and not zt_prev2.empty else set()
    if zt_prev is None or zt_prev.empty:
        return None

    first_board = zt_prev[
        (zt_prev["limit_times"] == 1)
        & (~zt_prev["ts_code"].isin(prev2_set))
        & (zt_prev["ts_code"].map(is_mainboard))
        & (~zt_prev["ts_code"].isin(st_set))
    ].copy()
    second_board = zt_prev[
        (zt_prev["limit_times"] == 2)
        & (zt_prev["ts_code"].map(is_mainboard))
        & (~zt_prev["ts_code"].isin(st_set))
    ].copy()
    third_board = zt_prev[
        (zt_prev["limit_times"] == 3)
        & (zt_prev["ts_code"].map(is_mainboard))
        & (~zt_prev["ts_code"].isin(st_set))
    ].copy()
    pool = pd.concat([first_board, second_board, third_board], ignore_index=True).drop_duplicates(subset=["ts_code"]).copy()
    if pool.empty:
        return None

    pool["name"] = pool["ts_code"].map(name_map)
    pool_codes = pool["ts_code"].tolist()

    auc = fetch_auction_pool_only(pro_min, trade_date, pool_codes, _invoke, log_fallback=False)
    if auc.empty:
        return None

    basic = fetch_daily_basic_pool(pro, prev_d, pool_codes, _invoke)
    start_hist = (datetime.strptime(prev_d, "%Y%m%d") - timedelta(days=180)).strftime("%Y%m%d")
    hist = fetch_hist_pool_parallel(pro, pool_codes, start_hist, prev_d, _invoke, progress=False)

    return {"trade_date": trade_date, "pool": pool, "auction": auc, "basic": basic, "hist": hist}


# ── 今日：只拉首板池 + 历史特征，不拉竞价（竞价未出）────────────
def collect_today_pool(
    pro, trade_dates, name_map, st_set, trade_date
) -> Optional[dict[str, Any]]:
    prev_d, prev2_d = prev_dates(trade_dates, trade_date)
    zt_prev = retry(pro.limit_list_d, trade_date=prev_d, limit_type="U")
    zt_prev2 = retry(pro.limit_list_d, trade_date=prev2_d, limit_type="U")
    prev2_set = set(zt_prev2["ts_code"]) if zt_prev2 is not None and not zt_prev2.empty else set()
    if zt_prev is None or zt_prev.empty:
        return None

    first_board = zt_prev[
        (zt_prev["limit_times"] == 1)
        & (~zt_prev["ts_code"].isin(prev2_set))
        & (zt_prev["ts_code"].map(is_mainboard))
        & (~zt_prev["ts_code"].isin(st_set))
    ].copy()
    second_board = zt_prev[
        (zt_prev["limit_times"] == 2)
        & (zt_prev["ts_code"].map(is_mainboard))
        & (~zt_prev["ts_code"].isin(st_set))
    ].copy()
    third_board = zt_prev[
        (zt_prev["limit_times"] == 3)
        & (zt_prev["ts_code"].map(is_mainboard))
        & (~zt_prev["ts_code"].isin(st_set))
    ].copy()
    pool = pd.concat([first_board, second_board, third_board], ignore_index=True).drop_duplicates(subset=["ts_code"]).copy()
    if pool.empty:
        return None

    pool["name"] = pool["ts_code"].map(name_map)
    pool_codes = pool["ts_code"].tolist()

    start_hist = (datetime.strptime(prev_d, "%Y%m%d") - timedelta(days=180)).strftime("%Y%m%d")
    hist = fetch_hist_pool_parallel(pro, pool_codes, start_hist, prev_d, _invoke, progress=True)
    return {"trade_date": trade_date, "prev_date": prev_d, "pool": pool, "hist": hist}


# ── 宽表构建（参考日用）────────────────────────────────────────
def build_ref_df(day: dict[str, Any]) -> Optional[pd.DataFrame]:
    df = day["pool"].merge(day["auction"], on="ts_code", how="left")
    df = df.merge(day["basic"][["ts_code", "circ_mv_yi"]], on="ts_code", how="left")
    df = df.merge(day["hist"], on="ts_code", how="left")
    if df.empty:
        return None

    for col in ["price", "high20", "high60", "auction_pct", "auction_amount_yi",
                "turnover_rate", "prev_5d", "prev_10d",
                "fd_amount", "first_time", "last_time", "open_times", "turnover_ratio"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["pct_rank"] = df["auction_pct"].rank(method="min", ascending=False)
    df["turn_rank"] = df["turnover_rate"].rank(method="min", ascending=False)
    df["amt_rank"] = df["auction_amount_yi"].rank(method="min", ascending=False)
    n_pct = max(int(df["auction_pct"].notna().sum()), 1)
    n_turn = max(int(df["turnover_rate"].notna().sum()), 1)
    n_amt = max(int(df["auction_amount_yi"].notna().sum()), 1)
    df["pct_rank_ratio"] = df["pct_rank"] / n_pct
    df["turn_rank_ratio"] = df["turn_rank"] / n_turn
    df["amt_rank_ratio"] = df["amt_rank"] / n_amt
    df["auction_new20"] = df["price"] >= df["high20"]
    df["auction_new60"] = df["price"] >= df["high60"]
    return df


# ── 参数推导 ────────────────────────────────────────────────
def round_down(value: float, step: float) -> float:
    return round(math.floor((float(value) + 1e-9) / step) * step, 6)


def round_up(value: float, step: float) -> float:
    return round(math.ceil((float(value) - 1e-9) / step) * step, 6)


def get_reference_rows(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    required = ["auction_pct", "auction_amount_yi", "turnover_rate",
                "pct_rank_ratio", "turn_rank_ratio", "amt_rank_ratio", "prev_5d", "prev_10d"]
    rows = []
    for case in REFERENCE_CASES:
        df = dfs.get(case["trade_date"])
        if df is None or df.empty:
            raise SystemExit(f"缺少参考日数据: {case['trade_date']}")
        row = df[df["ts_code"] == case["ts_code"]]
        if row.empty:
            raise SystemExit(f"参考样本未命中: {case['trade_date']} {case['ts_code']}")
        rows.append(row.iloc[0])
    out = pd.DataFrame(rows).reset_index(drop=True)
    for col in required:
        if out[col].isna().any():
            raise SystemExit(f"参考样本字段缺失: {col}")
    return out


def derive_params(ref_rows: pd.DataFrame) -> dict[str, Any]:
    """宽松包络（降级用）：与 构建一进二选股规则.py 保持同一哲学。"""
    new_high = ref_rows["auction_new20"] | ref_rows["auction_new60"]
    params: dict[str, Any] = {
        "pct_min": round_down(float(ref_rows["auction_pct"].min()) * (1 - LOOSE_LOWER), ROUND_STEP["pct"]),
        "pct_max": round_up(float(ref_rows["auction_pct"].max()) * (1 + LOOSE_UPPER), ROUND_STEP["pct"]),
        "amount_min": round_down(float(ref_rows["auction_amount_yi"].min()) * (1 - LOOSE_LOWER), ROUND_STEP["amount"]),
        "turn_min": round_down(float(ref_rows["turnover_rate"].min()) * (1 - LOOSE_LOWER), ROUND_STEP["turn"]),
        # turn_max 已删除
        "pct_rank_ratio_max": round_up(float(ref_rows["pct_rank_ratio"].max()) * (1 + LOOSE_UPPER), 0.01),
        "turn_rank_ratio_max": round_up(float(ref_rows["turn_rank_ratio"].max()) * (1 + LOOSE_UPPER), 0.01),
        "amt_rank_ratio_max": round_up(float(ref_rows["amt_rank_ratio"].max()) * (1 + LOOSE_UPPER), 0.01),
        "prev5_max": int(math.ceil(float(ref_rows["prev_5d"].max()) * (1 + LOOSE_UPPER))),
        "prev10_max": int(math.ceil(float(ref_rows["prev_10d"].max()) * (1 + LOOSE_UPPER))),
        "need_new_high": bool(new_high.all()),
    }
    if "open_times" in ref_rows.columns and ref_rows["open_times"].notna().all():
        params["open_times_max"] = int(math.ceil(float(ref_rows["open_times"].max()))) + 2
    # fd_amount_min / first_time_max 已删除（过拟合）
    return params


def build_prototype(ref_rows: pd.DataFrame) -> dict[str, dict[str, float]]:
    """计算参考样本的原型中心与归一化尺度，供 928_run.py 排序使用。"""
    center: dict[str, float] = {}
    scale: dict[str, float] = {}
    for f in PROTOTYPE_FEATURES:
        if f not in ref_rows.columns:
            continue
        center[f] = float(ref_rows[f].median())
        span = float(ref_rows[f].max()) - float(ref_rows[f].min())
        scale[f] = span if (not pd.isna(span) and span > 1e-6) else 1e-6
    return {"center": center, "scale": scale}


def _load_rule_params() -> tuple[dict | None, dict | None]:
    """尝试从 rule_params.json 读取已收紧的参数与原型，失败返回 (None, None)。"""
    rule_path = os.path.join(DIR, "rule_params.json")
    if not os.path.exists(rule_path):
        return None, None
    try:
        with open(rule_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("params"), data.get("prototype")
    except Exception as e:
        print(f"  [警告] rule_params.json 读取失败: {e}")
        return None, None


# ── 主流程 ───────────────────────────────────────────────────
def run(today: str):
    print(f"\n{'='*55}")
    print(f"  一进二 盘前准备  |  {today}")
    print(f"{'='*55}")

    ts.set_token(TOKEN)
    tss.set_token(TOKEN_MIN)
    pro = ts.pro_api()
    pro_min = tss.pro_api()

    all_dates = sorted({today, *[x["trade_date"] for x in REFERENCE_CASES]})
    trade_dates = get_trade_dates(pro, all_dates)
    if today not in trade_dates:
        print(f"[警告] {today} 不是交易日，退出。")
        return

    name_map, st_set = get_name_st_maps(pro)

    # 1. 优先从 rule_params.json 读取已收紧参数（由 构建一进二选股规则.py 生成）
    saved_params, saved_prototype = _load_rule_params()
    if saved_params is not None and saved_prototype is not None:
        params = saved_params
        prototype = saved_prototype
        print(f"\n  [参数来源] rule_params.json（已含反例收紧）")
    else:
        # 降级：重新拉参考日推导（不含反例收紧）
        print(f"\n  [参数来源] 重新从参考日推导（rule_params.json 不可用）")
        ref_dates = sorted({x["trade_date"] for x in REFERENCE_CASES})
        ref_dfs: dict[str, pd.DataFrame] = {}
        for td in ref_dates:
            print(f"\n[参考日] {td}")
            day = collect_reference_day(pro, pro_min, trade_dates, name_map, st_set, td)
            if not day:
                raise SystemExit(f"{td} 参考日取数失败或池为空")
            df = build_ref_df(day)
            if df is None or df.empty:
                raise SystemExit(f"{td} 参考日宽表构建失败")
            ref_dfs[td] = df
            print(f"  首板池 {len(day['pool'])} 只，竞价有数 {len(day['auction'])} 只")

        ref_rows = get_reference_rows(ref_dfs)
        params = derive_params(ref_rows)
        prototype = build_prototype(ref_rows)

    print(f"\n  推导参数: 竞价[{params['pct_min']}%,{params['pct_max']}%]  "
          f"额≥{params['amount_min']}亿  换手≥{params['turn_min']}%  新高={params['need_new_high']}")
    print(f"  名次占比: 涨≤{params['pct_rank_ratio_max']:.2f}  "
          f"换≤{params['turn_rank_ratio_max']:.2f}  额≤{params['amt_rank_ratio_max']:.2f}")
    qual_parts = []
    if params.get("open_times_max") is not None:
        qual_parts.append(f"开板次数≤{params['open_times_max']}")
    if params.get("fd_amount_min") is not None:
        qual_parts.append(f"封单≥{params['fd_amount_min']}亿")
    if params.get("first_time_max") is not None:
        qual_parts.append(f"封板时间≤{params['first_time_max']:.0f}")
    if qual_parts:
        print(f"  质量维: {' '.join(qual_parts)}")

    # 2. 拉今日首板池 + 历史特征（不拉竞价）
    print(f"\n[今日池] {today}")
    today_raw = collect_today_pool(pro, trade_dates, name_map, st_set, today)
    if not today_raw:
        raise SystemExit(f"{today} 今日首板池为空或取数失败")

    pool_df = today_raw["pool"].merge(today_raw["hist"], on="ts_code", how="left")
    for col in ["high20", "high60", "prev_5d", "prev_10d",
                "fd_amount", "first_time", "last_time", "open_times", "turnover_ratio"]:
        if col in pool_df.columns:
            pool_df[col] = pd.to_numeric(pool_df[col], errors="coerce")

    pool_records = []
    for _, r in pool_df.iterrows():
        pool_records.append({
            "ts_code": r["ts_code"],
            "name": str(r.get("name", "")),
            "fd_amount": (float(r["fd_amount"]) if pd.notna(r.get("fd_amount")) else None),
            "first_time": (float(r["first_time"]) if pd.notna(r.get("first_time")) else None),
            "last_time": (float(r["last_time"]) if pd.notna(r.get("last_time")) else None),
            "open_times": (int(r["open_times"]) if pd.notna(r.get("open_times")) else 0),
            "turnover_ratio": (float(r["turnover_ratio"]) if pd.notna(r.get("turnover_ratio")) else None),
            "high20": (float(r["high20"]) if pd.notna(r.get("high20")) else None),
            "high60": (float(r["high60"]) if pd.notna(r.get("high60")) else None),
            "prev_5d": (float(r["prev_5d"]) if pd.notna(r.get("prev_5d")) else None),
            "prev_10d": (float(r["prev_10d"]) if pd.notna(r.get("prev_10d")) else None),
        })
    print(f"  今日首板池: {len(pool_records)} 只")

    # 3. 写缓存
    cache = {
        "trade_date": today,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": params,
        "prototype": prototype,
        "pool": pool_records,
    }
    cache_path = os.path.join(DIR, f"928_cache_{today}.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] 缓存写入: {cache_path}（含原型向量 {len(prototype.get('center', {}))} 维）")
    print(f"{'='*55}\n")


def main():
    ap = argparse.ArgumentParser(description="一进二盘前准备（参数缓存）")
    ap.add_argument("--date", default=None, help="指定交易日 YYYYMMDD，默认今日")
    args = ap.parse_args()
    today = args.date or datetime.now().strftime("%Y%m%d")
    run(today)


if __name__ == "__main__":
    main()
