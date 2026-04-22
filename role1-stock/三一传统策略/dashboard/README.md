# 三一传统策略 · 本地盯盘看板

> 本地离线看板，覆盖「盘前 → 竞价 → 盘中 → 盘后」四段。承接 `三一传统策略/` 下 5 个既有脚本的产出，按四维打分 + 开盘八法 + 情绪节点体系组织。
>
> **研究参考，不构成投资建议。**

---

## 目录结构

```
dashboard/
├── PLAN.md              # 主交付文档（架构 / 数据来源 / 规则 / 分期）
├── README.md            # 本文件：启动与扩展说明
├── index.html           # 前端骨架（tailwindcdn + 原生 fetch）
├── server.py            # Flask 最小后端（/ /data /append-note /health）
├── advisor.py           # 盯盘规则引擎（12+ 条规则）
└── data/                # JSON 数据文件 + schema 说明
    ├── premarket.json         premarket.schema.md
    ├── auction.json           auction.schema.md
    ├── advisor.json           advisor.schema.md
    └── postmarket.json        postmarket.schema.md
```

未来扩展：`dashboard/parsers/`（把既有脚本的 TXT 产出解析成 JSON）。

---

## 完整启动（含真实数据）

### 最快上手：mock 模式（无需 tushare，立即可用）

```bash
# 终端 1：启动 Node 服务
cd 盘中监控脚本 && node server.js

# 终端 2：写入 mock 数据，然后启动规则引擎（含 feeder 后台）
cd 三一传统策略/dashboard
python feeder.py --mock --once    # 先写一次 mock 数据
python advisor.py --with-feeder-mock   # 启动规则引擎 + 后台 mock feeder
```

浏览器访问 <http://localhost:3000>（或 Node 服务实际端口）的「三一盘前盘中盘后」Tab，
即可看到有意义的示例数据和 advisor 操作指导。

### 一次性验证 Tab 展示

```bash
# 写入 mock 数据
python 三一传统策略/dashboard/feeder.py --mock --once
# 运行一次规则引擎
python 三一传统策略/dashboard/advisor.py --once
# 查看生成的操作指导
cat 三一传统策略/dashboard/data/advisor.json
```

### 完整真实数据流（需要 tushare token）

```bash
# 终端 1：启动 Node 服务
cd 盘中监控脚本 && node server.js

# 终端 2：启动规则引擎（自动在后台启动 tushare feeder）
cd 三一传统策略/dashboard && python advisor.py --with-feeder

# 或分开启动：
# 终端 2：feeder（每 60s 刷新，竞价时段 30s）
python 三一传统策略/dashboard/feeder.py
# 终端 3：规则引擎
python 三一传统策略/dashboard/advisor.py
```

tushare 配置见 `三一传统策略/refactored/config.example.json`，
实际配置写入 `三一传统策略/refactored/config.local.json`（不提交）。

---

## 启动顺序

### 1. 安装依赖

```bash
pip install flask
```

（`advisor.py` 只用标准库，不需额外依赖。）

### 2. 确保现有脚本产出数据

现有 5 个策略脚本保持不变，正常运行即可；未来的 `parsers/*.py` 会把 TXT 报告解析成 `dashboard/data/*.json`。当前 P0 阶段 JSON 均为占位骨架，可以手动编辑验证前端渲染。

典型调度（示例，用户自行串联）：

```bash
# 盘前 08:30
python 一红+爆量.py --output-file reports/yihong.txt
python dashboard/parsers/yihong.py reports/yihong.txt dashboard/data/premarket.json  # P1

# 竞价 09:15 - 09:30（每 10-20s）
python 竞价三一_断板弱转强.py --output-file reports/sanyi.txt
python 9431.py               --output-file reports/9431.txt
python 单核带队.py            --output-file reports/danhe.txt
python dashboard/parsers/jingjia_sanyi.py  reports/sanyi.txt dashboard/data/auction.json
python dashboard/parsers/nine431.py        reports/9431.txt  dashboard/data/auction.json
python dashboard/parsers/danhedaidui.py    reports/danhe.txt dashboard/data/auction.json

# 盘后 15:05
python 梯队复盘.py --output-file reports/tidui.txt
python dashboard/parsers/tidui_fupan.py reports/tidui.txt dashboard/data/postmarket.json
```

### 3. 启动规则引擎（推荐后台常驻）

```bash
python dashboard/advisor.py               # 每 60s 执行一次
python dashboard/advisor.py --once        # 只跑一次
python dashboard/advisor.py --interval 30 # 自定义间隔
```

### 4. 启动看板服务

```bash
python dashboard/server.py                # 默认 5178
python dashboard/server.py --port 8080    # 自定端口
```

浏览器访问：<http://localhost:5178>

### 5. 离线打开（降级模式）

