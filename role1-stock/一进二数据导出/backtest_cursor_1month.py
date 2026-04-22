# -*- coding: utf-8 -*-
"""
逐日回测：按当前 Cursor 定稿参数（rule_params.json）逐日筛首板∪二板∪三板池竞价，输出命中标的及收益。

默认日期范围：2026-04-01 ~ 2026-04-20（完整验证区间）。

收益口径（按用户定义）：
  当日收益(百分点) = 收盘涨幅 - 买入涨幅
  其中「买入涨幅」= 9:25 竞价价相对前收涨幅 `auction_pct`；
  「收盘涨幅」= T 日 `daily` 的 `pct_chg`（相对前收，与竞价同一基准）。

另附一列 `close_vs_auction_pct` = (收盘 - 竞价价) / 竞价价 * 100，便于对照。

用法（在「一进二数据导出」目录下）：
  python backtest_cursor_1month.py
  python backtest_cursor_1month.py --start 20260401 --end 20260420
  python backtest_cursor_1month.py --end 20260417
  python backtest_cursor_1month.py --days 30
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent
if str(DIR) not in sys.path:
    sys.path.insert(0, str(DIR))

from first_board_pool_data import fetch_close_pool_parallel  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("rule_builder", DIR / "构建一进二选股规则.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("无法加载 构建一进二选股规则.py")
rb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rb)


DEFAULT_START = "20260401"
DEFAULT_END = "20260420"


def main() -> None:
    ap = argparse.ArgumentParser(description="Cursor 规则回测（默认 04-01~04-20）")
    ap.add_argument("--start", default=None, help="窗口起始日 YYYYMMDD，默认 20260401")
    ap.add_argument("--end", default=None, help="窗口结束日 YYYYMMDD，默认 20260420")
    ap.add_argument("--days", type=int, default=None,
                    help="向前覆盖的自然日天数（提供此参数时以 end 为基准向前推，忽略 start/默认区间）")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    end_s = args.end or DEFAULT_END
    if args.days is not None:
        # 兼容旧用法：--days 向前推
        end_dt = datetime.strptime(end_s, "%Y%m%d")
        cut_s = (end_dt - timedelta(days=int(args.days))).strftime("%Y%m%d")
    else:
        cut_s = args.start or DEFAULT_START

    pro, pro_min = rb.init_apis()
    seed = sorted({cut_s, end_s, *rb.FETCH_DATES})
    full_tds = rb.get_all_trade_dates(pro, seed)
    month_tds = [d for d in full_tds if cut_s <= d <= end_s]

    name_map, st_set = rb.get_name_st_maps(pro)

    # 优先从 rule_params.json 读取已收紧参数（含反例验证）
    rule_json = DIR / "rule_params.json"
    if rule_json.exists():
        import json
        with open(rule_json, encoding="utf-8") as _f:
            _rp = json.load(_f)
        params = _rp["params"]
        prototype = _rp["prototype"]
        print(f"[参数来源] rule_params.json（已含反例收紧）")
    else:
        # 降级：重新拉锚定日推导（不含反例收紧）
        print(f"[参数来源] 重新从锚定日推导（rule_params.json 不可用）")
        raw_anchor: dict[str, dict] = {}
        dfs_anchor: dict[str, pd.DataFrame] = {}
        for td in rb.FETCH_DATES:
            if td not in full_tds:
                raise SystemExit(f"锚定日 {td} 不在交易日历中")
            print(f"[锚定] 拉取 {td} …")
            raw_anchor[td] = rb.collect_day(pro, pro_min, full_tds, name_map, st_set, td)
            if not raw_anchor[td]:
                raise SystemExit(f"锚定日 {td} collect_day 失败")
            dfs_anchor[td] = rb.build_df(raw_anchor[td])
            if dfs_anchor[td] is None or dfs_anchor[td].empty:
                raise SystemExit(f"锚定日 {td} build_df 为空")
        ref = rb.get_reference_rows(dfs_anchor)
        params = rb.derive_params(ref)
        prototype = rb.build_prototype(ref)

    print(f"[参数] pct [{params['pct_min']},{params['pct_max']}] "
          f"额≥{params['amount_min']} 换手[{params['turn_min']},{params.get('turn_max','∞')}] "
          f"新高={params['need_new_high']}")

    rows_out: list[dict] = []
    for i, td in enumerate(month_tds):
        print(f"[回测] ({i + 1}/{len(month_tds)}) {td} …")
        try:
            rb.prev_dates(full_tds, td)
        except ValueError:
            continue
        day = rb.collect_day(pro, pro_min, full_tds, name_map, st_set, td)
        if not day:
            rows_out.append({
                "trade_date": td,
                "ts_code": "",
                "name": "",
                "skip_reason": "无池或竞价",
                "n_pool": 0,
                "n_hit": 0,
            })
            continue
        df = rb.build_df(day)
        if df is None or df.empty:
            rows_out.append({
                "trade_date": td,
                "ts_code": "",
                "name": "",
                "skip_reason": "build_df 空",
                "n_pool": len(day.get("pool", [])),
                "n_hit": 0,
            })
            continue
        hits = rb.apply_params(df, params)
        ordered = rb.sort_codes_by_prototype(hits, df, prototype)
        if not ordered:
            rows_out.append({
                "trade_date": td,
                "ts_code": "",
                "name": "",
                "skip_reason": "无命中",
                "n_pool": len(df),
                "n_hit": 0,
            })
            continue
        close_map = fetch_close_pool_parallel(pro, td, ordered, rb._invoke)
        n_pool = len(df)
        for rank, code in enumerate(ordered, start=1):
            r = df[df["ts_code"] == code]
            if r.empty:
                continue
            r0 = r.iloc[0]
            buy_pct = float(r0["auction_pct"]) if pd.notna(r0.get("auction_pct")) else None
            ap_price = float(r0["price"]) if pd.notna(r0.get("price")) else None
            nm = str(r0.get("name", "")) if "name" in r0.index else name_map.get(code, "")
            cm = close_map.get(code) or {}
            close_px = cm.get("close")
            close_pct = cm.get("pct_chg")
            pnl_pp = None
            if close_pct is not None and buy_pct is not None:
                pnl_pp = float(close_pct) - float(buy_pct)
            vs_auc = None
            if close_px is not None and ap_price is not None and ap_price > 0:
                vs_auc = (float(close_px) - ap_price) / ap_price * 100.0
            apr = float(r0["auction_price_ratio"]) if "auction_price_ratio" in r0.index and pd.notna(r0.get("auction_price_ratio")) else None
            prev_ap = float(r0["prev_auction_pct"]) if "prev_auction_pct" in r0.index and pd.notna(r0.get("prev_auction_pct")) else None
            open_t = float(r0["open_times"]) if "open_times" in r0.index and pd.notna(r0.get("open_times")) else None
            fd_amt = float(r0["fd_amount"]) if "fd_amount" in r0.index and pd.notna(r0.get("fd_amount")) else None
            first_t = float(r0["first_time"]) if "first_time" in r0.index and pd.notna(r0.get("first_time")) else None
            tr_ratio = float(r0["turnover_ratio"]) if "turnover_ratio" in r0.index and pd.notna(r0.get("turnover_ratio")) else None
            turn_r = float(r0["turnover_rate"]) if "turnover_rate" in r0.index and pd.notna(r0.get("turnover_rate")) else None
            amt_yi = float(r0["auction_amount_yi"]) if "auction_amount_yi" in r0.index and pd.notna(r0.get("auction_amount_yi")) else None
            prev5 = float(r0["prev_5d"]) if "prev_5d" in r0.index and pd.notna(r0.get("prev_5d")) else None
            prev10 = float(r0["prev_10d"]) if "prev_10d" in r0.index and pd.notna(r0.get("prev_10d")) else None
            rows_out.append({
                "trade_date": td,
                "ts_code": code,
                "name": nm,
                "skip_reason": "",
                "n_pool": n_pool,
                "n_hit": len(ordered),
                "hit_rank": rank,
                "auction_pct": buy_pct,
                "auction_amount_yi": amt_yi,
                "turnover_rate": turn_r,
                "prev_auction_pct": prev_ap,
                "auction_price_ratio": apr,
                "prev_5d": prev5,
                "prev_10d": prev10,
                "open_times": open_t,
                "fd_amount": fd_amt,
                "first_time": first_t,
                "turnover_ratio": tr_ratio,
                "close_pct_chg": float(close_pct) if close_pct is not None else None,
                "pnl_close_pct_minus_buy_pct": pnl_pp,
                "close_vs_auction_pct": vs_auc,
            })

    out_df = pd.DataFrame(rows_out)
    out_path = DIR / f"backtest_cursor_1m_{end_s}.csv"
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] 已写入 {out_path} 行数={len(out_df)}")

    hit_df = out_df[out_df["ts_code"].astype(str).str.len() > 0].copy()
    if not hit_df.empty and hit_df["pnl_close_pct_minus_buy_pct"].notna().any():
        m = hit_df["pnl_close_pct_minus_buy_pct"].mean()
        print(f"[统计] 命中样本数 {len(hit_df)}，"
              f"「收盘涨幅-买入涨幅」均值 {m:.3f} 百分点")


if __name__ == "__main__":
    main()
