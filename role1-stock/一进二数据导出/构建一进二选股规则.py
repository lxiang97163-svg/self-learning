# -*- coding: utf-8 -*-
"""
一次性构建「一进二选股规则.md」：仅依赖 first_board_pool_data + Tushare 类 API。
不 import 一进二_grid_search / 一进二_9点28选股。

运行：
  python 构建一进二选股规则.py --export-csv-only   # 只拉数并导出 CSV（不写 md）
  python 构建一进二选股规则.py

方法：
  1. 拉取严格首板池、9:25 竞价、前日市值、历史特征、当日收盘
  2. 以「锚定样本 + 历史支撑样本」形成参考样本集
  3. 对参考样本的量化字段做“保守包络 + 最小粒度取整”
  4. 得到一套可执行硬规则；命中结果再按“原型相似度”排序
"""
from __future__ import annotations

import argparse
import json as _json
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

import chinadata.ca_data as ts
import chinamindata.min as tss

from first_board_pool_data import (
    fetch_auction_pool_only,
    fetch_close_pool_parallel,
    fetch_daily_basic_pool,
    fetch_hist_pool_parallel,
)

DIR = Path(__file__).resolve().parent
OUT_MD = DIR / "一进二选股规则.md"
# 脚本位于「一进二数据导出」目录内时，CSV 与脚本同目录，避免再套一层子目录
OUT_CSV_DIR = DIR

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"
TOKEN_MIN = "ne34e6697159de73c228e34379b510ec554"

FETCH_DATES = [
    "20260410", "20260413", "20260414", "20260415", "20260416", "20260417", "20260420",
]
ANCHORS = [
    {"trade_date": "20260410", "ts_code": "600743.SH", "name": "华远控股"},
    {"trade_date": "20260410", "ts_code": "002824.SZ", "name": "和胜股份"},
    {"trade_date": "20260413", "ts_code": "002418.SZ", "name": "康盛股份"},
    {"trade_date": "20260415", "ts_code": "600664.SH", "name": "哈药股份"},
    {"trade_date": "20260417", "ts_code": "605388.SH", "name": "均瑶健康"},
    {"trade_date": "20260420", "ts_code": "002217.SZ", "name": "合力泰"},
]
# 反例验证日：04-14、04-16（04-10~04-20 区间内已确认无合适标的的交易日）
NEGATIVE_DATES = ["20260414", "20260416"]
VALIDATION_DATES = sorted({a["trade_date"] for a in ANCHORS})
REFERENCE_CASES = ANCHORS

RANK_UNLIMITED = 999  # 与 apply_params 中「不截排名」约定一致
ROUND_STEP = {
    "pct": 0.1,
    "amount": 0.01,
    "turn": 0.01,
}
# 宽松包络系数：下界放宽 LOOSE_LOWER，上界放宽 LOOSE_UPPER
# 0.05/0.10：保留少量缓冲以应对轻微样本外波动，比 0.30/0.50 更紧以便贪心收紧清零反例日
LOOSE_LOWER = 0.05
LOOSE_UPPER = 0.10
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

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


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


def init_apis():
    ts.set_token(TOKEN)
    tss.set_token(TOKEN_MIN)
    return ts.pro_api(), tss.pro_api()


def get_all_trade_dates(pro, dates: list[str]) -> list[str]:
    all_dt = sorted(dates)
    start = (datetime.strptime(all_dt[0], "%Y%m%d") - timedelta(days=45)).strftime("%Y%m%d")
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


def is_mainboard(code: str) -> bool:
    if code.endswith(".BJ"):
        return False
    c = code.split(".")[0]
    return not c.startswith(("300", "301", "688", "689"))


def collect_day(
    pro,
    pro_min,
    all_trade_dates: list[str],
    name_map: dict,
    st_set: set,
    trade_date: str,
) -> Optional[dict]:
    prev_d, prev2_d = prev_dates(all_trade_dates, trade_date)
    zt_prev = retry(pro.limit_list_d, trade_date=prev_d, limit_type="U")
    zt_prev2 = retry(pro.limit_list_d, trade_date=prev2_d, limit_type="U")
    prev2_set = set(zt_prev2["ts_code"]) if zt_prev2 is not None and not zt_prev2.empty else set()
    if zt_prev is None or zt_prev.empty:
        print(f"  skip {trade_date}: no limit_list {prev_d}")
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
    pool["name"] = pool["ts_code"].map(name_map)
    pool_codes = pool["ts_code"].tolist()
    print(f"  {trade_date} pool(首板∪二板∪三板)={len(pool_codes)} (首板{len(first_board)} 二板{len(second_board)} 三板{len(third_board)})")
    auc = fetch_auction_pool_only(pro_min, trade_date, pool_codes, _invoke)
    if auc.empty:
        print(f"  skip {trade_date}: no auction")
        return None
    # T-1 竞价（前一日 9:25 集合竞价），用于计算 prev_auction_pct 维度
    prev_auc = fetch_auction_pool_only(pro_min, prev_d, pool_codes, _invoke)
    basic = fetch_daily_basic_pool(pro, prev_d, pool_codes, _invoke)
    start_hist = (datetime.strptime(prev_d, "%Y%m%d") - timedelta(days=180)).strftime("%Y%m%d")
    hist_df = fetch_hist_pool_parallel(pro, pool_codes, start_hist, prev_d, _invoke, progress=True)
    close_map = fetch_close_pool_parallel(pro, trade_date, pool_codes, _invoke)
    return {
        "trade_date": trade_date,
        "prev_date": prev_d,
        "pool": pool,
        "auction": auc,
        "prev_auction": prev_auc,
        "basic": basic,
        "hist": hist_df,
        "close_map": close_map,
        "name_map": {r["ts_code"]: r.get("name", "") for _, r in pool.iterrows()},
    }