不启动 `server.py` 时，也可直接 **双击 `index.html`** 打开。此时：
- 所有卡片显示「等待数据…」或上一次成功的数据
- 「追加备注」按钮被禁用（`fetch /data` 失败即 disabled）
- 四维打分和情绪节点仍然可用（走 localStorage）

---

## 前端功能

### 顶部 Header
- **今日日期**：自动渲染
- **四维打分** 4 个输入（指数 0-4 / 情绪 0-3 / 题材 0-2 / 个股 0-1）
  - 自动求和为 `总分 X/10`
  - `localStorage` 持久化，刷新不丢
  - 总分颜色：≥6 绿色 / ≤4 红色 / 其他黄色
- **情绪节点** 下拉（启动/上升/高潮/分歧/退潮/断板次日）

### 三列布局
- **左侧 盘前区（7 卡片）**：指数关键位、隔夜外盘、情绪风标候选、主线/支线题材、涨停梯队、断板统计、竞价汇总
- **中间 盯盘操作指引**：规则引擎 + 手动备注合并列表（最新置顶，≤20 条），带 textarea 追加按钮
- **右侧 盘后区（3 卡片）**：涨跌停比、龙虎榜要点、模式命中率 + 次日预案

### 轮询策略
前端 `getRefreshIntervalMs()` 按当前时间窗自动切换：
| 时间窗 | 间隔 |
|--------|------|
| 08:30 – 09:15 | 60s |
| 09:15 – 09:30 | **15s**（竞价） |
| 09:30 – 15:00 | 60s |
| 15:00 – 16:30 | 5 分钟 |
| 其他 | 2 分钟 |

### 底部固定
红色小字：**「研究参考，不构成投资建议」**

---

## 如何扩展新的规则到 `advisor.py`

每条规则是一个函数：

```python
def rule_your_new_rule(s: Snapshot) -> list[RuleMsg]:
    """触发条件说明。"""
    msgs = []
    if <从 s.premarket / s.auction / s.postmarket 取出的条件成立>:
        msgs.append(RuleMsg(
            level="info",          # info / warn / critical
            text=f"{<变量>} 满足某条件 → 建议 <动作>",
        ))
    return msgs
```

然后加入 `RULES: list[Callable[[Snapshot], list[RuleMsg]]]` 列表即可。

规则引擎自动处理：
- 同 `type+text` 5 分钟内去重
- 头插 + 截断到 20 条
- 原子写入 `data/advisor.json`

### 已内置的 12 条（见 `advisor.py`）

1. 断板次日铁律（critical）
2. 市场情绪节点（info / critical）
3. 进价三一买点（info）
4. 小盘陷阱跳过（warn）
5. 主线题材分歧期（warn）
6. 主线题材盘中加强（info）
7. 开盘三高 + 梯队完整（info）
8. 核心股交集命中（info）
9. 封单强 + 炸板六原则关注（info）
10. 指数跌破关键支撑（critical）
11. 涨停梯队接近高潮（warn）
12. 盘后涨跌停比偏弱（warn）

---

## 与既有脚本的对接（P1 重点）

既有 5 个脚本**保持不改**，通过「TXT 报告 → parser → JSON」的单向适配：

| 脚本 | TXT 产出关键段 | 解析器（待实现） | 目标 JSON |
|------|---------------|-------------------|-----------|
| 竞价三一_断板弱转强.py | 【题材情绪】【市场情绪】【核心股交集】【今日推荐】 | `parsers/jingjia_sanyi.py` | `auction.json` |
| 一红+爆量.py | 连板爆量+高开 / 一红定江山 / 大盘爆量高开 | `parsers/yihong.py` | `premarket.json.sentinels` |
| 9431.py | 题材高开板块前三 + 金额/换手/人气前三 | `parsers/nine431.py` | `premarket.json.themes` + `auction.json` |
| 单核带队.py | 封单前五 + 涨停原因 + 概念下前三 | `parsers/danhedaidui.py` | `auction.json.fengdan_top5` |
| 梯队复盘.py | 涨停梯队 + 断板 + 涨跌停比 | `parsers/tidui_fupan.py` | `premarket.json.ladder` + `postmarket.json` |

详见 `PLAN.md §7`。

---

## 分期交付

- **P0（当前）**：骨架 + 规则引擎 + Flask 后端 + 手写 JSON 验证
- **P1**：`parsers/*.py` 真实解析器 + UI 精修 + 轮询完整实现
- **P2**：龙虎榜、模式命中率半自动、`refactored/` 直接写 JSON

详见 `PLAN.md §8`。

---

## 声明

本看板仅用于本人交易研究和盘中辅助决策。所有数据源脚本为第三方数据重组，存在延迟和错误可能。交易决策以个人独立判断为准。**研究参考，不构成投资建议。**
