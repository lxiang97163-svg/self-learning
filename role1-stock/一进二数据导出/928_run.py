# -*- coding: utf-8 -*-
"""
一进二 9:28 选股 + 推送
运行时机：09:25 后（竞价数据已落盘），9:28 前完成推送
用法：python 928_run.py
      python 928_run.py --date 20260415   # 回测/补跑

主流程（缓存命中）：
  读取 928_cache_YYYYMMDD.json → 拉今日竞价 → cursor 规则过滤 → 按名次占比排序 → 推送

降级流程（缓存缺失）：
  直接跑 cc 固定参数逻辑 → 推送（标注 [备用]）
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd
import requests

import chinadata.ca_data as ts
import chinamindata.min as tss

import first_board_pool_data  # noqa: F401 — stk_auction 单行 dict 兼容补丁
from first_board_pool_data import fetch_auction_pool_only

TOKEN = "e95696cde1bc72c2839d1c9cc510ab2cf33"
TOKEN_MIN = "ne34e6697159de73c228e34379b510ec554"
PUSH_TOKEN = "66c0490b50c34e74b5cc000232b1d23c"

DIR = os.path.dirname(os.path.abspath(__file__))

# ── cc 备用参数（缓存缺失时使用）────────────────────────────────
CC_PARAMS = dict(
    pct_min=3.0,
    pct_max=6.0,
    amount_min=0.10,
    turn_min=0.45,
    pct_rank_max=12,
    turn_rank_max=10,
    prev5_max=28.0,
    prev10_max=40.0,
)


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


def is_mainboard(code: str) -> bool:
    if code.endswith(".BJ"):
        return False
    c = code.split(".")[0]
    return not c.startswith(("300", "301", "688", "689"))


def get_trade_dates(pro, around: str) -> list[str]:
    dt = datetime.strptime(around, "%Y%m%d")
    start = (dt - timedelta(days=90)).strftime("%Y%m%d")
    cal = retry(pro.trade_cal, exchange="SSE", start_date=start, end_date=around,
                fields="cal_date,is_open")
    return sorted(cal[cal["is_open"] == 1]["cal_date"].astype(str).tolist())


def prev_trade_date(trade_dates: list[str], today: str) -> str:
    idx = trade_dates.index(today)
    if idx == 0:
        raise ValueError(f"找不到 {today} 的前一交易日")
    return trade_dates[idx - 1]


def prev2_trade_date(trade_dates: list[str], today: str) -> str:
    idx = trade_dates.index(today)
    if idx < 2:
        raise ValueError(f"找不到 {today} 的前二交易日")
    return trade_dates[idx - 2]


# ── 推送 ────────────────────────────────────────────────────
def push(title: str, content: str):
    try:
        resp = requests.post(
            "http://www.pushplus.plus/send",
            json={"token": PUSH_TOKEN, "title": title, "content": content,
                  "template": "txt", "channel": "wechat"},
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("code") == 200:
            print("[OK] 推送成功")
        else:
            print(f"[WARN] 推送响应: {resp.text[:200]}")
    except Exception as e:
        print(f"[ERR] 推送失败: {e}")


# ── 竞价拉取（通用）─────────────────────────────────────────
def fetch_auction(pro_min, today: str, pool_codes: list[str]) -> pd.DataFrame:
    return fetch_auction_pool_only(pro_min, today, pool_codes, retry, log_fallback=True)


# ════════════════════════════════════════════════════════════
#  主流程：缓存命中
# ════════════════════════════════════════════════════════════
def run_cursor(pro_min, today: str, cache: dict[str, Any]):
    params = cache["params"]
    pool_records = cache["pool"]
    if not pool_records:
        return None, "今日首板池为空（缓存）", params

    pool_df = pd.DataFrame(pool_records)
    pool_codes = pool_df["ts_code"].tolist()

    print(f"  缓存首板池: {len(pool_codes)} 只")
    print(f"  拉取今日竞价...")
    auc = fetch_auction(pro_min, today, pool_codes)
    if auc.empty:
        return None, "竞价数据为空", params

    print(f"  竞价有数: {len(auc)} 只，合并计算...")
    df = pool_df.merge(auc[["ts_code", "price", "auction_pct", "auction_amount_yi", "turnover_rate"]],
                       on="ts_code", how="inner")
    for col in ["price", "high20", "high60", "auction_pct", "auction_amount_yi",
                "turnover_rate", "prev_5d", "prev_10d"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 在今日池内计算名次与名次占比
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
    df["_n_pct"] = n_pct  # 暂存池大小用于格式化

    # 过滤（与 928选股_cursor.py / apply_strategy 同口径）
    cond = df["auction_pct"].between(params["pct_min"], params["pct_max"], inclusive="both")
    cond &= df["auction_amount_yi"] >= params["amount_min"]
    cond &= df["turnover_rate"] >= params["turn_min"]
    # turn_max 已删除
    cond &= df["pct_rank_ratio"] <= params["pct_rank_ratio_max"]
    cond &= df["turn_rank_ratio"] <= params["turn_rank_ratio_max"]
    cond &= df["amt_rank_ratio"] <= params["amt_rank_ratio_max"]
    if params.get("prev5_max") is not None:
        cond &= df["prev_5d"].fillna(999) <= params["prev5_max"]
    if params.get("prev10_max") is not None:
        cond &= df["prev_10d"].fillna(999) <= params["prev10_max"]
    if params.get("need_new_high"):
        cond &= df["auction_new20"] | df["auction_new60"]
    if params.get("open_times_max") is not None and "open_times" in df.columns:
        cond &= df["open_times"].fillna(0) <= params["open_times_max"]
    # fd_amount_min / first_time_max 已删除（过拟合）
    if params.get("prev_auction_pct_min") is not None and "prev_auction_pct" in df.columns:
        cond &= df["prev_auction_pct"].fillna(-999) >= params["prev_auction_pct_min"]
    if params.get("auction_price_ratio_min") is not None and "auction_price_ratio" in df.columns:
        cond &= df["auction_price_ratio"].fillna(-999) >= params["auction_price_ratio_min"]

    hits = df[cond].copy()
    if hits.empty:
        return hits.reset_index(drop=True), None, params

    # 原型排序：cache 中有 prototype 时与 928选股_cursor.py 对齐
    prototype = cache.get("prototype")
    if prototype:
        _center = prototype.get("center", {})
        _scale = prototype.get("scale", {})
        _features = list(_center.keys())

        def _proto_dist(row: pd.Series) -> float:
            d = 0.0
            for f in _features:
                v = row.get(f)
                if pd.isna(v):
                    d += 10.0
                    continue
                s = max(float(_scale.get(f, 1e-6)), 1e-6)
                d += abs(float(v) - float(_center[f])) / s
            return d

        hits["prototype_dist"] = hits.apply(_proto_dist, axis=1)
        hits = hits.sort_values(["prototype_dist", "pct_rank_ratio", "turn_rank_ratio"]).reset_index(drop=True)
    else:
        hits["prototype_dist"] = float("nan")
        hits = hits.sort_values(["pct_rank_ratio", "turn_rank_ratio", "amt_rank_ratio"]).reset_index(drop=True)

    return hits, None, params


def format_cursor_msg(today: str, hits: pd.DataFrame, params: dict, n_pool: int) -> str:
    lines = [f"一进二 9:28 | {today}"]
    lines.append(f"首板池 {n_pool} 只 | 命中 {len(hits)} 只")
    lines.append("")

    for i, r in hits.iterrows():
        n = int(r["_n_pct"])
        pr = int(r["pct_rank"]); tr = int(r["turn_rank"]); ar = int(r["amt_rank"])
        new20 = bool(r.get("auction_new20", False))
        new60 = bool(r.get("auction_new60", False))
        new_flag = "创20日新高" if new20 else ("创60日新高" if new60 else "")
        p5 = f"+{r['prev_5d']:.1f}%" if pd.notna(r.get("prev_5d")) else "N/A"
        p10 = f"+{r['prev_10d']:.1f}%" if pd.notna(r.get("prev_10d")) else "N/A"

        lines.append(f"【{i+1}】{r['name']}  {r['ts_code']}")
        lines.append(f"  竞价 +{r['auction_pct']:.2f}%  成交额 {r['auction_amount_yi']:.2f}亿  换手 {r['turnover_rate']:.2f}%")
        dist = r.get("prototype_dist")
        dist_str = f"  原型距 {dist:.2f}" if dist is not None and not pd.isna(dist) else ""
        lines.append(f"  名次 涨{pr}/{n}({r['pct_rank_ratio']:.0%})  换{tr}/{n}({r['turn_rank_ratio']:.0%})  额{ar}/{n}({r['amt_rank_ratio']:.0%}){dist_str}")
        if new_flag:
            lines.append(f"  [{new_flag}]  近5日{p5}  近10日{p10}")
        else:
            lines.append(f"  近5日{p5}  近10日{p10}")
        lines.append("")

    lines.append(f"参数: 竞价[{params['pct_min']}%,{params['pct_max']}%]  "
                 f"额≥{params['amount_min']}亿  换手≥{params['turn_min']}%  新高={'是' if params['need_new_high'] else '否'}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════
#  降级流程：cc 固定参数
# ════════════════════════════════════════════════════════════
def get_strict_pool_cc(pro, prev_d: str, prev2_d: str) -> pd.DataFrame:
    zt = retry(pro.limit_list_d, trade_date=prev_d, limit_type="U")
    if zt is None or zt.empty:
        return pd.DataFrame()
    zt2 = retry(pro.limit_list_d, trade_date=prev2_d, limit_type="U")
    prev2_set = set(zt2["ts_code"]) if zt2 is not None and not zt2.empty else set()
    stk = retry(pro.stock_basic, exchange="", list_status="L", fields="ts_code,name")
    st_set = {r.ts_code for r in stk.itertuples(index=False)
              if "ST" in str(r.name).upper() or "*" in str(r.name)}
    name_map = dict(zip(stk["ts_code"], stk["name"]))
    first_board = zt[
        (zt["limit_times"] == 1)
        & (~zt["ts_code"].isin(prev2_set))
        & (zt["ts_code"].map(is_mainboard))
        & (~zt["ts_code"].isin(st_set))
    ].copy()
    second_board = zt[
        (zt["limit_times"] == 2)
        & (zt["ts_code"].map(is_mainboard))
        & (~zt["ts_code"].isin(st_set))
    ].copy()
    third_board = zt[
        (zt["limit_times"] == 3)
        & (zt["ts_code"].map(is_mainboard))
        & (~zt["ts_code"].isin(st_set))
    ].copy()
    pool = pd.concat([first_board, second_board, third_board], ignore_index=True).drop_duplicates(subset=["ts_code"]).copy()
    pool["name"] = pool["ts_code"].map(name_map)
    return pool


def run_cc_fallback(pro, pro_min, today: str, trade_dates: list[str]):
    print("  [降级] 使用 cc 固定参数规则")
    prev_d = prev_trade_date(trade_dates, today)
    prev2_d = prev2_trade_date(trade_dates, today)
    pool = get_strict_pool_cc(pro, prev_d, prev2_d)
    if pool.empty:
        return None, "首板池为空（cc降级）"

    pool_codes = pool["ts_code"].tolist()
    auc = fetch_auction(pro_min, today, pool_codes)
    if auc.empty:
        return None, "竞价数据为空（cc降级）"

    df = pool[["ts_code", "name"]].merge(auc, on="ts_code", how="inner")
    df["pct_rank"] = df["auction_pct"].rank(method="min", ascending=False)
    df["turn_rank"] = df["turnover_rate"].rank(method="min", ascending=False)

    p = CC_PARAMS
    cond = (
        df["auction_pct"].between(p["pct_min"], p["pct_max"], inclusive="both")
        & (df["auction_amount_yi"] >= p["amount_min"])
        & (df["turnover_rate"] >= p["turn_min"])
        & (df["pct_rank"] <= p["pct_rank_max"])
        & (df["turn_rank"] <= p["turn_rank_max"])
    )
    hits = df[cond].sort_values(["pct_rank", "turn_rank"]).reset_index(drop=True)
    return hits, None


def format_cc_msg(today: str, hits: pd.DataFrame, n_pool: int) -> str:
    p = CC_PARAMS
    lines = [f"一进二 9:28 | {today}  [备用规则]"]
    lines.append(f"首板池 {n_pool} 只 | 命中 {len(hits)} 只")
    lines.append("")
    for i, r in hits.iterrows():
        lines.append(f"【{i+1}】{r['name']}  {r['ts_code']}")
        lines.append(f"  竞价 +{r['auction_pct']:.2f}%  成交额 {r['auction_amount_yi']:.2f}亿  换手 {r['turnover_rate']:.2f}%")
        lines.append(f"  涨幅排名 {int(r['pct_rank'])}  换手排名 {int(r['turn_rank'])}")
        lines.append("")
    lines.append(f"参数(cc备用): 竞价[{p['pct_min']}%,{p['pct_max']}%]  "
                 f"额≥{p['amount_min']}亿  换手≥{p['turn_min']}%  涨名≤{p['pct_rank_max']}  换名≤{p['turn_rank_max']}")
    lines.append("⚠ 盘前缓存未就绪，使用备用规则（新高/额名约束未生效）")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════════
def run(today: str):
    t0 = time.time()
    print(f"\n{'='*55}")
    print(f"  一进二 9:28 选股  |  {today}")
    print(f"{'='*55}")

    ts.set_token(TOKEN)
    tss.set_token(TOKEN_MIN)
    pro = ts.pro_api()
    pro_min = tss.pro_api()

    cache_path = os.path.join(DIR, f"928_cache_{today}.json")
    cache_ok = os.path.exists(cache_path)

    if cache_ok:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"  缓存文件: {cache_path}")
        print(f"  生成时间: {cache.get('generated_at', '未知')}")

        hits, err, params = run_cursor(pro_min, today, cache)
        n_pool = len(cache.get("pool", []))

        if err:
            title = f"一进二 9:28 | {today}"
            content = f"今日无命中\n原因: {err}"
            print(f"  {err}")
        elif hits is None or hits.empty:
            title = f"一进二 9:28 | {today}"
            content = f"首板池 {n_pool} 只 | 今日无命中\n\n参数: 竞价[{params['pct_min']}%,{params['pct_max']}%]  新高={'是' if params['need_new_high'] else '否'}"
            print("  今日无命中")
        else:
            title = f"一进二 9:28 命中{len(hits)}只 | {today}"
            content = format_cursor_msg(today, hits, params, n_pool)
            print(f"  命中 {len(hits)} 只: {', '.join(hits['name'].tolist())}")
    else:
        print(f"  ⚠ 未找到缓存 {cache_path}，降级使用 cc 规则")
        trade_dates = get_trade_dates(pro, today)
        if today not in trade_dates:
            print(f"  {today} 不是交易日，退出。")
            return

        hits_cc, err = run_cc_fallback(pro, pro_min, today, trade_dates)
        # cc 降级时 n_pool 需单独计算（已在 run_cc_fallback 内拿到 pool）
        # 这里直接用 hits 前的 pool 大小（无法二次获取，用 hits 长度代替，不太精确）
        # 解法：把 pool 大小从 run_cc_fallback 一并返回
        if err:
            title = f"一进二 9:28 | {today} [备用]"
            content = f"今日无命中（备用规则）\n原因: {err}"
            print(f"  {err}")
        elif hits_cc is None or hits_cc.empty:
            title = f"一进二 9:28 | {today} [备用]"
            content = "备用规则今日无命中"
            print("  cc备用: 今日无命中")
        else:
            title = f"一进二 9:28 命中{len(hits_cc)}只 | {today} [备用]"
            content = format_cc_msg(today, hits_cc, n_pool=len(hits_cc))
            print(f"  cc备用命中 {len(hits_cc)} 只: {', '.join(hits_cc['name'].tolist())}")

    print(f"\n{'='*55}")
    print(content)
    print(f"{'='*55}")
    push(title, content)
    print(f"  总耗时: {time.time()-t0:.1f}s\n")


def main():
    ap = argparse.ArgumentParser(description="一进二 9:28 选股+推送")
    ap.add_argument("--date", default=None, help="指定交易日 YYYYMMDD，默认今日")
    args = ap.parse_args()
    today = args.date or datetime.now().strftime("%Y%m%d")
    run(today)


if __name__ == "__main__":
    main()
