# -*- coding: utf-8 -*-
"""三一传统策略 · 数据喂入器。

分阶段从不同数据源获取市场数据，写入 dashboard/data/ 下的 JSON 文件：
  premarket.json  - 盘前（昨日 tushare 日线数据，9:15 前写入）
  auction.json    - 竞价（9:25 tushare stk_auction 快照）
  intraday.json   - 盘中（9:30-15:00 腾讯行情实时，不依赖 tushare）
  postmarket.json - 盘后（当日 tushare 日线数据，15:30 后写入）

运行：
    python feeder.py              # 持续运行，按阶段自动切换数据源
    python feeder.py --once       # 只跑一次（当前阶段）
    python feeder.py --mock       # mock 模式（无需任何外部 API）
    python feeder.py --mock --once

研究参考，不构成投资建议。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("feeder")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

_REFACTORED_DIR = BASE_DIR.parent / "refactored"
if str(_REFACTORED_DIR) not in sys.path:
    sys.path.insert(0, str(_REFACTORED_DIR))


# ─────────────────────────────────────────────
# 交易阶段
# ─────────────────────────────────────────────

PHASE_PREMARKET  = "premarket"   # 开市前（昨日数据）
PHASE_AUCTION    = "auction"     # 9:15-9:30 集合竞价
PHASE_INTRADAY   = "intraday"    # 9:30-15:00 连续竞价（腾讯实时）
PHASE_CLOSING    = "closing"     # 15:00-15:30 等待收盘数据
PHASE_POSTMARKET = "postmarket"  # 15:30 后（当日 tushare）
PHASE_CLOSED     = "closed"      # 非交易日 / 夜间


def _current_phase() -> str:
    now = datetime.now()
    if now.weekday() >= 5:
        return PHASE_CLOSED
    hm = now.hour * 100 + now.minute
    if hm < 915:
        return PHASE_PREMARKET
    if hm <= 930:
        return PHASE_AUCTION
    if hm < 1500:
        return PHASE_INTRADAY
    if hm < 1530:
        return PHASE_CLOSING
    if hm <= 1600:
        return PHASE_POSTMARKET
    return PHASE_CLOSED


def _prev_trading_date_nodash() -> str:
    """上一个工作日日期（粗估，不处理法定节假日）。"""
    d = date.today()
    delta = 3 if d.weekday() == 0 else (2 if d.weekday() == 6 else 1)
    return (d - timedelta(days=delta)).strftime("%Y%m%d")


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def _save_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """写 .tmp 再 replace，防止读到残缺文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info("已写入 %s", path.name)


