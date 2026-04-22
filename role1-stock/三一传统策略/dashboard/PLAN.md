# 三一传统策略 · 本地盯盘看板 PLAN.md

> 目标：在 `三一传统策略/dashboard/` 下构建一个**本地纯离线**看板，覆盖「盘前 → 竞价 → 盘中 → 盘后」四段，承接既有 5 个 Python 脚本的产出，按交易员的四维打分 + 开盘八法 + 情绪节点体系组织信息流。研究参考，不构成投资建议。

---

## 1. 整体架构（文字版）

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        数据生产层（已有 Python 脚本）                       │
│   竞价三一_断板弱转强.py   一红+爆量.py   9431.py   单核带队.py   梯队复盘.py   │
│              │                 │            │           │             │     │
│     （现有产出：TXT 报告 + PushPlus 微信推送，保持不改）                   │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│             数据适配层（dashboard/parsers/ + advisor.py）                   │
│   - parsers/*.py ：把各脚本 TXT 产出解析成 dashboard/data/*.json            │
│   - advisor.py   ：读 auction/premarket/postmarket.json → 规则引擎 →       │
│                    追加短句到 advisor.json（每 60s 或 --once）              │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                     dashboard/data/*.json
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    服务层（server.py Flask 最小后端）                        │
│   GET /           → 返回 index.html                                        │
│   GET /data       → 聚合 data/*.json，统一返回                              │
│   POST /append-note → advisor.json 头插用户手动备注                         │
│   GET /health     → 健康检查                                                │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
                         fetch / POST
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     展示层（index.html + tailwindcdn + 原生 JS）            │
│   Header（四维打分 + 情绪节点）                                              │
│   ├─ 盘前区（左）：7 卡片                                                    │
│   ├─ 盘中区（中）：盯盘操作指引（最新置顶，≤20 条，含手动备注输入）            │
│   └─ 盘后区（右）：3 卡片                                                    │
│   轮询策略：按当前时间窗自动切换 10s / 20s / 60s / 300s                      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 数据来源清单

| 字段 | 来源脚本 / 适配器 | 刷新频率 | 是否依赖实时行情 |
|------|--------------------|---------|-------------------|
| 指数关键位 + IF-THEN | 手工维护 `data/premarket.json` 或未来 `parsers/index_levels.py` | 盘前一次 | 否（需前一日收盘） |
| 隔夜外盘（中国金龙/KWEB 等） | 手工/未来 `parsers/overseas.py`（外部接口） | 盘前一次 | 是（外盘收盘价） |
| 情绪风标候选 | `一红+爆量.py` → `parsers/yihong.py` | 盘前一次 | 否 |
| 主线/支线题材 | `9431.py` → `parsers/jiuslsanyi.py` | 竞价 10-20s 轮询 | 是 |
| 题材强度（涨幅排行） | `竞价三一_断板弱转强.py` →【题材情绪】段 | 竞价 10-20s | 是 |
| 涨停梯队分布 | `梯队复盘.py` / 昨日收盘数据 | 盘前一次 / 盘后刷新 | 否 |
| 断板统计 | `梯队复盘.py` / `竞价三一_断板弱转强.py` | 盘前一次 | 否 |
| 竞价三一汇总（推荐票） | `竞价三一_断板弱转强.py` →【今日推荐】段 | 竞价 10-20s | 是 |
| 核心股交集 | `竞价三一_断板弱转强.py` →【核心股交集】段 | 竞价 10-20s | 是 |
| 封单前五 + 概念关联 | `单核带队.py` | 竞价 10-20s | 是（Selenium） |
| 盘中盯盘指引 | `advisor.py` 规则引擎 + 用户手动备注 | 60s | 依赖快照 JSON |
| 盘后涨跌停比 | `梯队复盘.py` | 5 分钟 | 否 |
| 龙虎榜要点 | 未来 `parsers/lhb.py`（盘后接口） | 盘后一次 | 否 |
| 模式命中率 | 未来 `parsers/pattern_hit.py`（复盘时人工或半自动） | 盘后一次 | 否 |
| 次日预案占位 | 用户手写 | 盘后 | 否 |

---

## 3. 页面分区

### 3.1 顶部 Header
- 左：今日日期（YYYY-MM-DD，中文星期）
- 中：**四维打分输入**——4 个数字 input（指数/情绪/题材/个股，范围按 4/3/2/1）+ 自动累加显示 `总分 X/10`
- 右：当前**情绪节点**下拉（启动 3 / 上升 2 / 高潮 1 / 分歧 1 / 退潮 0 / 断板次日 0）
- 四维打分与情绪节点均 **localStorage 持久化**，刷新不丢失

### 3.2 左侧盘前区（7 卡片）
1. **指数关键位 · IF-THEN** —— 上证/创业板/科创 前一日收盘 + 关键支撑压力 + IF-THEN 短句（跌破 X → 减仓；站上 Y → 加仓）
2. **隔夜外盘** —— KWEB、中国金龙 ETF、纳指期货等，涨跌幅展示
3. **情绪风标候选** —— 来自"一红+爆量"的多头/空头风标候选（代码 · 名称 · 前日涨幅）
4. **主线/支线题材** —— 主线题材、支线题材（最多各 5 个，带强度百分比）
5. **涨停梯队分布** —— 9 板 / 8 板 / ... / 1 板 各多少只（柱状/数字）
6. **断板统计** —— 昨日断板数 + 断板龙头列表（铁律：断板次日 = 情绪 0 分）
7. **竞价汇总（占位，9:15 起实时刷新）** —— 竞价三一 + 核心股交集 + 封单前五

### 3.3 中间盘中区 · **盯盘操作指引**（核心）
- 卡片化列表，最新消息**置顶**，最多保留 20 条
- 每条含：时间戳 · 类型标签（规则 / 备注 / 警示） · 等级（info / warn / critical）· 正文
- 底部有 `<textarea>` + 「追加备注」按钮 → POST `/append-note`
- 规则引擎由 `advisor.py` 每 60s 执行，输出见 §4

### 3.4 右侧盘后区（3 卡片）
1. **涨跌停比** —— 涨停数 / 跌停数 / 比值 / 炸板数
2. **龙虎榜要点** —— 顶级游资席位、机构席位、关键票
3. **模式命中率 + 次日预案** —— 今日触发的模式（三一 / 弱转强 / 一红定江山 …）是否兑现 + 明日盯盘重点列表（用户手填）

### 3.5 页脚
固定红色小字：**"研究参考，不构成投资建议"**

---

## 4. 「盯盘操作指引」规则模板（≥12 条）

`advisor.py` 规则引擎输出，与用户手动备注合并写入 `advisor.json.messages[]`。

| # | 触发条件（伪码） | 输出短句模板 | 等级 |
|---|-----------------|-------------|------|
| 1 | `theme.open_three_high && theme.ladder_complete` | 「`<题材>` 开盘三高且梯队完整 → 可考虑龙一 `<code/name>`」 | info |
| 2 | `theme.top_broken_yesterday` | 「`<题材>` 最高板断板 → 铁律：今日情绪 0 分，空仓」 | critical |
| 3 | `theme.stage == '分歧'` | 「`<题材>` 分歧期，不接力；龙头如回封再看」 | warn |
| 4 | `stock in auction_sanyi && circ_mv >= 20 && !small_trap` | 「`<code>` 进价三一（题材范围），流通 `<X>` 亿，非小盘陷阱 → 符合三一买点」 | info |
| 5 | `stock.circ_mv < 20 && stock.turnover > 20` | 「`<code>` 小盘陷阱（<20 亿 + 换手>20%），跳过」 | warn |
| 6 | `stock.blast_after && seal_amount > 5e8 && passive_blast && quick_recovery` | 「炸板 `<code>` 后炸 + 封单 >5 亿 + 被动炸板 + 回风快 → 关注做低阶」 | info |
| 7 | `index.break_key_support` | 「指数跌破 `<关键位>` → 减仓，仓位降至 ≤4 分（指数位）」 | critical |
| 8 | `sentiment.node in ['启动','上升']` | 「情绪节点 = `<节点>`，可参与；优先龙一且符合三一」 | info |
| 9 | `sentiment.node in ['退潮','断板次日']` | 「情绪节点 = `<节点>` → 铁律空仓，观察不操作」 | critical |
| 10 | `core_stock.hit_in_intersection` | 「核心股交集命中 `<code>`，题材 `<sector>`，rank `<r>` → 盯盘重点」 | info |
| 11 | `theme.strength_top1 && theme.volume_amplified` | 「主线题材 `<题材>` 盘中加强，优先龙一 `<X>`，龙二 `<Y>` 备选」 | info |
| 12 | `stock.opened_low && leader_weak && sentinel_weak` | 「持仓低开 + 龙头弱 + 风标弱 → 双弱清仓」 | critical |
| 13 | `time == '14:30' && 指数跌幅 > 1%` | 「尾盘 14:30 后指数弱 → 不追尾盘板，次日预案准备」 | warn |
| 14 | 手动 | 用户 textarea 原文 | user |

**合并策略**：新消息头插，截断到 20 条；同 `type` + `text` 在 5 分钟内的重复消息去重。

---

## 5. 数据刷新频率（前端 `setInterval` 按时段切换）

| 时间窗 | 轮询周期 | 说明 |
|--------|---------|------|
| 08:30 – 09:15 | 一次性拉取（60s 兜底） | 盘前静态数据 |
| 09:15 – 09:30 | **10–20s** | 竞价，JSON 密集刷新 |
| 09:30 – 11:30 / 13:00 – 15:00 | **60s** | 盘中 + 盯盘指引 |
| 15:00 – 16:30 | **5 分钟** | 盘后总结 |
| 其他 | 不轮询（只首加载） | 仅展示最后状态 |

前端用 `getCurrentPeriod()` 判定时段切换周期。

---

## 6. 技术选型决策

### 6.1 采用方案：**静态 HTML + Flask 最小后端**
- **理由一句话**：用户是单机交易员、无部署需求，静态 HTML 保证断网也能看；Flask 两个接口即可解决「前端写回备注」的痛点，比纯静态 + 手动编辑 JSON 友好得多。
- 前端：CDN 版 Tailwind + 原生 `fetch` + `setInterval`，零构建工具。
- 后端：Flask（唯一依赖），≤150 行。
- 数据：文件系统 JSON，脚本/人工都可直接写入。

### 6.2 备选方案对比

| 方案 | 优点 | 缺点 | 是否采用 |
|------|------|------|---------|
| 纯静态轮询 JSON（无后端） | 双击打开、零依赖 | 不能前端追加备注、CORS 可能限制 file:// | ❌（功能残缺）|
| **静态 HTML + Flask** | 零构建、备注可写回、易扩展 | 需启动 Python 进程 | ✅ |
| Vite + React + tRPC | 类型安全、组件化 | 对单用户过重、编译链复杂 | ❌（YAGNI）|
| Next.js | 生态成熟 | 同上，且 SSR 无必要 | ❌ |

### 6.3 无后端降级
HTML 直接双击打开时，`fetch('/data')` 失败 → 显示「等待数据…」；手动备注按钮 disabled + tooltip「请启动 server.py」。

---

## 7. 与既有 Python 输出对接

每个脚本的 TXT 产出目前直接给 PushPlus。为了 dashboard，新增 `dashboard/parsers/*.py` 解析器（本次只给伪码骨架，**不改原 5 个 .py**）。

### 7.1 `parsers/jingjia_sanyi.py` — 竞价三一_断板弱转强
```python
def parse_jingjia_sanyi(txt_path: Path) -> dict:
    """
    解析【题材情绪】【市场情绪】【核心股交集】【今日推荐】四段
    → 写入 data/auction.json
    """
    lines = txt_path.read_text(encoding='utf-8').splitlines()
    out = {
        'themes_strength': [],      # [{name, avg_pct}]
        'market_sentiment': {...},  # {score, label}
        'core_intersection': [],    # [{name, sector, pct_chg, rank}]
        'recommendations': [],      # [{code, name, pct, rank, circ_mv, reason, ...}]
        'updated_at': now_iso(),
    }
    # 逐行正则匹配「【题材情绪】」「【市场情绪】」「【核心股交集】」「【今日推荐】」
    # 解析每条推荐的：所属概念 / 板块今日高开 / 板块内涨停 / 流通市值 / rank / 原因
    return out
```

### 7.2 `parsers/yihong.py` — 一红+爆量
```python
def parse_yihong(txt_path: Path) -> dict:
    """解析连板爆量+高开 / 一红定江山 / 大盘爆量高开 → data/premarket.json.sentinels"""
    ...
```

### 7.3 `parsers/nine431.py` — 9431
```python
def parse_9431(txt_path: Path) -> dict:
    """高开板块前三 + 每板块竞价金额/换手/人气前三 → premarket.json.themes + auction.json"""
    ...
```

### 7.4 `parsers/danhedaidui.py` — 单核带队
```python
def parse_danhedaidui(txt_path: Path) -> dict:
    """封单前五 + 涨停原因 + 概念下竞价金额/换手前三 → auction.json.recommendations 的补强"""
    ...
```

### 7.5 `parsers/tidui_fupan.py` — 梯队复盘
```python
def parse_tidui_fupan(txt_path: Path, xlsx_path: Path) -> dict:
    """涨停梯队、断板、涨跌停比 → premarket.json.ladder + postmarket.json"""
    ...
```

### 7.6 未来优化（任务 A 联动）
在 `refactored/` 重构版本里直接让每个策略写 `dashboard/data/*.json`，省去 TXT → JSON 转换。当前 PLAN 不强制。

### 7.7 统一调度
推荐加一行到既有 scheduler（如果有）或用户手动编排：
```bash
python 竞价三一_断板弱转强.py --output-file latest_sanyi.txt && \
python dashboard/parsers/jingjia_sanyi.py latest_sanyi.txt dashboard/data/auction.json
```

---

## 8. 分期交付计划

### P0（本次交付 · 最关键）
- [x] `dashboard/PLAN.md`（本文件）
- [x] `dashboard/index.html` 骨架（含盘中盯盘指引区 + 手动备注）
- [x] `dashboard/server.py` Flask 最小后端
- [x] `dashboard/advisor.py` 规则引擎骨架（12+ 条规则）
- [x] `dashboard/data/auction.json` + `advisor.json` + schema 说明
- [x] `dashboard/README.md` 启动说明

### P1（下一迭代）
- [ ] `parsers/jingjia_sanyi.py` / `yihong.py` / `nine431.py` / `danhedaidui.py` / `tidui_fupan.py` 真实实现
- [ ] `dashboard/data/premarket.json` + `postmarket.json` 真实数据接入
- [ ] 盘前/盘后卡片 UI 精修
- [ ] 轮询周期按时段切换的完整实现（当前为 60s 统一轮询）

### P2（进阶）
- [ ] 龙虎榜 `parsers/lhb.py`（盘后接口）
- [ ] 模式命中率半自动复盘（匹配 `05_操作模式.md` 的 12 种模式）
- [ ] `refactored/` 版本脚本直接写 JSON，废弃 TXT 解析
- [ ] 可选 WebSocket 推送代替轮询
- [ ] 历史 advisor 消息归档 `data/history/YYYY-MM-DD.json`

---

## 9. 研究参考声明

本看板**仅用于本人交易研究和盘中辅助决策**，不构成投资建议。所有数据源脚本均为第三方数据重组，存在延迟和错误可能。交易决策以个人独立判断为准。
