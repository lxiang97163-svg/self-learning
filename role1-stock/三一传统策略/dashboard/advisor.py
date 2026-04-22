"""三一传统策略 · 盯盘规则引擎。

读取 data/premarket.json + data/auction.json + data/postmarket.json，
基于规则生成盯盘短句，写入 data/advisor.json（最新在前，最多 20 条）。

运行：
    python advisor.py              # 每 60s 循环
    python advisor.py --once       # 只跑一次
    python advisor.py --interval 30

研究参考，不构成投资建议。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("advisor")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "data"

# 运行期可被 CLI --data-dir 覆盖（保持默认为 dashboard/data/）
DATA_DIR: Path = DEFAULT_DATA_DIR

MAX_MESSAGES = 20
DEDUPE_WINDOW_SEC = 300  # 5 分钟内同 type+text 去重
SMALL_TRAP_CIRC_MV_MAX = 20.0  # 亿
SMALL_TRAP_TURNOVER_MIN = 20.0  # %
SEAL_AMOUNT_STRONG_YI = 5.0  # 亿


@dataclass(frozen=True)
class Snapshot:
    premarket: dict[str, Any]
    auction: dict[str, Any]
    postmarket: dict[str, Any]
    intraday: dict[str, Any]


@dataclass(frozen=True)
class RuleMsg:
    level: str  # info / warn / critical
    text: str


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 %s 失败: %s", path.name, exc)
        return {}


def _save_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------- 规则函数 ----------------

def rule_duanban_next_day(s: Snapshot) -> list[RuleMsg]:
    """铁律：昨日最高板断板 → 今日情绪 0 分，强制空仓。"""
    duanban = s.premarket.get("duanban") or []
    msgs: list[RuleMsg] = []
    for d in duanban:
        name = d.get("name") or d.get("code") or ""
        board = d.get("highest_board") or 0
        if name and board >= 5:
            msgs.append(RuleMsg(
                level="critical",
                text=f"{name} 最高板（{board}板）断板 → 铁律：今日情绪 0 分，空仓",
            ))
    return msgs


def rule_sentiment_node(s: Snapshot) -> list[RuleMsg]:
    """情绪节点在退潮/断板次日 → 空仓提示。"""
    # 情绪节点由前端 localStorage 控制，这里从 auction.market_sentiment 近似推断
    ms = s.auction.get("market_sentiment") or {}
    label = ms.get("label") or ""
    if label in {"冰点", "偏冷"}:
        return [RuleMsg(level="critical", text=f"市场情绪={label} → 接近退潮/断板次日，铁律空仓，观察不操作")]
    if label in {"偏暖", "过热"}:
        return [RuleMsg(level="info", text=f"市场情绪={label} → 可参与；优先龙一且符合三一")]
    return []


def rule_sanyi_buy_point(s: Snapshot) -> list[RuleMsg]:
    """进价三一（题材范围）+ 非小盘陷阱 → 符合三一买点。"""
    msgs: list[RuleMsg] = []
    for r in s.auction.get("recommendations") or []:
        tag = r.get("reason_tag") or ""
        small_trap = bool(r.get("small_trap"))
        circ_mv = r.get("circ_mv")
        code = r.get("code") or ""
        name = r.get("name") or ""
        concept = r.get("concept") or ""
        if not code or not name:
            continue
        if tag == "sanyi" and not small_trap and circ_mv and circ_mv >= SMALL_TRAP_CIRC_MV_MAX:
            msgs.append(RuleMsg(
                level="info",
                text=f"{code} {name} 进价三一（{concept}），流通 {circ_mv:.1f} 亿，非小盘陷阱 → 符合三一买点",
            ))
        if small_trap:
            msgs.append(RuleMsg(
                level="warn",
                text=f"{code} {name} 小盘陷阱（<20 亿 + 换手>20%），跳过",
            ))
    return msgs


def rule_theme_divergence(s: Snapshot) -> list[RuleMsg]:
    """主线题材强度骤降 → 分歧期，不接力。"""
    msgs: list[RuleMsg] = []
    themes = s.auction.get("themes_strength") or []
    for t in themes[:3]:
        name = t.get("name") or ""
        pct = t.get("avg_pct")
        if name and pct is not None and pct < -1.0:
            msgs.append(RuleMsg(
                level="warn",
                text=f"{name} 分歧期（题材均涨 {pct:+.2f}%），不接力；龙头如回封再看",
            ))
    return msgs


def rule_theme_strengthening(s: Snapshot) -> list[RuleMsg]:
    """主线题材盘中加强 → 优先龙一龙二。"""
    themes = s.auction.get("themes_strength") or []
    if not themes:
        return []
    top = themes[0]
    name = top.get("name") or ""
    pct = top.get("avg_pct") or 0
    leaders = top.get("leaders") or []
    if name and pct >= 2.0 and leaders:
        longyi = leaders[0] if len(leaders) > 0 else ""
        longer = leaders[1] if len(leaders) > 1 else ""
        return [RuleMsg(
            level="info",
            text=f"主线题材 {name} 盘中加强（均涨 {pct:+.2f}%），优先龙一 {longyi}，龙二 {longer} 备选",
        )]
    return []


def rule_three_high_opening(s: Snapshot) -> list[RuleMsg]:
    """题材开盘三高 + 梯队完整 → 龙一可考虑。"""
    msgs: list[RuleMsg] = []
    for r in s.auction.get("recommendations") or []:
        tag = r.get("reason_tag") or ""
        if tag == "yihong" or tag == "sanyi":
            code = r.get("code") or ""
            name = r.get("name") or ""
            concept = r.get("concept") or ""
            open_pct = r.get("concept_open_pct")
            limit_count = r.get("concept_limitup_count") or 0
            if open_pct and open_pct >= 2.0 and limit_count >= 2:
                msgs.append(RuleMsg(
                    level="info",
                    text=f"{concept} 开盘三高（板块高开 {open_pct:+.2f}%，板块内涨停 {limit_count}）且梯队完整 → 可考虑龙一 {code} {name}",
                ))
    return msgs


def rule_core_intersection(s: Snapshot) -> list[RuleMsg]:
    """核心股交集命中 → 盯盘重点。"""
    msgs: list[RuleMsg] = []
    for c in s.auction.get("core_intersection") or []:
        code = c.get("code") or ""
        name = c.get("name") or ""
        sector = c.get("sector") or ""
        rank = c.get("rank")
        if code and name:
            msgs.append(RuleMsg(
                level="info",
                text=f"核心股交集命中 {code} {name}，题材 {sector}，rank{rank} → 盯盘重点",
            ))
    return msgs


def rule_fengdan_strong(s: Snapshot) -> list[RuleMsg]:
    """炸板六原则：封单 >5 亿 + 被动炸板 + 回封快 → 关注做低阶。"""
    # 当前 JSON 里暂无 blast_after 字段，demo 只按封单金额粗判
    msgs: list[RuleMsg] = []
    for f in (s.auction.get("fengdan_top5") or [])[:3]:
        code = f.get("code") or ""
        name = f.get("name") or ""
        seal = f.get("seal_amount_yi") or 0
        lu = f.get("lu_desc") or ""
        if code and seal >= SEAL_AMOUNT_STRONG_YI:
            msgs.append(RuleMsg(
                level="info",
                text=f"{code} {name} 封单 {seal:.1f} 亿（原因:{lu}）→ 若后炸+被动炸板+回风快，关注做低阶",
            ))
    return msgs


def rule_index_break(s: Snapshot) -> list[RuleMsg]:
    """指数跌破关键支撑 → 减仓警示。"""
    msgs: list[RuleMsg] = []
    for idx in s.premarket.get("indices") or []:
        name = idx.get("name") or ""
        point = idx.get("point")
        support = idx.get("key_support")
        if name and point and support and point < support:
            msgs.append(RuleMsg(
                level="critical",
                text=f"{name} 跌破关键支撑 {support}（现 {point}）→ 减仓，指数维度仓位降至 ≤4 分",
            ))
    return msgs


def rule_ladder_climax(s: Snapshot) -> list[RuleMsg]:
    """涨停梯队出现 7 板及以上 → 情绪高潮提示。"""
    ladder = s.premarket.get("ladder") or {}
    high = sum(int(ladder.get(str(k), 0) or 0) for k in (7, 8, 9))
    if high >= 1:
        return [RuleMsg(level="warn", text=f"涨停梯队 ≥7 板有 {high} 只 → 情绪接近高潮，警惕分歧")]
    return []


def rule_postmarket_ratio(s: Snapshot) -> list[RuleMsg]:
    """盘后涨跌停比过低 → 明日偏弱预警。"""
    up = s.postmarket.get("limit_up_count") or 0
    dn = s.postmarket.get("limit_down_count") or 0
    if up + dn == 0:
        return []
    ratio = up / max(dn, 1)
    if ratio < 1.0 and up > 0:
        return [RuleMsg(
            level="warn",
            text=f"盘后涨跌停比 {up}:{dn} ({ratio:.2f}) → 明日情绪偏弱，次日预案保守",
        )]
    return []


def rule_low_open_double_weak(s: Snapshot) -> list[RuleMsg]:
    """持仓低开 + 龙头弱 + 风标弱 → 双弱清仓（占位，需用户侧传入 holdings）。"""
    return []


# -------- 盘中规则（读 intraday.json，腾讯行情实时数据）--------

def rule_index_live_break(s: Snapshot) -> list[RuleMsg]:
    """[盘中] 指数实时跌破关键支撑 → 立即减仓（比盘前静态规则更及时）。"""
    msgs: list[RuleMsg] = []
    for idx in s.intraday.get("indices") or []:
        if idx.get("ok") is False:  # 明确 False，None 表示无支撑数据不触发
            name = idx.get("name") or ""
            price = idx.get("price")
            support = idx.get("key_support")
            ifthen = idx.get("ifthen") or "减仓，指数维度仓位降至 ≤4 分"
            price_str = f"{price:.2f}" if price is not None else "—"
            msgs.append(RuleMsg(
                level="critical",
                text=f"[实时] {name} 跌破支撑 {support}（现 {price_str}）→ {ifthen}",
            ))
    return msgs


def rule_theme_live_diverge(s: Snapshot) -> list[RuleMsg]:
    """[盘中] 主线题材实时均涨转负 → 分歧提示，不追。"""
    msgs: list[RuleMsg] = []
    for t in (s.intraday.get("themes") or [])[:3]:
        name = t.get("name") or ""
        avg_pct = t.get("avg_pct")
        if avg_pct is not None and avg_pct < -1.0:
            msgs.append(RuleMsg(
                level="warn",
                text=f"[实时] {name} 盘中转弱（龙头均涨 {avg_pct:+.2f}%），不追；龙头回封再观察",
            ))
    return msgs


def rule_rec_live_limitup(s: Snapshot) -> list[RuleMsg]:
    """[盘中] 竞价推荐股盘中封涨停 → 提示不追高，关注炸板风险。"""
    msgs: list[RuleMsg] = []
    for r in s.intraday.get("recs_live") or []:
        pct = r.get("live_pct")
        name = r.get("name") or r.get("code") or ""
        concept = r.get("concept") or ""
        if pct is not None and pct >= 9.5:
            msgs.append(RuleMsg(
                level="warn",
                text=f"[实时] {name}（{concept}）盘中封板 {pct:+.2f}%，不追；关注炸板后低阶机会",
            ))
    return msgs


RULES: list[Callable[[Snapshot], list[RuleMsg]]] = [
    rule_duanban_next_day,
    rule_sentiment_node,
    rule_sanyi_buy_point,
    rule_theme_divergence,
    rule_theme_strengthening,
    rule_three_high_opening,
    rule_core_intersection,
    rule_fengdan_strong,
    rule_index_break,
    rule_ladder_climax,
    rule_postmarket_ratio,
    rule_low_open_double_weak,
    # 盘中实时规则（腾讯行情）
    rule_index_live_break,
    rule_theme_live_diverge,
    rule_rec_live_limitup,
]


# ---------------- 主循环 ----------------

def _load_snapshot() -> Snapshot:
    return Snapshot(
        premarket=_load_json(DATA_DIR / "premarket.json"),
        auction=_load_json(DATA_DIR / "auction.json"),
        postmarket=_load_json(DATA_DIR / "postmarket.json"),
        intraday=_load_json(DATA_DIR / "intraday.json"),
    )


def _recent_dedupe_set(messages: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """返回 5 分钟内已出现的 (type,text) 集合。"""
    cutoff = datetime.now() - timedelta(seconds=DEDUPE_WINDOW_SEC)
    seen: set[tuple[str, str]] = set()
    for m in messages:
        if m.get("type") == "user":
            continue
        ts_str = m.get("ts") or ""
        try:
            ts = datetime.fromisoformat(ts_str)
            # 统一去掉时区信息，以便与 naive datetime.now() 比较
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except (ValueError, AttributeError):
            continue
        if ts >= cutoff:
            seen.add((m.get("type", ""), m.get("text", "")))
    return seen


def run_once() -> int:
    """执行一轮规则引擎，返回本轮新增消息数。"""
    snap = _load_snapshot()
    advisor_path = DATA_DIR / "advisor.json"
    current = _load_json(advisor_path)
    messages: list[dict[str, Any]] = current.get("messages") or []

    seen = _recent_dedupe_set(messages)
    new_count = 0
    for rule in RULES:
        try:
            rule_msgs = rule(snap)
        except Exception as exc:  # 单条规则失败不影响其他
            logger.exception("规则 %s 执行异常: %s", rule.__name__, exc)
            continue
        for m in rule_msgs:
            key = ("rule", m.text)
            if key in seen:
                continue
            seen.add(key)
            messages.insert(0, {
                "ts": _now_iso(),
                "type": "rule",
                "level": m.level,
                "text": m.text,
            })
            new_count += 1

    messages = messages[:MAX_MESSAGES]
    payload = {"updated_at": _now_iso(), "messages": messages}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _save_json_atomic(advisor_path, payload)
    logger.info("规则引擎完成 · 本轮新增 %d 条 · 总 %d 条", new_count, len(messages))
    return new_count


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="盯盘规则引擎")
    parser.add_argument("--once", action="store_true", help="只跑一次后退出")
    parser.add_argument("--interval", type=int, default=60, help="循环间隔秒（默认 60）")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(DEFAULT_DATA_DIR),
        help=f"数据目录（默认 {DEFAULT_DATA_DIR}）",
    )
    parser.add_argument(
        "--with-feeder",
        action="store_true",
        help="同时在后台启动 feeder.py（tushare 模式；若需 mock 请先单独运行 feeder.py --mock）",
    )
    parser.add_argument(
        "--with-feeder-mock",
        action="store_true",
        help="同时在后台启动 feeder.py --mock（无需 tushare，用于测试 Tab 展示）",
    )
    return parser


def _start_feeder(mock: bool = False) -> Optional[subprocess.Popen]:
    """后台启动同目录的 feeder.py，返回进程句柄，失败时返回 None。"""
    feeder_path = BASE_DIR / "feeder.py"
    if not feeder_path.exists():
        logger.warning("feeder.py 不存在于 %s，跳过启动", BASE_DIR)
        return None
    cmd = [sys.executable, str(feeder_path)]
    if mock:
        cmd.append("--mock")
    try:
        proc = subprocess.Popen(cmd, cwd=str(BASE_DIR))
        label = "mock" if mock else "tushare"
        logger.info("feeder.py 已在后台启动（%s 模式），PID=%d", label, proc.pid)
        return proc
    except Exception as exc:
        logger.warning("启动 feeder.py 失败: %s", exc)
        return None


def main() -> None:
    global DATA_DIR
    args = _build_arg_parser().parse_args()
    DATA_DIR = Path(args.data_dir).resolve()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 启动时钟（合并入 盘中监控脚本 Node 站，Node 侧会读同一 data_dir）
    print(f"[advisor] 启动时钟 = {datetime.now().isoformat(timespec='seconds')} · data_dir = {DATA_DIR}")

    feeder_proc: Optional[subprocess.Popen] = None
    if args.with_feeder_mock:
        feeder_proc = _start_feeder(mock=True)
    elif args.with_feeder:
        feeder_proc = _start_feeder(mock=False)

    try:
        if args.once:
            run_once()
            return
        logger.info("advisor 启动 · 间隔 %ss · 数据目录 %s", args.interval, DATA_DIR)
        while True:
            try:
                run_once()
            except Exception as exc:
                logger.exception("主循环异常: %s", exc)
            time.sleep(args.interval)
    finally:
        if feeder_proc is not None:
            feeder_proc.terminate()
            logger.info("feeder.py 已终止（PID=%d）", feeder_proc.pid)


if __name__ == "__main__":
    main()