def _load_json_safe(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


# ─────────────────────────────────────────────
# 腾讯行情实时接口（盘中专用，不依赖 tushare）
# ─────────────────────────────────────────────

def _qq_prefix(ts_code: str) -> str:
    """002020.SZ → sz002020, 688456.SH → sh688456"""
    num, mkt = ts_code.upper().split(".")
    return ("sh" if mkt == "SH" else "sz") + num


def _fetch_qq_prices(ts_codes: list[str]) -> dict[str, dict[str, Any]]:
    """腾讯行情批量实时报价。返回 {ts_code: {price, pct, amount_yi}}。"""
    if not ts_codes:
        return {}
    import requests
    url = "http://qt.gtimg.cn/q=" + ",".join(_qq_prefix(c) for c in ts_codes)
    try:
        r = requests.get(url, timeout=10, proxies={"http": None, "https": None})
        r.raise_for_status()
    except Exception as exc:
        logger.warning("腾讯行情股票请求失败: %s", exc)
        return {}

    result: dict[str, dict[str, Any]] = {}
    for line in r.text.split(";"):
        if "~" not in line or '="' not in line:
            continue
        inner = line.split('="', 1)[1].split('"', 1)[0]
        p = inner.split("~")
        if len(p) < 6:
            continue
        try:
            code_raw = p[2]
            cur = float(p[3])
            pre_close = float(p[4])
            pct = (cur / pre_close - 1.0) * 100.0 if pre_close else 0.0
            amt_yi: Optional[float] = None
            if len(p) > 35 and p[35] and "/" in p[35]:
                segs = p[35].split("/")
                if len(segs) >= 3 and segs[2]:
                    amt_yi = float(segs[2]) / 1e8
        except (ValueError, IndexError):
            continue
        for tc in ts_codes:
            if tc.split(".")[0] == code_raw:
                result[tc] = {
                    "price": cur,
                    "pct": round(pct, 2),
                    "amount_yi": round(amt_yi, 4) if amt_yi else None,
                }
    return result


def _fetch_qq_indices() -> list[dict[str, Any]]:
    """腾讯行情实时指数（上证、深证、创业板、科创50）。"""
    import requests
    url = "http://qt.gtimg.cn/q=s_sh000001,s_sz399001,s_sz399006,s_sh000688"
    try:
        r = requests.get(url, timeout=10, proxies={"http": None, "https": None})
        r.raise_for_status()
    except Exception as exc:
        logger.warning("腾讯行情指数请求失败: %s", exc)
        return []

    _name_map = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指", "000688": "科创50"}
    out: list[dict[str, Any]] = []
    for line in r.text.split(";"):
        if "~" not in line or '="' not in line:
            continue
        inner = line.split('="', 1)[1].split('"', 1)[0]
        p = inner.split("~")
        if len(p) < 6:
            continue
        try:
            code = p[2]
            price = float(p[3])
            pct = float(p[5])
        except (ValueError, IndexError):
            continue
        out.append({"code": code, "name": _name_map.get(code, p[1]), "price": price, "pct": round(pct, 2)})
    return out


# ─────────────────────────────────────────────
# Mock 数据生成
# ─────────────────────────────────────────────

def _build_mock_premarket() -> dict[str, Any]:
    today = _today_str()
    return {
        "updated_at": _now_iso(),
        "trade_date": today,
        "indices": [
            {"name": "上证指数", "point": 3312.5, "key_support": 3280.0, "key_resistance": 3360.0,
             "ifthen": "若跌破 3280 → 仓位降至 ≤4 分（指数维度）；若站上 3360 → 可加仓"},
            {"name": "创业板指", "point": 1952.8, "key_support": 1920.0, "key_resistance": 1980.0,
             "ifthen": "低开幅度 > 1% 且不回补 → 持仓低开三思路启动"},
            {"name": "科创50", "point": 968.4, "key_support": 950.0, "key_resistance": 990.0, "ifthen": ""},
        ],
        "overseas": [
            {"name": "中国金龙 ETF", "symbol": "PGJ", "change_pct": 1.23, "note": "隔夜中概参考"},
            {"name": "KWEB", "symbol": "KWEB", "change_pct": 0.85, "note": "中概互联"},
            {"name": "纳指期货", "symbol": "NQ", "change_pct": -0.32, "note": "风险偏好参考"},
        ],
        "sentinels": [
            {"role": "多头风标候选", "code": "300930.SZ", "name": "鸿图科技",
             "yesterday_pct": 10.0, "reason": "连板爆量+高开候选，昨日5板，今日竞价高开 3.2%"},
            {"role": "空头风标候选", "code": "", "name": "", "yesterday_pct": None,
             "reason": "昨日最高板首要断板候选"},
        ],
        "themes": {
            "main": [
                {"name": "商业航天", "strength_pct": 4.8, "leaders": ["300930.SZ", "688456.SH", "002920.SZ"]},
                {"name": "人形机器人", "strength_pct": 3.1, "leaders": ["300433.SZ", "688169.SH"]},
            ],
            "sub": [{"name": "低空经济", "strength_pct": 1.9, "leaders": ["002803.SZ"]}],
        },
        "ladder": {"9": 0, "8": 0, "7": 0, "6": 0, "5": 1, "4": 2, "3": 5, "2": 12, "1": 38},
        "duanban": [
            {"code": "688456.SH", "name": "科思科技", "highest_board": 5, "reason": "商业航天 / 尾盘砸盘，情绪分歧"},
        ],
        "notes": "Mock 数据（feeder.py --mock）。研究参考，不构成投资建议。",
    }


def _build_mock_auction() -> dict[str, Any]:
    today = _today_str()
    return {
        "updated_at": _now_iso(),
        "trade_date": today,
        "themes_strength": [
            {"name": "商业航天", "avg_pct": 3.2, "leaders": ["300930.SZ", "688456.SH"]},
            {"name": "人形机器人", "avg_pct": 2.1, "leaders": ["300433.SZ", "688169.SH"]},
            {"name": "低空经济", "avg_pct": 0.8, "leaders": ["002803.SZ"]},
        ],
        "market_sentiment": {"score": 2.4, "label": "偏暖", "note": "竞价综合指标：上涨家数 > 下跌家数"},
        "core_intersection": [
            {"code": "300930.SZ", "name": "鸿图科技", "sector": "商业航天", "pct_chg": 3.2, "rank": 1,
             "note": "进价第一 + 换手第一 + 涨幅第一 同时命中"},
        ],
        "recommendations": [
            {"code": "300930.SZ", "name": "鸿图科技", "pct": 3.2, "rank": 1, "circ_mv": 42.5,
             "reason": "竞价三一：进价第一+换手第一+题材主线龙头", "concept": "商业航天",
             "concept_open_pct": 3.1, "concept_limitup_count": 3, "reason_tag": "sanyi", "small_trap": False},
            {"code": "002920.SZ", "name": "德赛西威", "pct": 2.8, "rank": 2, "circ_mv": 86.3,
             "reason": "竞价三一备选：题材排名第二，高开量能充分", "concept": "商业航天",
             "concept_open_pct": 3.1, "concept_limitup_count": 3, "reason_tag": "sanyi", "small_trap": False},
            {"code": "300776.SZ", "name": "帝尔激光", "pct": 9.8, "rank": 3, "circ_mv": 8.2,
             "reason": "小盘陷阱警告：流通 < 20 亿且换手 > 20%", "concept": "人形机器人",
             "concept_open_pct": 2.0, "concept_limitup_count": 2, "reason_tag": "sanyi", "small_trap": True},
        ],
        "fengdan_top5": [
            {"code": "300930.SZ", "name": "鸿图科技", "seal_amount_yi": 6.3,
             "lu_desc": "卫星通信+商业航天概念",
             "concept_auction_top3": [{"code": "300930.SZ", "name": "鸿图科技", "amount_wan": 6300}]},
            {"code": "300433.SZ", "name": "蓝思科技", "seal_amount_yi": 3.1,
             "lu_desc": "人形机器人零部件供应商",
             "concept_auction_top3": [{"code": "300433.SZ", "name": "蓝思科技", "amount_wan": 3100}]},
        ],
        "notes": "Mock 数据（feeder.py --mock）。研究参考，不构成投资建议。",
    }


def _build_mock_intraday() -> dict[str, Any]:
    today = _today_str()
    return {
        "updated_at": _now_iso(),
        "trade_date": today,
        "phase": "intraday",
        "indices": [
            {"code": "000001", "name": "上证指数", "price": 3298.5, "pct": -0.42,
             "key_support": 3280.0, "ok": True, "ifthen": "若跌破 3280 → 仓位降至 ≤4 分"},
            {"code": "399006", "name": "创业板指", "price": 1948.3, "pct": -0.23,
             "key_support": 1920.0, "ok": True, "ifthen": ""},
            {"code": "000688", "name": "科创50", "price": 961.5, "pct": -0.71,
             "key_support": 950.0, "ok": True, "ifthen": ""},
        ],
        "themes": [
            {"name": "商业航天", "avg_pct": 5.8,
             "leaders": ["300930.SZ", "688456.SH"],
             "leader_data": [
                 {"code": "300930.SZ", "pct": 10.0, "amount_yi": 12.3},
                 {"code": "688456.SH", "pct": 3.2, "amount_yi": 2.1},
             ]},
            {"name": "人形机器人", "avg_pct": 1.2,
             "leaders": ["300433.SZ"],
             "leader_data": [{"code": "300433.SZ", "pct": 1.2, "amount_yi": 5.4}]},
        ],
        "recs_live": [
            {"code": "300930.SZ", "name": "鸿图科技", "concept": "商业航天",
             "auction_pct": 3.2, "live_pct": 10.0, "live_amount_yi": 12.3,
             "reason": "三一买点", "small_trap": False},
        ],
        "notes": "Mock 盘中数据（feeder.py --mock）。研究参考，不构成投资建议。",
    }


def _build_mock_postmarket() -> dict[str, Any]:
    today = _today_str()
    return {
        "updated_at": _now_iso(),
        "trade_date": today,
        "limit_up_count": 115,
        "limit_down_count": 8,
        "ratio": round(115 / 8, 2),
        "blast_count": 23,
        "dragon_tiger": [
            {"code": "300930.SZ", "name": "鸿图科技", "seat": "中信证券上海分部",
             "direction": "买入", "amount_yi": 1.32, "note": "游资席位净买入，主力接力信号"},
        ],
        "pattern_hit_rate": [
            {"pattern": "三一买点", "triggered_count": 12, "hit_count": 9, "hit_rate": 0.75,
             "remark": "次日开盘 > 竞价买点 或 次日收盘 > 买点"},
            {"pattern": "一红定江山", "triggered_count": 8, "hit_count": 6, "hit_rate": 0.75, "remark": ""},
        ],
        "next_day_plan": [
            {"theme": "商业航天", "leaders": ["300930.SZ", "002920.SZ"],
             "watch_points": "明日若龙一高开3%+ 且封板稳，可考虑竞价三一接力；若低开则观察",
             "plan_tag": "接力"},
        ],
        "notes": "Mock 数据（feeder.py --mock）。研究参考，不构成投资建议。",
    }


def write_mock_data() -> None:
    """将四阶段 mock JSON 原子写入 data/ 目录。"""
    logger.info("=== Mock 模式：生成四阶段示例数据 ===")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _save_json_atomic(DATA_DIR / "premarket.json",  _build_mock_premarket())
    _save_json_atomic(DATA_DIR / "auction.json",    _build_mock_auction())
    _save_json_atomic(DATA_DIR / "intraday.json",   _build_mock_intraday())
    _save_json_atomic(DATA_DIR / "postmarket.json", _build_mock_postmarket())
    logger.info("Mock 数据写入完成。")


# ─────────────────────────────────────────────
# 真实数据 —— 盘前（昨日 tushare 日线）
# ─────────────────────────────────────────────

def _fetch_and_write_premarket(pro: Any, today: str, prev_nodash: str) -> None:
    """盘前：用昨日日期拉 tushare，避免当日 bar 未收盘返回空。"""
    index_map = {"上证指数": "000001.SH", "创业板指": "399006.SZ", "科创50": "000688.SH"}
    indices: list[dict[str, Any]] = []
    for name, ts_code in index_map.items():
        try:
            df = pro.index_daily(ts_code=ts_code, start_date=prev_nodash, end_date=prev_nodash)
            point = float(df.iloc[0]["close"]) if df is not None and not df.empty else None
        except Exception as exc:
            logger.warning("拉取指数 %s 失败: %s", ts_code, exc)
            point = None
        indices.append({
            "name": name, "point": point,
            "key_support": None, "key_resistance": None,
            "ifthen": (
                "若跌破 关键支撑 → 仓位降至 ≤4 分（指数维度）；若站上 关键压力 → 可加仓"
                if name == "上证指数" else
                "低开幅度 > 1% 且不回补 → 持仓低开三思路启动"
                if name == "创业板指" else ""
            ),
        })

    ladder: dict[str, int] = {str(k): 0 for k in range(1, 10)}
    duanban: list[dict[str, Any]] = []
    try:
        df_limit = pro.kpl_list(trade_date=prev_nodash, limit_type="U")
        if df_limit is not None and not df_limit.empty:
            col_days = next(
                (c for c in ("continuous_limit_up_days", "lu_time", "lim_days") if c in df_limit.columns),
                None,
            )
            if col_days:
                for _, row in df_limit.iterrows():
                    days = int(row.get(col_days) or 1)
                    key = str(min(days, 9))
                    ladder[key] = ladder.get(key, 0) + 1
    except Exception as exc:
        logger.warning("拉取涨停梯队失败: %s", exc)

    _save_json_atomic(DATA_DIR / "premarket.json", {
        "updated_at": _now_iso(),
        "trade_date": today,
        "data_date": prev_nodash,
        "indices": indices,
        "overseas": [
            {"name": "中国金龙 ETF", "symbol": "PGJ", "change_pct": None, "note": "隔夜中概参考"},
            {"name": "KWEB", "symbol": "KWEB", "change_pct": None, "note": "中概互联"},
            {"name": "纳指期货", "symbol": "NQ", "change_pct": None, "note": "风险偏好参考"},
        ],
        "sentinels": [
            {"role": "多头风标候选", "code": "", "name": "", "yesterday_pct": None, "reason": "由一红脚本产出"},
            {"role": "空头风标候选", "code": "", "name": "", "yesterday_pct": None, "reason": "昨日最高板候选"},
        ],
        "themes": {
            "main": [{"name": "", "strength_pct": None, "leaders": []}],
            "sub":  [{"name": "", "strength_pct": None, "leaders": []}],
        },
        "ladder": ladder,
        "duanban": duanban or [{"code": "", "name": "", "highest_board": 0, "reason": ""}],
        "notes": f"tushare 昨日数据（{prev_nodash}）。研究参考，不构成投资建议。",
    })


# ─────────────────────────────────────────────
# 真实数据 —— 竞价（tushare stk_auction 9:25）
# ─────────────────────────────────────────────

def _fetch_and_write_auction(pro_min: Any, today: str, today_nodash: str) -> None:
    auction: dict[str, Any] = {
        "updated_at": _now_iso(),
        "trade_date": today,
        "themes_strength": [],
        "market_sentiment": {"score": None, "label": "中性", "note": "tushare stk_auction"},
        "core_intersection": [],
        "recommendations": [],
        "fengdan_top5": [],
        "notes": f"tushare 竞价数据（{today}）。研究参考，不构成投资建议。",
    }
    try:
        df_auc = pro_min.stk_auction(trade_date=today_nodash)
        if df_auc is not None and not df_auc.empty:
            if "price" in df_auc.columns and "pre_close" in df_auc.columns:
                df_auc["pct_chg"] = (df_auc["price"] - df_auc["pre_close"]) / df_auc["pre_close"] * 100
            if "pct_chg" in df_auc.columns:
                med = float(df_auc["pct_chg"].median())
                label = (
                    "过热" if med >= 3.0 else
                    "偏暖" if med >= 1.0 else
                    "中性" if med >= -0.5 else
                    "偏冷" if med >= -2.0 else "冰点"
                )
                auction["market_sentiment"] = {
                    "score": round(med, 2), "label": label,
                    "note": f"竞价中位涨跌幅 {med:+.2f}%",
                }
    except Exception as exc:
        logger.warning("拉取竞价数据失败: %s", exc)
    _save_json_atomic(DATA_DIR / "auction.json", auction)


# ─────────────────────────────────────────────
# 真实数据 —— 盘中（腾讯行情，9:30-15:00）
# ─────────────────────────────────────────────

_TS_PAT = re.compile(r"^\d{6}\.(SH|SZ)$")


def _fetch_and_write_intraday() -> None:
    """盘中连续竞价：纯腾讯行情实时接口，不依赖 tushare。"""
    auc = _load_json_safe(DATA_DIR / "auction.json")
    pre = _load_json_safe(DATA_DIR / "premarket.json")

    # 收集要追踪的股票代码（来自竞价阶段写入的 auction.json）
    ts_codes: set[str] = set()
    for theme in auc.get("themes_strength") or []:
        for ldr in theme.get("leaders") or []:
            if _TS_PAT.match(str(ldr)):
                ts_codes.add(ldr)
    for rec in auc.get("recommendations") or []:
        c = rec.get("code") or ""
        if _TS_PAT.match(c):
            ts_codes.add(c)
    for fda in auc.get("fengdan_top5") or []:
        c = fda.get("code") or ""
        if _TS_PAT.match(c):
            ts_codes.add(c)

    prices = _fetch_qq_prices(list(ts_codes))
    indices_raw = _fetch_qq_indices()

    # 指数实时价格 vs 盘前写入的关键支撑
    pre_idx_map = {idx["name"]: idx for idx in pre.get("indices") or []}
    indices_status: list[dict[str, Any]] = []
    for idx in indices_raw:
        pinfo = pre_idx_map.get(idx["name"]) or {}
        support = pinfo.get("key_support")
        ok: Optional[bool] = (idx["price"] >= support) if support is not None else None
        indices_status.append({
            **idx,
            "key_support": support,
            "ok": ok,
            "ifthen": pinfo.get("ifthen") or "",
        })

    # 题材龙头实时强度（均涨）
    themes_live: list[dict[str, Any]] = []
    for theme in auc.get("themes_strength") or []:
        leaders = theme.get("leaders") or []
        pcts = [prices[c]["pct"] for c in leaders if c in prices and prices[c].get("pct") is not None]
        avg_pct = round(sum(pcts) / len(pcts), 2) if pcts else None
        leader_data = [
            {
                "code": c,
                "pct": prices[c]["pct"] if c in prices else None,
                "amount_yi": prices[c].get("amount_yi") if c in prices else None,
            }
            for c in leaders[:3]
        ]
        themes_live.append({
            "name": theme.get("name") or "",
            "avg_pct": avg_pct,
            "leaders": leaders,
            "leader_data": leader_data,
        })

    # 竞价推荐标的实时状态（买入后是否还强）
    recs_live: list[dict[str, Any]] = []
    for rec in auc.get("recommendations") or []:
        code = rec.get("code") or ""
        pdata = prices.get(code) or {}
        recs_live.append({
            "code": code,
            "name": rec.get("name") or "",
            "concept": rec.get("concept") or "",
            "auction_pct": rec.get("pct"),    # 竞价时的涨幅（基准）
            "live_pct": pdata.get("pct"),      # 当前实时涨幅
            "live_amount_yi": pdata.get("amount_yi"),
            "reason": rec.get("reason") or "",
            "small_trap": bool(rec.get("small_trap")),
        })

    _save_json_atomic(DATA_DIR / "intraday.json", {
        "updated_at": _now_iso(),
        "trade_date": _today_str(),
        "phase": "intraday",
        "indices": indices_status,
        "themes": themes_live,
        "recs_live": recs_live,
        "notes": f"腾讯行情实时数据 ({_now_iso()})。研究参考，不构成投资建议。",
    })
    logger.info("盘中实时数据已写入，追踪 %d 只股票", len(ts_codes))


# ─────────────────────────────────────────────
# 真实数据 —— 盘后（tushare 当日，15:30+）
# ─────────────────────────────────────────────

def _fetch_and_write_postmarket(pro: Any, today: str, today_nodash: str) -> None:
    limit_up = limit_down = 0
    try:
        df_up = pro.kpl_list(trade_date=today_nodash, limit_type="U")
        df_dn = pro.kpl_list(trade_date=today_nodash, limit_type="D")
        limit_up   = len(df_up) if df_up is not None else 0
        limit_down = len(df_dn) if df_dn is not None else 0
    except Exception as exc:
        logger.warning("拉取涨跌停比失败: %s", exc)

    _save_json_atomic(DATA_DIR / "postmarket.json", {
        "updated_at": _now_iso(),
        "trade_date": today,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "ratio": round(limit_up / max(limit_down, 1), 2) if limit_up else None,
        "blast_count": 0,
        "dragon_tiger": [],
        "pattern_hit_rate": [],
        "next_day_plan": [],
        "notes": f"tushare 当日数据（{today}）。研究参考，不构成投资建议。",
    })


# ─────────────────────────────────────────────
# 调度：阶段分派
# ─────────────────────────────────────────────

def _fetch_real_data() -> bool:
    """按当前交易阶段选择数据源，返回是否成功。"""
    phase = _current_phase()
    today = _today_str()
    today_nodash = today.replace("-", "")

    if phase == PHASE_CLOSED:
        logger.info("非交易日/夜间，跳过数据拉取")
        return True

    if phase == PHASE_CLOSING:
        logger.info("15:00-15:30 等待收盘数据…")
        return True

    if phase == PHASE_INTRADAY:
        # 盘中：纯腾讯行情，不需要 tushare
        _fetch_and_write_intraday()
        return True

    # 盘前 / 竞价 / 盘后 阶段需要 tushare
    try:
        from common.config import init_tushare_clients  # type: ignore
    except ImportError as exc:
        logger.warning("无法导入 common.config: %s → 降级 mock", exc)
        return False

    try:
        _, pro, pro_min = init_tushare_clients()
    except Exception as exc:
        logger.warning("tushare 初始化失败: %s → 降级 mock", exc)
        return False

    prev_nodash = _prev_trading_date_nodash()

    try:
        if phase == PHASE_PREMARKET:
            _fetch_and_write_premarket(pro, today, prev_nodash)
        elif phase == PHASE_AUCTION:
            _fetch_and_write_premarket(pro, today, prev_nodash)
            _fetch_and_write_auction(pro_min, today, today_nodash)
        elif phase == PHASE_POSTMARKET:
            _fetch_and_write_postmarket(pro, today, today_nodash)
    except Exception as exc:
        logger.exception("数据拉取异常: %s", exc)
        return False

    return True


def _run_once(mock_mode: bool) -> None:
    if mock_mode:
        write_mock_data()
        return
    if not _fetch_real_data():
        logger.warning("真实数据拉取失败，降级写入 mock 数据")
        write_mock_data()


def _loop_interval() -> int:
    """根据当前阶段返回刷新间隔秒。"""
    phase = _current_phase()
    if phase == PHASE_AUCTION:
        return 30    # 竞价：30s
    if phase == PHASE_INTRADAY:
        return 60    # 盘中：60s
    return 300       # 其余：5min


def _seconds_to_next_open() -> int:
    now = datetime.now()
    target = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= target or now.weekday() >= 5:
        ahead = 1
        while (now + timedelta(days=ahead)).weekday() >= 5:
            ahead += 1
        target = (now + timedelta(days=ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    return max(int((target - now).total_seconds()), 60)


def run_loop(mock_mode: bool) -> None:
    logger.info("feeder 启动 · 模式=%s · 数据目录=%s", "mock" if mock_mode else "real", DATA_DIR)
    while True:
        phase = _current_phase()
        if phase == PHASE_CLOSED:
            wait = min(_seconds_to_next_open(), 1800)
            logger.info("非交易时段，等待 %d 分钟…", wait // 60)
            time.sleep(wait)
            continue
        try:
            _run_once(mock_mode)
        except Exception as exc:
            logger.exception("主循环异常: %s", exc)
        interval = _loop_interval()
        logger.info("下次刷新在 %d 秒后（阶段=%s）…", interval, phase)
        time.sleep(interval)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="三一传统策略数据喂入器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python feeder.py --mock --once    # mock 数据写一次，用于 Tab 展示测试\n"
            "  python feeder.py --mock           # mock 持续运行\n"
            "  python feeder.py                  # 真实数据持续运行（按交易阶段自动切换）\n"
        ),
    )
    parser.add_argument("--once",  action="store_true", help="只写一次数据后退出")
    parser.add_argument("--mock",  action="store_true", help="使用 mock 数据（无需外部 API）")
    parser.add_argument(
        "--data-dir", type=str, default=str(DATA_DIR),
        help=f"数据写入目录（默认 {DATA_DIR}）",
    )
    return parser


def main() -> None:
    global DATA_DIR
    args = _build_arg_parser().parse_args()
    DATA_DIR = Path(args.data_dir).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("feeder 启动 · 时钟=%s · data_dir=%s", _now_iso(), DATA_DIR)
    if args.once:
        _run_once(mock_mode=args.mock)
        return
    run_loop(mock_mode=args.mock)


if __name__ == "__main__":
    main()
