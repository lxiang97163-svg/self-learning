"""
collect_strategies.py
========================================================
同花顺策略广场 策略问句 + 收益率 采集脚本（备用方案 3）
Target: https://backtest.10jqka.com.cn/backtest/app.html#/strategysquare

使用条件：
    pip install playwright==1.47.0
    playwright install chromium

输出：
    strategies_raw.json  —— 包含每条策略的 {title, question, tags, author, popularity,
                              yield_30d, yield_180d, yield_1y, win_rate, max_drawdown}
    yields.json          —— 仅导出收益率相关字段的扁平 JSON（便于后续 join）

使用限制：
    - 仅用于个人研究与学习
    - 遵守目标站 robots.txt 与 ToS
    - 严禁商用 / 高频批量
    - 请求间隔 ≥2s（抓收益率动作通常需要悬停/展开，比单纯列表更重）
    - 总请求量 ≤30
    - 不构成任何投资建议
    - 所有收益率均为**历史回测数据**，不等于实盘收益；历史不代表未来

用法：
    python collect_strategies.py              # 默认最多抓 5 页
    python collect_strategies.py --pages 3    # 指定翻页数上限（≤10）
    python collect_strategies.py --pages 5 --output-dir /path/to/dir  # 指定输出目录
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import (  # type: ignore
        Page,
        TimeoutError as PwTimeout,
        sync_playwright,
    )
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "[ERROR] 未安装 playwright。请先运行：\n"
        "    pip install playwright==1.47.0\n"
        "    playwright install chromium\n"
    )
    sys.exit(1)


TARGET_URL = "https://backtest.10jqka.com.cn/backtest/app.html#/strategysquare"
_SCRIPT_DIR = Path(__file__).parent

# throttle: 每次动作至少停 2s（抓收益率比纯列表更重，多留余量）
MIN_INTERVAL_SEC = 2.0
MAX_PAGES_HARD_CAP = 10

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("collect_strategies")


# ---------- 数据结构 ----------
@dataclass(frozen=True)
class StrategyCard:
    """策略广场单卡数据（不可变）。"""

    title: str
    question: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    author: str | None = None
    popularity: str | None = None
    yield_30d: float | None = None
    yield_180d: float | None = None
    yield_1y: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    source: str = "页面抓取"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tags"] = list(self.tags)
        return d


# ---------- 工具函数 ----------
def polite_sleep(base: float = MIN_INTERVAL_SEC) -> None:
    """礼貌间隔，加入 0~0.6s 随机抖动。"""
    jitter = random.uniform(0.0, 0.6)
    time.sleep(base + jitter)


# 百分比 / 带小数点的数字（可带正负号）
_PCT_PATTERN = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%")


def _parse_pct(text: str) -> float | None:
    """从字符串里抽第一个百分比值，返回 float（例 '12.3%' -> 12.3）。"""
    if not text:
        return None
    match = _PCT_PATTERN.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_field_by_label(
    text: str, labels: tuple[str, ...]
) -> float | None:
    """
    在 `text` 中按「标签 + 数字%」的启发式找第一个命中的字段。
    例如 labels=('近30日收益率', '30日收益') -> 在文本里找 '近30日收益率 12.3%' 的片段。
    """
    if not text:
        return None
    for label in labels:
        # 允许 label 与数字之间出现：空格 / 冒号 / 中英文标点 / 换行
        pattern = re.compile(
            re.escape(label) + r"[\s:：]*([-+]?\d+(?:\.\d+)?)\s*%"
        )
        m = pattern.search(text)
        if m:
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                continue
    return None


def extract_cards_from_dom(page: Page) -> list[dict[str, Any]]:
    """
    从当前已渲染的 DOM 中抽取策略卡片。
    注意：同花顺页面会随版本调整 class name，这里用较宽松的选择器 + 文本启发式。
    如果页面结构变化，改这个函数即可。

    抓取策略：
      1. 用多组候选选择器捞所有像"策略卡片"的块
      2. 对每个块：首行 = title、最长行 = question
      3. 子元素 class 含 tag/label/badge 的 = tags
      4. 内文用正则匹配「收益率」「胜率」「回撤」等字段
    """
    js = r"""
    () => {
      const results = [];
      const candidates = Array.from(
        document.querySelectorAll(
          '[class*="strategy"], [class*="card"], [class*="item"], [class*="question"], [class*="strat"]'
        )
      );
      const seen = new Set();
      for (const el of candidates) {
        const text = (el.innerText || '').trim();
        if (!text || text.length < 6 || text.length > 1200) continue;
        if (seen.has(text)) continue;
        seen.add(text);

        const lines = text
          .split(/\n+/)
          .map((s) => s.trim())
          .filter(Boolean);
        if (!lines.length) continue;

        const title = lines[0].slice(0, 80);
        const question =
          [...lines].sort((a, b) => b.length - a.length)[0].slice(0, 400);

        const tagEls = el.querySelectorAll(
          '[class*="tag"], [class*="label"], [class*="badge"]'
        );
        const tags = Array.from(tagEls)
          .map((t) => (t.innerText || '').trim())
          .filter((s) => s && s.length <= 20);

        // 作者、热度（弱信号）
        const authorEl = el.querySelector(
          '[class*="author"], [class*="user"], [class*="nickname"]'
        );
        const popEl = el.querySelector(
          '[class*="popular"], [class*="hot"], [class*="count"], [class*="follow"]'
        );

        results.push({
          title,
          question,
          tags,
          author: authorEl ? (authorEl.innerText || '').trim() : null,
          popularity: popEl ? (popEl.innerText || '').trim() : null,
          fullText: text,  // 保留给 Python 侧做收益率字段正则
        });
      }
      return results;
    }
    """
    try:
        return page.evaluate(js) or []
    except Exception as exc:  # pragma: no cover
        logger.warning("evaluate 抽取失败: %s", exc)
        return []


def enrich_with_yields(cards: list[dict[str, Any]]) -> list[StrategyCard]:
    """
    对 extract_cards_from_dom 产出的 raw card 做收益率字段抽取。
    `fullText` 是卡片完整可见文本，我们用多组标签启发式匹配。
    """
    yield_30d_labels = (
        "近30日收益率",
        "近30天收益率",
        "近30日",
        "30日收益",
        "30天收益率",
        "月收益率",
    )
    yield_180d_labels = (
        "近180日收益率",
        "近半年收益率",
        "近180天收益率",
        "180日收益",
        "半年收益率",
    )
    yield_1y_labels = (
        "近1年收益率",
        "近一年收益率",
        "近12个月收益率",
        "年化收益率",
        "1年收益",
    )
    win_rate_labels = ("胜率", "策略胜率", "成功率")
    max_drawdown_labels = ("最大回撤", "回撤", "最大回撤率")

    out: list[StrategyCard] = []
    for c in cards:
        full_text: str = c.get("fullText") or ""
        card = StrategyCard(
            title=str(c.get("title") or "")[:80],
            question=str(c.get("question") or "")[:400],
            tags=tuple(c.get("tags") or []),
            author=c.get("author"),
            popularity=c.get("popularity"),
            yield_30d=_extract_field_by_label(full_text, yield_30d_labels),
            yield_180d=_extract_field_by_label(full_text, yield_180d_labels),
            yield_1y=_extract_field_by_label(full_text, yield_1y_labels),
            win_rate=_extract_field_by_label(full_text, win_rate_labels),
            max_drawdown=_extract_field_by_label(full_text, max_drawdown_labels),
            source="页面抓取",
        )
        out.append(card)
    return out


def try_click_next(page: Page) -> bool:
    """尝试点击下一页按钮，返回是否成功翻页。"""
    selectors = (
        'button:has-text("下一页")',
        'a:has-text("下一页")',
        '[class*="next"]:not([disabled])',
        ".pagination-next:not(.disabled)",
    )
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn and btn.is_visible(timeout=800):
                btn.click(timeout=1500)
                return True
        except PwTimeout:
            continue
        except Exception:
            continue
    return False


def dedupe(items: list[StrategyCard]) -> list[StrategyCard]:
    seen: set[tuple[str, str]] = set()
    out: list[StrategyCard] = []
    for it in items:
        key = (it.title, it.question)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# ---------- 主流程 ----------
def collect(pages_limit: int) -> list[StrategyCard]:
    pages_limit = min(max(1, pages_limit), MAX_PAGES_HARD_CAP)
    collected: list[StrategyCard] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30_000)
        except PwTimeout:
            logger.error("页面加载超时")
            browser.close()
            return []

        # 等 SPA 渲染
        polite_sleep(2.0)
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except PwTimeout:
            pass

        for page_idx in range(pages_limit):
            polite_sleep()
            raw_cards = extract_cards_from_dom(page)
            enriched = enrich_with_yields(raw_cards)
            logger.info(
                "page %d/%d -> %d items (with yields: %d)",
                page_idx + 1,
                pages_limit,
                len(enriched),
                sum(
                    1
                    for c in enriched
                    if c.yield_30d is not None or c.yield_1y is not None
                ),
            )
            collected.extend(enriched)

            if page_idx == pages_limit - 1:
                break
            if not try_click_next(page):
                logger.info("未找到下一页按钮，结束")
                break
            polite_sleep()
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except PwTimeout:
                pass

        browser.close()

    return dedupe(collected)


def dump_yields(cards: list[StrategyCard]) -> list[dict[str, Any]]:
    """只抽收益率相关字段，便于后续与 strategies_filtered.md 做 join。"""
    return [
        {
            "title": c.title,
            "question": c.question,
            "yield_30d": c.yield_30d,
            "yield_180d": c.yield_180d,
            "yield_1y": c.yield_1y,
            "win_rate": c.win_rate,
            "max_drawdown": c.max_drawdown,
            "source": c.source,
            "disclaimer": "历史回测收益率，不等于实盘，历史不代表未来",
        }
        for c in cards
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="同花顺策略广场问句 + 收益率采集（仅个人研究使用）"
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help=f"最多翻页数（上限 {MAX_PAGES_HARD_CAP}，默认 5）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="输出目录路径（默认与脚本同目录）",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else _SCRIPT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    output_raw = output_dir / "strategies_raw.json"
    output_yields = output_dir / "yields.json"

    items = collect(args.pages)

    _disclaimer = (
        "所有收益率为策略广场历史回测数据，不等于实盘收益；"
        "历史回测不代表未来表现；"
        "本数据仅供个人研究，不构成投资建议。"
    )

    raw_payload = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": TARGET_URL,
        "disclaimer": _disclaimer,
        "items": [c.to_dict() for c in items],
    }
    output_raw.write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    yields_payload = {
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": TARGET_URL,
        "disclaimer": _disclaimer,
        "items": dump_yields(items),
    }
    output_yields.write_text(
        json.dumps(yields_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 每10条打印一次进度（对大批量运行友好）
    for i, card in enumerate(items, start=1):
        if i % 10 == 0 or i == len(items):
            print(
                f"[进度] 已处理 {i}/{len(items)} 条"
                f"（30日收益有值：{sum(1 for c in items[:i] if c.yield_30d is not None)} 条）"
            )

    logger.info(
        "采集 %d 条 -> %s（同时导出 yields -> %s）",
        len(items),
        output_raw,
        output_yields,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