def enrich_wide_for_csv(
    df: pd.DataFrame,
    trade_date: str,
    prev_date: str,
    close_map: dict[str, dict],
) -> pd.DataFrame:
    """宽表增加交易日、收盘价与相对竞价收益等列，便于自行分析。"""
    out = df.copy()
    for c in ("trade_date", "prev_trade_date"):
        if c in out.columns:
            out = out.drop(columns=[c])
    out.insert(0, "prev_trade_date", prev_date)
    out.insert(0, "trade_date", trade_date)

    closes, opens, pcts = [], [], []
    pnl_au = []
    for _, row in out.iterrows():
        ts_code = row["ts_code"]
        m = close_map.get(ts_code) or {}
        c = m.get("close")
        o = m.get("open")
        pc = m.get("pct_chg")
        closes.append(c)
        opens.append(o)
        pcts.append(pc)
        ap = float(row["price"]) if pd.notna(row.get("price")) else None
        if c is not None and ap is not None and ap > 0:
            pnl_au.append((float(c) - ap) / ap * 100)
        else:
            pnl_au.append(None)
    out["daily_close"] = closes
    out["daily_open"] = opens
    out["daily_pct_chg"] = pcts
    out["close_vs_auction_pct"] = pnl_au
    return out


def export_csv_bundle(
    raw: dict[str, dict],
    dfs: dict[str, pd.DataFrame],
    close_maps: dict[str, dict],
    out_dir: Path,
) -> None:
    """把各日原始片段与合并宽表全部写入 CSV（utf-8-sig）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_parts: list[pd.DataFrame] = []

    for td in FETCH_DATES:
        day = raw.get(td)
        if not day:
            continue
        prefix = out_dir / f"{td}"

        day["pool"].to_csv(f"{prefix}_01_首板二板联合池_limit_list.csv", index=False, encoding="utf-8-sig")
        day["auction"].to_csv(f"{prefix}_02_竞价原始_stk_auction.csv", index=False, encoding="utf-8-sig")
        day["basic"].to_csv(f"{prefix}_03_前日市值_daily_basic.csv", index=False, encoding="utf-8-sig")
        day["hist"].to_csv(f"{prefix}_04_历史特征_daily_agg.csv", index=False, encoding="utf-8-sig")

        rows_close = []
        for code, info in (day.get("close_map") or {}).items():
            rows_close.append({"ts_code": code, **info})
        pd.DataFrame(rows_close).to_csv(
            f"{prefix}_05_当日收盘_daily.csv", index=False, encoding="utf-8-sig"
        )

        dfw = dfs.get(td)
        if dfw is not None and not dfw.empty:
            wide = enrich_wide_for_csv(dfw, td, day["prev_date"], close_maps.get(td, {}))
            wide.to_csv(f"{prefix}_06_分析宽表_全字段.csv", index=False, encoding="utf-8-sig")
            merged_parts.append(wide)

    if merged_parts:
        pd.concat(merged_parts, ignore_index=True).to_csv(
            out_dir / "00_分析宽表_全部日期合并.csv", index=False, encoding="utf-8-sig"
        )

    meta = pd.DataFrame(
        {
            "说明": [
                "01_首板二板联合池：T-1 日 limit_list_d 筛 strict 首板(limit_times=1) ∪ strict 二板(limit_times=2) + 主板 + 非ST",
                "02_竞价原始：T 日 stk_auction 池内标的",
                "03_前日市值：T-1 daily_basic（circ_mv 等）",
                "04_历史特征：并行 daily 汇总的 prev_5d/prev_10d/high20/high60",
                "05_当日收盘：T 日 daily 池内",
                "06_分析宽表：pool 与 02–04 合并 + pct_rank/turn_rank/amt_rank 及对应 ratio + 收盘与相对竞价涨跌",
                "00_合并：各日 06 纵向合并",
            ]
        }
    )
    meta.to_csv(str(out_dir / "README_字段说明.csv"), index=False, encoding="utf-8-sig")
    print(f"[CSV] 已写入目录: {out_dir.resolve()}")


def build_df(day: dict) -> Optional[pd.DataFrame]:
    pool = day["pool"]
    auc = day["auction"]
    basic = day["basic"]
    hist = day["hist"]
    df = pool.merge(auc, on="ts_code", how="left")
    df = df.merge(basic[["ts_code", "circ_mv_yi"]], on="ts_code", how="left")
    df = df.merge(hist, on="ts_code", how="left")
    # 合并 T-1 竞价涨幅 + 竞价价格
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
    if df.empty:
        return None
    for col in [
        "price", "high20", "high60", "auction_pct", "auction_amount_yi",
        "turnover_rate", "circ_mv_yi", "prev_5d", "prev_10d",
        "fd_amount", "first_time", "last_time", "open_times", "turnover_ratio",
        "prev_auction_pct",
        "prev_auction_price",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["pct_rank"] = df["auction_pct"].rank(method="min", ascending=False)
    df["turn_rank"] = df["turnover_rate"].rank(method="min", ascending=False)
    df["amt_rank"] = df["auction_amount_yi"].rank(method="min", ascending=False)
    pct_pool_size = max(int(df["auction_pct"].notna().sum()), 1)
    turn_pool_size = max(int(df["turnover_rate"].notna().sum()), 1)
    amt_pool_size = max(int(df["auction_amount_yi"].notna().sum()), 1)
    df["pct_pool_size"] = pct_pool_size
    df["turn_pool_size"] = turn_pool_size
    df["amt_pool_size"] = amt_pool_size
    df["pct_rank_ratio"] = df["pct_rank"] / pct_pool_size
    df["turn_rank_ratio"] = df["turn_rank"] / turn_pool_size
    df["amt_rank_ratio"] = df["amt_rank"] / amt_pool_size
    df["auction_new20"] = df["price"] >= df["high20"]
    df["auction_new60"] = df["price"] >= df["high60"]
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
    return df


def apply_params(df: pd.DataFrame, p: dict) -> list[str]:
    if df is None or df.empty:
        return []
    cond = df["auction_pct"].between(p["pct_min"], p["pct_max"], inclusive="both") & (
        df["auction_amount_yi"] >= p["amount_min"]
    ) & (df["turnover_rate"] >= p["turn_min"])
    if p.get("turn_max") is not None:
        cond &= df["turnover_rate"] <= p["turn_max"]
    if p.get("pct_rank_ratio_max", RANK_UNLIMITED) < RANK_UNLIMITED:
        cond &= df["pct_rank_ratio"] <= p["pct_rank_ratio_max"]
    if p.get("turn_rank_ratio_max", RANK_UNLIMITED) < RANK_UNLIMITED:
        cond &= df["turn_rank_ratio"] <= p["turn_rank_ratio_max"]
    if p.get("amt_rank_ratio_max", RANK_UNLIMITED) < RANK_UNLIMITED:
        cond &= df["amt_rank_ratio"] <= p["amt_rank_ratio_max"]
    if p.get("prev5_max") is not None:
        cond &= df["prev_5d"] <= p["prev5_max"]
    if p.get("prev10_max") is not None:
        cond &= df["prev_10d"] <= p["prev10_max"]
    if p.get("need_new_high"):
        cond &= df["auction_new20"] | df["auction_new60"]
    # T-1 质量字段过滤（仅当 derive_params 推导出该维时生效）
    if p.get("open_times_max") is not None and "open_times" in df.columns:
        cond &= df["open_times"].fillna(0) <= p["open_times_max"]
    if p.get("fd_amount_min") is not None and "fd_amount" in df.columns:
        cond &= df["fd_amount"].fillna(0) >= p["fd_amount_min"]
    if p.get("first_time_max") is not None and "first_time" in df.columns:
        cond &= df["first_time"].fillna(999999) <= p["first_time_max"]
    # auction_price_ratio_min：今昨竞价比下限；NaN 自动通过（旧版 CSV 兼容）
    if p.get("auction_price_ratio_min") is not None and "auction_price_ratio" in df.columns:
        cond &= df["auction_price_ratio"].isna() | (df["auction_price_ratio"] >= p["auction_price_ratio_min"])
    # turnover_ratio_min：T-1 收盘封板量占流通股比例下限；弱封板 = T 日延续乏力
    if p.get("turnover_ratio_min") is not None and "turnover_ratio" in df.columns:
        cond &= df["turnover_ratio"].fillna(0) >= p["turnover_ratio_min"]
    # tr_quality_min = turnover_ratio / turnover_rate：T-1封板强度/T日竞价压力比
    # 值低 = T日竞价抛压相对T-1封板承诺过重，延续性弱（反例瑞康医药=6.18 < 7.0 ≤ 来伊份=7.94）
    if p.get("tr_quality_min") is not None and "turnover_ratio" in df.columns and "turnover_rate" in df.columns:
        tr_quality = df["turnover_ratio"] / df["turnover_rate"].clip(lower=0.01)
        cond &= tr_quality >= p["tr_quality_min"]
    return df.loc[cond, "ts_code"].tolist()


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
    for case in REFERENCE_CASES:
        trade_date = case["trade_date"]
        ts_code = case["ts_code"]
        df = dfs.get(trade_date)
        if df is None or df.empty:
            raise SystemExit(f"缺少参考样本所在交易日数据: {trade_date}")
        row = df[df["ts_code"] == ts_code]
        if row.empty:
            raise SystemExit(f"参考样本未出现在对应交易日池中: {trade_date} {ts_code}")
        rows.append(row.iloc[0])
    out = pd.DataFrame(rows).reset_index(drop=True)
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
    for col in required_cols:
        if out[col].isna().any():
            bad = out.loc[out[col].isna(), ["trade_date", "ts_code"]].to_dict("records")
            raise SystemExit(f"参考样本关键字段缺失: {col} -> {bad}")
    return out


def derive_params(reference_rows: pd.DataFrame) -> dict[str, Any]:
    """
    宽松包络推导：在锚定样本 min/max 基础上分别放宽 LOOSE_LOWER / LOOSE_UPPER。
    LOOSE_LOWER=0.05 / LOOSE_UPPER=0.10 保留少量缓冲，避免过拟合同时能被贪心收紧清零反例日。
    turn_max 已恢复：有效过滤高换手噪声股；fd_amount_min / first_time_max 仍删除（无通用性）。
    auction_price_ratio_min 固定为逻辑门槛 1.0，不再从样本推导。
    """
    new_high_series = reference_rows["auction_new20"] | reference_rows["auction_new60"]
    pct_min_raw = float(reference_rows["auction_pct"].min())
    pct_max_raw = float(reference_rows["auction_pct"].max())
    amount_min_raw = float(reference_rows["auction_amount_yi"].min())
    turn_min_raw = float(reference_rows["turnover_rate"].min())
    pct_rank_max_raw = float(reference_rows["pct_rank_ratio"].max())
    turn_rank_max_raw = float(reference_rows["turn_rank_ratio"].max())
    amt_rank_max_raw = float(reference_rows["amt_rank_ratio"].max())
    prev5_max_raw = float(reference_rows["prev_5d"].max())
    prev10_max_raw = float(reference_rows["prev_10d"].max())

    turn_max_raw = float(reference_rows["turnover_rate"].max())

    params: dict[str, Any] = {
        "pct_min": round_down(pct_min_raw * (1 - LOOSE_LOWER), ROUND_STEP["pct"]),
        "pct_max": round_up(pct_max_raw * (1 + LOOSE_UPPER), ROUND_STEP["pct"]),
        "amount_min": round_down(amount_min_raw * (1 - LOOSE_LOWER), ROUND_STEP["amount"]),
        "turn_min": round_down(turn_min_raw * (1 - LOOSE_LOWER), ROUND_STEP["turn"]),
        "turn_max": round_up(turn_max_raw * (1 + LOOSE_UPPER), ROUND_STEP["turn"]),
        "pct_rank_ratio_max": round_up(pct_rank_max_raw * (1 + LOOSE_UPPER), 0.01),
        "turn_rank_ratio_max": round_up(turn_rank_max_raw * (1 + LOOSE_UPPER), 0.01),
        "amt_rank_ratio_max": round_up(amt_rank_max_raw * (1 + LOOSE_UPPER), 0.01),
        "prev5_max": int(math.ceil(prev5_max_raw * (1 + LOOSE_UPPER))),
        "prev10_max": int(math.ceil(prev10_max_raw * (1 + LOOSE_UPPER))),
        "need_new_high": bool(new_high_series.all()),
    }
    # 领域知识覆盖：
    # A 股主板涨停上限 10%，竞价价理论上不超过 10%；
    # 锚定期 pct_max=9.5，但样本外存在 9.5~9.99% 的强势个股（如崩盘反弹日），放宽到 9.99%
    if params["pct_max"] < 9.99:
        params["pct_max"] = 9.99
    # 崩盘/急跌回弹日（如 04-07~04-09）整体换手偏低；允许换手下限低至 0.50%
    if params["turn_min"] > 0.50:
        params["turn_min"] = 0.50
    # T-1 开板次数：+2 缓冲（比锚定最大值多允许 2 次）
    if "open_times" in reference_rows.columns and reference_rows["open_times"].notna().all():
        params["open_times_max"] = int(math.ceil(float(reference_rows["open_times"].max()))) + 2
    # 今昨竞价比（auction_price_ratio）：T-1 早盘已封涨停 → 比值低 → T 日是虚假跟风
    # 6 锚定 ratio ∈ [1.141, 1.198]；反例世运电路 = 1.058 → LOOSE_LOWER 5% → 1.08
    if "auction_price_ratio" in reference_rows.columns and reference_rows["auction_price_ratio"].notna().all():
        ratio_min_raw = float(reference_rows["auction_price_ratio"].min())
        params["auction_price_ratio_min"] = round_down(ratio_min_raw * (1 - LOOSE_LOWER), 0.01)
    # T-1 封板量占流通股比例（turnover_ratio）：封板越牢 T 日延续越强
    # 6 锚定 ∈ [6.92, 12.65]；非锚正例来伊份=6.05；反例晋西车轴=5.95/海王生物=4.70/粤传媒=4.34
    # 标准 LOOSE_LOWER(5%) → 6.92×0.95=6.57 会过滤来伊份(6.05)；
    # 固定硬门槛 6.0（gap 中点，防止锚定最小值漂移影响来伊份等边界正例）
    if "turnover_ratio" in reference_rows.columns and reference_rows["turnover_ratio"].notna().any():
        params["turnover_ratio_min"] = 6.0
    # tr_quality = turnover_ratio / turnover_rate：T-1封板强度/T日竞价压力比
    # 瑞康医药=6.18 < 7.0 ≤ 来伊份=7.94（最小正例），gap 清晰
    if ("turnover_ratio" in reference_rows.columns and "turnover_rate" in reference_rows.columns
            and reference_rows["turnover_ratio"].notna().any() and reference_rows["turnover_rate"].notna().any()):
        params["tr_quality_min"] = 7.0
    return params


def _all_anchors_hit(params: dict, dfs: dict[str, pd.DataFrame]) -> bool:
    """检查所有锚定样本是否仍被 params 命中。"""
    for anchor in ANCHORS:
        td = anchor["trade_date"]
        df = dfs.get(td)
        if df is None:
            return False
        hits = apply_params(df, params)
        if anchor["ts_code"] not in hits:
            return False
    return True


def _count_negative_hits(params: dict, dfs: dict[str, pd.DataFrame]) -> tuple[int, dict[str, list[str]]]:
    """统计反例日命中数量，返回 (总命中数, {date: [codes]})。"""
    neg_hits: dict[str, list[str]] = {}
    total = 0
    for nd in NEGATIVE_DATES:
        df = dfs.get(nd)
        if df is not None:
            codes = apply_params(df, params)
            if codes:
                neg_hits[nd] = codes
                total += len(codes)
    return total, neg_hits


def tighten_for_negatives(
    initial_params: dict,
    dfs: dict[str, pd.DataFrame],
    max_iterations: int = 200,
) -> dict[str, Any]:
    """
    贪心收紧：每轮对所有可收紧维度各尝试一步，选能减少最多反例命中且不丢失锚定的维度。
    直到所有反例日命中为 0 或无法继续收紧。
    """
    params = dict(initial_params)
    # (key, direction, step)  direction: +1 增大收紧, -1 减小收紧
    # fd_amount_min / first_time_max 已删除；turn_max 已恢复（有效区分高换手噪声股）
    dimensions: list[tuple[str, int, float]] = [
        ("pct_min", +1, 0.1),
        ("pct_max", -1, 0.1),
        ("amount_min", +1, 0.01),
        ("turn_min", +1, 0.01),
        ("turn_max", -1, 0.01),
        ("pct_rank_ratio_max", -1, 0.01),
        ("turn_rank_ratio_max", -1, 0.01),
        ("amt_rank_ratio_max", -1, 0.01),
        ("prev5_max", -1, 1),
        ("prev10_max", -1, 1),
    ]
    if params.get("open_times_max") is not None:
        dimensions.append(("open_times_max", -1, 1))
    if params.get("prev_auction_pct_min") is not None:
        dimensions.append(("prev_auction_pct_min", +1, 0.1))
    if params.get("auction_price_ratio_min") is not None:
        dimensions.append(("auction_price_ratio_min", +1, 0.01))
    if params.get("turnover_ratio_min") is not None:
        dimensions.append(("turnover_ratio_min", +1, 0.1))
    if params.get("tr_quality_min") is not None:
        dimensions.append(("tr_quality_min", +1, 0.1))

    for iteration in range(max_iterations):
        total_neg, neg_hits = _count_negative_hits(params, dfs)
        if total_neg == 0:
            print(f"  [收紧] 第 {iteration} 轮后反例日全部清零")
            return params

        best_dim: tuple[str, int, float] | None = None
        best_neg_remaining = total_neg

        for key, direction, step in dimensions:
            if key not in params or params[key] is None:
                continue
            candidate = dict(params)
            new_val = round(candidate[key] + direction * step, 6)
            # 基本边界保护
            if key.endswith("_max") and new_val < 0:
                continue
            if key == "pct_min" and new_val > params.get("pct_max", 999):
                continue
            if key == "turn_max" and new_val < params.get("turn_min", 0):
                continue
            candidate[key] = new_val

            if not _all_anchors_hit(candidate, dfs):
                continue

            neg_remaining, _ = _count_negative_hits(candidate, dfs)
            if neg_remaining < best_neg_remaining:
                best_neg_remaining = neg_remaining
                best_dim = (key, direction, step)

        if best_dim is None:
            print(f"  [收紧] 第 {iteration} 轮无法进一步收紧（所有单步均会丢失锚定或无改善）")
            remaining_neg, remaining_detail = _count_negative_hits(params, dfs)
            if remaining_neg > 0:
                print(f"  [警告] 仍有反例命中: {remaining_detail}")
            break

        key, direction, step = best_dim
        params[key] = round(params[key] + direction * step, 6)
        new_neg, _ = _count_negative_hits(params, dfs)
        print(f"  [收紧] 第 {iteration+1} 轮: {key} → {params[key]}  (反例剩余 {new_neg})")

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


def sort_codes_by_prototype(
    codes: list[str],
    df: pd.DataFrame,
    prototype: dict[str, dict[str, float]],
) -> list[str]:
    if not codes:
        return []
    pairs = []
    for code in codes:
        row = df[df["ts_code"] == code]
        if row.empty:
            continue
        pairs.append((prototype_distance(row.iloc[0], prototype), code))
    pairs.sort(key=lambda x: (x[0], x[1]))
    return [code for _, code in pairs]


def summarize_rule(
    picks: dict[str, list[str]],
    close_maps: dict[str, dict],
    dfs: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    support_hits = 0
    for case in REFERENCE_CASES:
        if case["ts_code"] in picks.get(case["trade_date"], []):
            support_hits += 1

    validation_non_empty = sum(1 for d in VALIDATION_DATES if picks.get(d))
    positive_pnl = 0
    negative_pnl = 0
    for d in VALIDATION_DATES:
        df = dfs.get(d)
        if df is None:
            continue
        for code in picks.get(d, []):
            info = close_maps.get(d, {}).get(code)
            row = df[df["ts_code"] == code]
            if not info or row.empty:
                continue
            ap = row.iloc[0]["price"]
            close = info.get("close")
            if pd.isna(ap) or float(ap) <= 0 or close is None or pd.isna(close):
                continue
            pnl = (float(close) - float(ap)) / float(ap) * 100
            if pnl > 0:
                positive_pnl += 1
            elif pnl < 0:
                negative_pnl += 1

    return {
        "support_hits": support_hits,
        "support_total": len(REFERENCE_CASES),
        "validation_non_empty": validation_non_empty,
        "validation_total": len(VALIDATION_DATES),
        "positive_pnl": positive_pnl,
        "negative_pnl": negative_pnl,
    }


def fmt_trade_date(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:]}"


def fmt_prev_limit(label: str, value: Optional[int]) -> str:
    if value is None:
        return f"- {label}：不限制（参考样本该字段缺失）。\n"
    return f"- {label} ≤ {value}%。\n"


def fmt_pick_row(
    code: str,
    df: pd.DataFrame,
    close_map: dict,
    name_map: dict[str, str],
    prototype: dict[str, dict[str, float]],
) -> str:
    row = df[df["ts_code"] == code]
    if row.empty:
        return f"| {code} | | | | | | | |"
    r = row.iloc[0]
    nm = name_map.get(code, "")
    ap = float(r["price"]) if pd.notna(r.get("price")) else 0.0
    cm = close_map.get(code) or {}
    cl = cm.get("close")
    pnl = ""
    if cl is not None and ap > 0:
        pnl = f"{(cl - ap) / ap * 100:+.2f}%"
    prank = int(r["pct_rank"]) if pd.notna(r.get("pct_rank")) else 0
    trank = int(r["turn_rank"]) if pd.notna(r.get("turn_rank")) else 0
    arnk = int(r["amt_rank"]) if pd.notna(r.get("amt_rank")) else 0
    dist = prototype_distance(r, prototype)
    pct_text = f"{float(r['auction_pct']):.2f}%" if pd.notna(r.get("auction_pct")) else ""
    amt_text = f"{float(r['auction_amount_yi']):.3f}亿" if pd.notna(r.get("auction_amount_yi")) else ""
    turn_text = f"{float(r['turnover_rate']):.3f}%" if pd.notna(r.get("turnover_rate")) else ""
    return (
        f"| {nm} | {code} | {pct_text} | {amt_text} | "
        f"{turn_text} | {prank}/{trank}/{arnk} | {dist:.2f} | {pnl} |"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--export-csv-only",
        action="store_true",
        help="只拉取接口数据并导出本目录下多份 CSV（与脚本同目录），不写 md",
    )
    args = ap.parse_args()

    pro, pro_min = init_apis()
    tds = get_all_trade_dates(pro, FETCH_DATES)
    for d in FETCH_DATES:
        if d not in tds:
            raise SystemExit(f"{d} 非交易日")

    name_map, st_set = get_name_st_maps(pro)
    raw: dict[str, dict] = {}
    for td in FETCH_DATES:
        print(f"=== fetch {td} ===")
        raw[td] = collect_day(pro, pro_min, tds, name_map, st_set, td)

    dfs: dict[str, pd.DataFrame] = {}
    close_maps: dict[str, dict] = {}
    for td, day in raw.items():
        if not day:
            continue
        dfs[td] = build_df(day)
        close_maps[td] = day["close_map"]

    export_csv_bundle(raw, dfs, close_maps, OUT_CSV_DIR)

    if args.export_csv_only:
        return

    for anchor in ANCHORS:
        trade_date = anchor["trade_date"]
        if trade_date not in dfs or dfs[trade_date] is None:
            raise SystemExit(f"缺少锚定日数据: {trade_date}")

    reference_rows = get_reference_rows(dfs)
    envelope_p = derive_params(reference_rows)
    print(f"\n[包络参数] {envelope_p}")

    # 反例验证日收紧
    neg_total, neg_detail = _count_negative_hits(envelope_p, dfs)
    if neg_total > 0:
        print(f"\n[反例验证] 包络参数下反例日仍有命中: {neg_detail}")
        print("  开始贪心收紧...")
        best_p = tighten_for_negatives(envelope_p, dfs)
    else:
        print("\n[反例验证] 包络参数下反例日已全部为空，无需收紧")
        best_p = envelope_p

    # 收紧后最终验证
    final_neg, final_neg_detail = _count_negative_hits(best_p, dfs)
    if final_neg > 0:
        print(f"\n[警告] 收紧后仍有反例命中: {final_neg_detail}")
    anchors_ok = _all_anchors_hit(best_p, dfs)
    print(f"[验证] 锚定全命中: {anchors_ok}  反例全清零: {final_neg == 0}")
    if not anchors_ok:
        raise SystemExit("收紧后锚定样本丢失，请检查数据或手动调整")

    prototype = build_prototype(reference_rows)

    # 导出 rule_params.json 供 928_prepare / 928选股_cursor 读取
    rule_export = {"params": best_p, "prototype": prototype}
    rule_json_path = DIR / "rule_params.json"
    rule_json_path.write_text(_json.dumps(rule_export, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[导出] {rule_json_path}")

    best_picks = {
        d: sort_codes_by_prototype(apply_params(dfs.get(d), best_p), dfs[d], prototype)
        for d in dfs
        if dfs.get(d) is not None
    }
    summary = summarize_rule(best_picks, close_maps, dfs)

    # --- Markdown ---
    lines: list[str] = []
    lines.append("# 一进二选股规则（书面定稿）\n")
    lines.append("> 生成方式：由 `构建一进二选股规则.py` 拉取**严格首板∪严格二板联合池**与 9:25 竞价数据，基于「参考样本包络 + 原型相似度排序」直接落盘；**未**引用 `一进二_grid_search.py` / `一进二_9点28选股.py` 的逻辑。\n")

    lines.append("## 一、推测过程（摘要）\n")
    lines.append("1. **池**：T-1 日 `limit_list_d` 中严格首板（`limit_times==1`、T-2 未涨停）∪ 严格二板（`limit_times==2`）∪ 三板（`limit_times==3`），均限沪深主板、非 ST；竞价与名次在联合池内计算。\n")
    lines.append("2. **次日竞价**：仅使用 T 日 `stk_auction` 在池内标的上的涨幅、成交额、换手率；在池内计算涨幅排名、换手排名、成交额排名。\n")
    anchor_desc = "；".join(
        f"`{fmt_trade_date(a['trade_date'])}` **{a['name']} `{a['ts_code']}`**"
        for a in ANCHORS
    )
    lines.append(
        "3. **参考样本（全部为锚定）**："
        f"{anchor_desc}。\n"
    )
    lines.append(
        "4. **量化推断**：对参考样本的各字段取保守包络，并按可读粒度向外取整。"
        "例如涨幅区间取参考样本最小/最大值后按 0.1% 外扩，成交额与换手率按 0.01 外扩；"
        "三类排名不再使用跨日绝对名次，而改用**池内名次占比**包络；命中结果再按参考样本原型的相似度排序。\n"
    )
    lines.append(
        "5. **样本内回放日**：对 "
        + "、".join(f"`{d}`" for d in VALIDATION_DATES)
        + " 做样本内回放，检查同一套硬条件是否均能产生命中，并用收盘相对竞价近似回看强弱；"
        + "**这不是独立样本外验证**。\n"
    )
    neg_dates_str = "、".join(f"`{d}`" for d in NEGATIVE_DATES)
    lines.append(
        f"6. **反例验证日**：{neg_dates_str} 为已知无合适标的的交易日，"
        "规则需确保这些日期**命中 0 只**；若包络参数仍有命中，"
        "脚本会自动贪心收紧参数（每轮选最优单步），直到反例全部清零且锚定不丢失。\n"
    )
    lines.append("7. **排除**：不采用流通市值 50~80 亿硬区间；本版也不再做大规模参数穷举。\n")
    lines.append(
        "8. **三维权**：`pct_rank_ratio_max`、`turn_rank_ratio_max`、`amt_rank_ratio_max` 为有限小数时，"
        "表示标的须同时满足「竞价涨幅名次占比 ≤ 该值」「换手名次占比 ≤ 该值」「竞价成交额名次占比 ≤ 该值」"
        "（名次占比 = 当日池内名次 / 当日池大小）。\n"
    )

    lines.append("## 二、定稿规则（可执行）\n")
    p = best_p
    lines.append("### 2.1 标的池（T-1）\n")
    lines.append("- **严格首板**：T-1 日涨停且 `limit_times=1`，T-2 未涨停，沪深主板，非 ST。\n")
    lines.append("- **严格二板**：T-1 日涨停且 `limit_times=2`，沪深主板，非 ST。\n")
    lines.append("- **三板**：T-1 日涨停且 `limit_times=3`，沪深主板，非 ST。\n")
    lines.append("- 三路结果按 `ts_code` 去重取**并集**；竞价与名次均在该联合池内计算。\n")
    lines.append("- 剔除：ST/*ST、创业板/科创板/北交所。\n")
    lines.append("\n### 2.2 次日竞价过滤（T 日 9:25）\n")
    nh = "是（竞价价须不低于近 20 或近 60 日最高价）" if p["need_new_high"] else "否"
    lines.append(f"- 竞价涨幅：{p['pct_min']}% ≤ 涨幅 ≤ {p['pct_max']}%。\n")
    lines.append(f"- 竞价成交额 ≥ {p['amount_min']} 亿元。\n")
    lines.append(f"- 竞价换手率：{p['turn_min']}% ≤ 换手率")
    if p.get("turn_max") is not None:
        lines[-1] += f" ≤ {p['turn_max']}%。\n"
    else:
        lines[-1] += "。\n"
    if p["pct_rank_ratio_max"] < RANK_UNLIMITED:
        lines.append(
            f"- 竞价涨幅在**当日首板池内**排名：前 {p['pct_rank_ratio_max'] * 100:.0f}%（按池内名次占比）。\n"
        )
    else:
        lines.append("- 竞价涨幅排名：**不限制**（参数为 999）。\n")
    if p["turn_rank_ratio_max"] < RANK_UNLIMITED:
        lines.append(
            f"- 竞价换手率在**当日首板池内**排名：前 {p['turn_rank_ratio_max'] * 100:.0f}%（按池内名次占比）。\n"
        )
    else:
        lines.append("- 竞价换手率排名：**不限制**（参数为 999）。\n")
    if p["amt_rank_ratio_max"] < RANK_UNLIMITED:
        lines.append(
            f"- 竞价成交额在**当日首板池内**排名：前 {p['amt_rank_ratio_max'] * 100:.0f}%（按池内名次占比）。\n"
        )
    else:
        lines.append("- 竞价成交额排名：**不限制**（参数为 999）。\n")
    lines.append(fmt_prev_limit("近 5 日涨幅", p.get("prev5_max")))
    lines.append(fmt_prev_limit("近 10 日涨幅", p.get("prev10_max")))
    lines.append(f"- 新高约束：{nh}。\n")
    if p.get("open_times_max") is not None:
        lines.append(f"- T-1 开板次数 ≤ {p['open_times_max']} 次（来自 `limit_list_d`，全锚定均有值时生效）。\n")
    if p.get("fd_amount_min") is not None:
        lines.append(f"- T-1 封单金额 ≥ {p['fd_amount_min']} 亿（来自 `limit_list_d`，全锚定均有值时生效）。\n")
    if p.get("first_time_max") is not None:
        lines.append(f"- T-1 首次封板时间 ≤ {p['first_time_max']:.0f}（越小越早，来自 `limit_list_d`，全锚定均有值时生效）。\n")
    lines.append("\n### 2.3 输出\n")
    lines.append("- 同时满足以上条件的全部股票即为「计算机选」结果；结果已按**原型相似度**由高到低排序。\n")
    lines.append("- 若需压到 1~2 只，优先取原型距离最小者；原型距离越小，越接近参考样本的整体画像。\n")

    lines.append("\n## 三、参数表（定稿）\n")
    lines.append("| 参数 | 值 |\n|------|-----|\n")
    for k, v in p.items():
        lines.append(f"| {k} | {v} |\n")

    lines.append("\n### 附：参考样本覆盖情况\n")
    lines.append(
        f"- 样本内参考样本命中：**{summary['support_hits']} / {summary['support_total']}**"
        "（参数即由这些样本直接包络得出）。\n"
    )
    lines.append(
        f"- 样本内回放日非空：**{summary['validation_non_empty']} / {summary['validation_total']}**；"
        f"命中中收盘相对竞价为正 **{summary['positive_pnl']}** 只、为负 **{summary['negative_pnl']}** 只。\n"
    )

    lines.append("\n## 四、锚定样本回放\n")
    lines.append("- 下面结果已按原型相似度排序；`原型距` 越小越接近参考样本中心。\n")
    for anchor in ANCHORS:
        trade_date = anchor["trade_date"]
        ts_code = anchor["ts_code"]
        picks = best_picks.get(trade_date, [])
        day = raw[trade_date]
        df = dfs[trade_date]
        name_map = day["name_map"] if day else {}
        lines.append(f"\n### {fmt_trade_date(trade_date)}（{anchor['name']}）\n")
        lines.append(f"- 本规则命中：**{len(picks)}** 只 → `{picks}`\n")
        lines.append(
            f"- **包含 `{ts_code}`（{anchor['name']}）**："
            + ("是" if ts_code in picks else "否")
            + "。\n"
        )
        lines.append("\n| 名称 | 代码 | 竞价涨幅 | 竞价额 | 换手% | 涨幅/换手/额名次 | 原型距 | 收盘相对竞价 |\n")
        lines.append("|------|------|----------|--------|-------|------------------|--------|---------------|\n")
        for code in picks:
            lines.append(fmt_pick_row(code, df, close_maps[trade_date], name_map, prototype) + "\n")

    lines.append(
        "\n## 五、样本内回放日（与锚定日相同，仅验证规则触发，非独立样本外检验）："
        + " / ".join(VALIDATION_DATES)
        + "\n"
    )
    lines.append("说明：本节与第四节使用相同日期，属于样本内验证；「收盘相对竞价」=（当日收盘 − 9:25 竞价价）/ 竞价价。\n\n")
    for td in VALIDATION_DATES:
        day = raw.get(td)
        if not day:
            lines.append(f"### {td}\n- 数据缺失，跳过。\n\n")
            continue
        picks = best_picks.get(td, [])
        df = dfs[td]
        nm = day["name_map"]
        lines.append(f"### {td}（前一日首板池 {len(day['pool'])} 只）\n")
        lines.append(f"- 命中：**{len(picks)}** 只。\n")
        if not picks:
            lines.append("- 当日无符合全部硬条件的标的（规则过严或该日池特征不符）。\n\n")
            continue
        lines.append("\n| 名称 | 代码 | 竞价涨幅 | 竞价额 | 换手% | 涨幅/换手/额名次 | 原型距 | 收盘相对竞价 |\n")
        lines.append("|------|------|----------|--------|-------|------------------|--------|---------------|\n")
        for c in picks:
            lines.append(fmt_pick_row(c, df, close_maps[td], nm, prototype) + "\n")
        lines.append("\n")

    # 反例验证日回放
    lines.append("## 六、反例验证日（应命中 0 只）\n")
    lines.append(
        f"反例日：{', '.join(NEGATIVE_DATES)}。这些日期无合适标的，规则需确保命中为空。\n\n"
    )
    for nd in NEGATIVE_DATES:
        day = raw.get(nd)
        if not day:
            lines.append(f"### {nd}\n- 非交易日或数据缺失，跳过。\n\n")
            continue
        picks = best_picks.get(nd, [])
        pool_size = len(day["pool"]) if day else 0
        lines.append(f"### {nd}（前一日联合池 {pool_size} 只）\n")
        if not picks:
            lines.append("- 命中：**0** 只 ✓（符合预期）。\n\n")
        else:
            df_nd = dfs.get(nd)
            nm_nd = day["name_map"] if day else {}
            lines.append(f"- 命中：**{len(picks)}** 只 ✗（不符合预期，需进一步收紧）。\n")
            lines.append("\n| 名称 | 代码 | 竞价涨幅 | 竞价额 | 换手% | 涨幅/换手/额名次 | 原型距 | 收盘相对竞价 |\n")
            lines.append("|------|------|----------|--------|-------|------------------|--------|---------------|\n")
            for c in picks:
                lines.append(fmt_pick_row(c, df_nd, close_maps.get(nd, {}), nm_nd, prototype) + "\n")
            lines.append("\n")

    lines.append("## 七、结论分级\n")
    lines.append("- **参数与命中集合**：来自参考样本的直接包络推断，外推仍需继续验证。\n")
    lines.append("- **高置信**：严格首板池定义、竞价字段与排名为接口直接计算。\n")
    lines.append("- **中/低置信**：阈值组合依赖当前参考样本集合；若后续新增锚点，应重新包络一次。\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("Wrote", OUT_MD)


if __name__ == "__main__":
    main()
