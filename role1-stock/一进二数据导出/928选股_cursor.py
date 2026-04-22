# -*- coding: utf-8 -*-
"""
9:28 一进二实盘选股（Cursor 规则版）

区别于旧版 928 逻辑：
1. 参数来自当前 cursor 规则口径
2. 排名条件使用池内名次占比，而不是跨日绝对名次
3. 增加竞价新高约束
4. 命中结果按原型距离排序，而不是按竞价涨幅优先
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
    "prev_auction_pct",
    "auction_price_ratio",
]


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


def prev_dates(trade_dates_sorted: list[str], date: str) -> tuple[str, str]:
    pos = trade_dates_sorted.index(date)
    if pos < 2:
        raise ValueError(f"{date} 前方交易日不足 2 个，无法定位 T-1/T-2")
    return trade_dates_sorted[pos - 1], trade_dates_sorted[pos - 2]


def get_name_st_maps(pro):
    df = retry(pro.stock_basic, exchange="", list_status="L", fields="ts_code,name")
    name_map = dict(zip(df["ts_code"], df["name"]))
    st_set = {
        r.ts_code
        for r in df.itertuples(index=False)
        if "ST" in str(r.name).upper() or "*" in str(r.name)
    }
    return name_map, st_set


def collect_day(
    pro,
    pro_min,
    trade_dates: list[str],
    name_map: dict[str, str],
    st_set: set[str],
    trade_date: str,
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

    # T-1 竞价：用于计算 prev_auction_pct / prev_auction_price（今昨竞价比）
    prev_auc = fetch_auction_pool_only(pro_min, prev_d, pool_codes, _invoke, log_fallback=False)
    basic = fetch_daily_basic_pool(pro, prev_d, pool_codes, _invoke)
    start_hist = (datetime.strptime(prev_d, "%Y%m%d") - timedelta(days=180)).strftime("%Y%m%d")
    hist = fetch_hist_pool_parallel(pro, pool_codes, start_hist, prev_d, _invoke, progress=False)
    return {
        "trade_date": trade_date,
        "prev_date": prev_d,
        "pool": pool,
        "auction": auc,
        "prev_auction": prev_auc,
        "basic": basic,
        "hist": hist,
    }


def build_df(day: dict[str, Any]) -> Optional[pd.DataFrame]:
    pool = day["pool"]
    auc = day["auction"]
    basic = day["basic"]
    hist = day["hist"]
    df = pool.merge(auc, on="ts_code", how="left")
    df = df.merge(basic[["ts_code", "circ_mv_yi"]], on="ts_code", how="left")
    df = df.merge(hist, on="ts_code", how="left")
    if df.empty:
        return None

    for col in [
        "price",
        "high20",
        "high60",
        "auction_pct",
        "auction_amount_yi",
        "turnover_rate",
        "prev_5d",
        "prev_10d",
        "fd_amount",
        "first_time",
        "last_time",
        "open_times",
        "turnover_ratio",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 合并 T-1 竞价涨幅 + 竞价价格（今昨竞价比）
    prev_auc = day.get("prev_auction")
    if prev_auc is not None and not prev_auc.empty and "auction_pct" in prev_auc.columns:
        pa_cols = {"auction_pct": "prev_auction_pct"}
        if "price" in prev_auc.columns:
            pa_cols["price"] = "prev_auction_price"
        pa_sub = prev_auc[["ts_code"] + list(pa_cols.keys())].rename(columns=pa_cols)
        df = df.merge(pa_sub, on="ts_code", how="left")
    else:
        df["prev_auction_pct"] = float("nan")
        df["prev_auction_price"] = float("nan")

    for col in ["prev_auction_pct", "prev_auction_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 今日竞价价格 / 昨日竞价价格（价格始终 > 0，无除零问题）
    if "prev_auction_price" in df.columns:
        df["auction_price_ratio"] = df.apply(
            lambda r: r["price"] / r["prev_auction_price"]
            if pd.notna(r.get("prev_auction_price")) and r.get("prev_auction_price", 0) > 0
            else float("nan"),
            axis=1,
        )
    else:
        df["auction_price_ratio"] = float("nan")

    df["pct_rank"] = df["auction_pct"].rank(method="min", ascending=False)
    df["turn_rank"] = df["turnover_rate"].rank(method="min", ascending=False)
    df["amt_rank"] = df["auction_amount_yi"].rank(method="min", ascending=False)
    pct_pool_size = max(int(df["auction_pct"].notna().sum()), 1)
    turn_pool_size = max(int(df["turnover_rate"].notna().sum()), 1)
    amt_pool_size = max(int(df["auction_amount_yi"].notna().sum()), 1)
    df["pct_rank_ratio"] = df["pct_rank"] / pct_pool_size
    df["turn_rank_ratio"] = df["turn_rank"] / turn_pool_size
    df["amt_rank_ratio"] = df["amt_rank"] / amt_pool_size
    df["auction_new20"] = df["price"] >= df["high20"]
    df["auction_new60"] = df["price"] >= df["high60"]
    return df


def round_down(value: float, step: float) -> float:
    if pd.isna(value):
        raise ValueError("round_down 收到 NaN")
    return round(math.floor((float(value) + 1e-9) / step) * step, 6)


def round_up(value: float, step: float) -> float:
    if pd.isna(value):
        raise ValueError("round_up 收到 NaN")
    return round(math.ceil((float(value) - 1e-9) / step) * step, 6)


def safe_ceil_int(value: float, default: Optional[int] = None) -> Optional[int]:
    if pd.isna(value):
        return default
    return int(math.ceil(float(value)))


def get_reference_rows(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.Series] = []
    required_cols = [
        "auction_pct",
        "auction_amount_yi",
        "turnover_rate",
        "pct_rank_ratio",
        "turn_rank_ratio",
        "amt_rank_ratio",
        "prev_5d",
        "prev_10d",
    ]
    for case in REFERENCE_CASES:
        df = dfs.get(case["trade_date"])
        if df is None or df.empty:
            raise SystemExit(f"缺少参考样本所在交易日数据: {case['trade_date']}")
        row = df[df["ts_code"] == case["ts_code"]]
        if row.empty:
            raise SystemExit(f"参考样本未出现在对应交易日池中: {case['trade_date']} {case['ts_code']}")
        rows.append(row.iloc[0])
    out = pd.DataFrame(rows).reset_index(drop=True)
    for col in required_cols:
        if out[col].isna().any():
            bad = out.loc[out[col].isna(), ["ts_code"]].to_dict("records")
            raise SystemExit(f"参考样本关键字段缺失: {col} -> {bad}")
    return out


def derive_params(reference_rows: pd.DataFrame) -> dict[str, Any]:
    """宽松包络（降级用）：与 构建一进二选股规则.py 的 derive_params 保持同一哲学。"""
    new_high_series = reference_rows["auction_new20"] | reference_rows["auction_new60"]
    params: dict[str, Any] = {
        "pct_min": round_down(float(reference_rows["auction_pct"].min()) * (1 - LOOSE_LOWER), ROUND_STEP["pct"]),
        "pct_max": round_up(float(reference_rows["auction_pct"].max()) * (1 + LOOSE_UPPER), ROUND_STEP["pct"]),
        "amount_min": round_down(float(reference_rows["auction_amount_yi"].min()) * (1 - LOOSE_LOWER), ROUND_STEP["amount"]),
        "turn_min": round_down(float(reference_rows["turnover_rate"].min()) * (1 - LOOSE_LOWER), ROUND_STEP["turn"]),
        "pct_rank_ratio_max": round_up(float(reference_rows["pct_rank_ratio"].max()) * (1 + LOOSE_UPPER), 0.01),
        "turn_rank_ratio_max": round_up(float(reference_rows["turn_rank_ratio"].max()) * (1 + LOOSE_UPPER), 0.01),
        "amt_rank_ratio_max": round_up(float(reference_rows["amt_rank_ratio"].max()) * (1 + LOOSE_UPPER), 0.01),
        "prev5_max": int(math.ceil(float(reference_rows["prev_5d"].max()) * (1 + LOOSE_UPPER))),
        "prev10_max": int(math.ceil(float(reference_rows["prev_10d"].max()) * (1 + LOOSE_UPPER))),
        "need_new_high": bool(new_high_series.all()),
    }
    if "open_times" in reference_rows.columns and reference_rows["open_times"].notna().all():
        params["open_times_max"] = int(math.ceil(float(reference_rows["open_times"].max()))) + 2
    if "prev_auction_pct" in reference_rows.columns and reference_rows["prev_auction_pct"].notna().all():
        params["prev_auction_pct_min"] = float(reference_rows["prev_auction_pct"].min()) - 2.0
    # 今昨竞价比：从锚定样本最小值推导（× 0.95 缓冲）
    if "auction_price_ratio" in reference_rows.columns and reference_rows["auction_price_ratio"].notna().all():
        ratio_min_raw = float(reference_rows["auction_price_ratio"].min())
        params["auction_price_ratio_min"] = round_down(ratio_min_raw * (1 - LOOSE_LOWER), 0.01)
    # T-1 封板量占流通股比例：从锚点最小值推导，LOOSE_LOWER 缓冲
    if "turnover_ratio" in reference_rows.columns and reference_rows["turnover_ratio"].notna().any():
        tr_min_raw = float(reference_rows["turnover_ratio"].min())
        params["turnover_ratio_min"] = round_down(tr_min_raw * (1 - LOOSE_LOWER), 0.1)
    # tr_quality = turnover_ratio / turnover_rate：从锚点最小值推导，LOOSE_LOWER 缓冲
    if ("turnover_ratio" in reference_rows.columns and "turnover_rate" in reference_rows.columns
            and reference_rows["turnover_ratio"].notna().any() and reference_rows["turnover_rate"].notna().any()):
        tr_quality_series = reference_rows["turnover_ratio"] / reference_rows["turnover_rate"].clip(lower=0.01)
        params["tr_quality_min"] = round_down(float(tr_quality_series.min()) * (1 - LOOSE_LOWER), 0.1)
    return params


def build_prototype(reference_rows: pd.DataFrame) -> dict[str, dict[str, float]]:
    center = {f: float(reference_rows[f].median()) for f in PROTOTYPE_FEATURES}
    scale = {}
    for f in PROTOTYPE_FEATURES:
        span = float(reference_rows[f].max()) - float(reference_rows[f].min())
        scale[f] = span if (not pd.isna(span) and span > 1e-6) else 1e-6
    return {"center": center, "scale": scale}


def prototype_distance(row: pd.Series, prototype: dict[str, dict[str, float]]) -> float:
    center = prototype["center"]
    scale = prototype["scale"]
    dist = 0.0
    for f in PROTOTYPE_FEATURES:
        val = row.get(f)
        if pd.isna(val) or pd.isna(center[f]):
            dist += 10.0
            continue
        dist += abs(float(val) - center[f]) / scale[f]
    return dist


def apply_strategy(df: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    cond = df["auction_pct"].between(p["pct_min"], p["pct_max"], inclusive="both")
    cond &= df["auction_amount_yi"] >= p["amount_min"]
    cond &= df["turnover_rate"] >= p["turn_min"]
    # turn_max 已删除
    cond &= df["pct_rank_ratio"] <= p["pct_rank_ratio_max"]
    cond &= df["turn_rank_ratio"] <= p["turn_rank_ratio_max"]
    cond &= df["amt_rank_ratio"] <= p["amt_rank_ratio_max"]
    if p.get("prev5_max") is not None:
        cond &= df["prev_5d"] <= p["prev5_max"]
    if p.get("prev10_max") is not None:
        cond &= df["prev_10d"] <= p["prev10_max"]
    if p.get("need_new_high"):
        cond &= df["auction_new20"] | df["auction_new60"]
    if p.get("open_times_max") is not None and "open_times" in df.columns:
        cond &= df["open_times"].fillna(0) <= p["open_times_max"]
    # fd_amount_min / first_time_max 已删除（过拟合）
    if p.get("prev_auction_pct_min") is not None and "prev_auction_pct" in df.columns:
        cond &= df["prev_auction_pct"].fillna(-999) >= p["prev_auction_pct_min"]
    # auction_price_ratio_min：NaN（T-1 竞价数据缺失）自动通过，不误杀
    if p.get("auction_price_ratio_min") is not None and "auction_price_ratio" in df.columns:
        cond &= df["auction_price_ratio"].isna() | (df["auction_price_ratio"] >= p["auction_price_ratio_min"])
    # turnover_ratio_min：T-1 封板量占流通股比例；弱封板 = T 日延续乏力
    if p.get("turnover_ratio_min") is not None and "turnover_ratio" in df.columns:
        cond &= df["turnover_ratio"].fillna(0) >= p["turnover_ratio_min"]
    # tr_quality_min = turnover_ratio / turnover_rate：T-1封板强度/T日竞价压力比
    if p.get("tr_quality_min") is not None and "turnover_ratio" in df.columns and "turnover_rate" in df.columns:
        tr_quality = df["turnover_ratio"] / df["turnover_rate"].clip(lower=0.01)
        cond &= tr_quality >= p["tr_quality_min"]
    return df[cond].copy()


def fmt_params(p: dict[str, Any]) -> str:
    parts = [
        f"竞价[{p['pct_min']}%,{p['pct_max']}%]",
        f"额>={p['amount_min']}亿",
        f"换手>={p['turn_min']}%",
        f"涨名占比<={p['pct_rank_ratio_max']:.2f}",
        f"换名占比<={p['turn_rank_ratio_max']:.2f}",
        f"额名占比<={p['amt_rank_ratio_max']:.2f}",
        f"prev5<={p['prev5_max']}%",
        f"prev10<={p['prev10_max']}%",
        f"新高={p['need_new_high']}",
    ]
    if p.get("open_times_max") is not None:
        parts.append(f"开板次数<={p['open_times_max']}")
    if p.get("prev_auction_pct_min") is not None:
        parts.append(f"昨竞价涨幅>={p['prev_auction_pct_min']}%")
    if p.get("auction_price_ratio_min") is not None:
        parts.append(f"竞价价比>={p['auction_price_ratio_min']}")
    if p.get("turnover_ratio_min") is not None:
        parts.append(f"封板比>={p['turnover_ratio_min']}%")
    if p.get("tr_quality_min") is not None:
        parts.append(f"封板质量>={p['tr_quality_min']}")
    return " ".join(parts)


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


def run(today: str):
    print(f"\n{'='*60}")
    print(f"  一进二 9:28 选股（Cursor 规则版）  |  {today}")
    print(f"{'='*60}")

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

    # 优先从 rule_params.json 读取已收紧参数
    saved_params, saved_prototype = _load_rule_params()
    use_saved = saved_params is not None and saved_prototype is not None

    # 只需拉今日数据（如果参数已从文件读取）
    need_dates = sorted({today} if use_saved else {today, *[x["trade_date"] for x in REFERENCE_CASES]})
    raw: dict[str, dict[str, Any]] = {}
    dfs: dict[str, pd.DataFrame] = {}

    for td in need_dates:
        print(f"\n[取数] {td}")
        day = collect_day(pro, pro_min, trade_dates, name_map, st_set, td)
        if not day:
            raise SystemExit(f"{td} 取数失败或池为空")
        raw[td] = day
        df = build_df(day)
        if df is None or df.empty:
            raise SystemExit(f"{td} 宽表构建失败")
        dfs[td] = df
        if td == today:
            print(f"  今日首板池: {len(day['pool'])} 只")
            print(f"  今日竞价数据: {len(day['auction'])} 只")

    if use_saved:
        params = saved_params
        prototype = saved_prototype
        print(f"\n  [参数来源] rule_params.json（已含反例收紧）")
    else:
        print(f"\n  [参数来源] 重新从参考日推导（rule_params.json 不可用）")
        reference_rows = get_reference_rows(dfs)
        params = derive_params(reference_rows)
        prototype = build_prototype(reference_rows)

    today_df = dfs[today]
    hits = apply_strategy(today_df, params)
    if hits.empty:
        print(f"\n{'='*60}")
        print("  今日无符合 cursor 规则的标的。")
        print(f"  参数: {fmt_params(params)}")
        print(f"{'='*60}\n")
        return

    hits["prototype_dist"] = hits.apply(lambda r: prototype_distance(r, prototype), axis=1)
    hits = hits.sort_values(["prototype_dist", "pct_rank", "turn_rank", "ts_code"]).reset_index(drop=True)

    print(f"\n{'='*60}")
    print(f"  命中 {len(hits)} 只（按原型距离优先）\n")
    print(
        f"  {'名称':8s} {'代码':12s} {'竞价%':>7} {'额(亿)':>7} {'换手%':>7} "
        f"{'涨名':>5} {'换名':>5} {'额名':>5} {'原型距':>7}"
    )
    print(f"  {'-'*86}")
    for _, r in hits.iterrows():
        print(
            f"  {r['name']:8s} {r['ts_code']:12s} "
            f"{r['auction_pct']:>7.2f} {r['auction_amount_yi']:>7.3f} "
            f"{r['turnover_rate']:>7.3f} "
            f"{int(r['pct_rank']):>5} {int(r['turn_rank']):>5} {int(r['amt_rank']):>5} "
            f"{r['prototype_dist']:>7.2f}"
        )

    top = hits.iloc[0]
    print(f"\n  今日应选：{top['name']} {top['ts_code']}")
    print("  原因：在全部命中标的中原型距离最小，最接近当前 cursor 规则的参考样本画像。")
    print(f"\n  参数: {fmt_params(params)}")
    print(f"{'='*60}\n")


def main():
    ap = argparse.ArgumentParser(description="9:28 一进二实盘选股（Cursor 规则版）")
    ap.add_argument("--date", default=None, help="指定交易日 YYYYMMDD，默认取今日")
    args = ap.parse_args()
    today = args.date or datetime.now().strftime("%Y%m%d")
    run(today)


if __name__ == "__main__":
    main()
