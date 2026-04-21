---
name: multi-source-daily-review
description: 全网检索成体系复盘维度 + 本地复盘表事实 → 长文《多源复盘长文》→ 交易员口吻小红书；或仅根据本地表生成小红书。触发词：全网复盘、多源复盘、搜索型复盘、长文复盘、多源复盘+小红书、复盘长文+小红书、发小红书、复盘发社媒、根据复盘表发小红书。数值以 jumpingnow_all/outputs/review/ 内复盘表为准；小红书格式见本包 references/xiaohongshu-output.md。
---

# 多源检索 → 长文复盘 → 小红书

## 何时启用

- **全流程**：**全网复盘**、**多源复盘**、**搜索型复盘**、**长文复盘**、**多源复盘报告**、**按网上框架写复盘**、**复盘长文+小红书** 等。  
- **仅小红书**（不强制检索）：**发小红书**、**复盘发社媒**、**根据复盘表发小红书**、**社媒版复盘** —— 执行 Step 0～1 后 **跳过 Step 2～3**，直接 **Step 4**（读 `references/xiaohongshu-output.md`）。

## 核心原则（硬约束）

1. **事实优先级**：指数、成交额、涨跌停、题材家数、封单、连板高度、晋级率等 **必须先读** `jumpingnow_all/outputs/review/每日复盘表_YYYY-MM-DD.md`（及可用的 `执行手册_*.md`、`速查_*.md`）。网传检索与本地冲突 → **以本地为准**。
2. **检索定位**：Web 仅用于维度与舆论对照，**不替代**脚本数据。
3. **反套话**：长文与小红书禁止孤立「首板最多」、万能「跌停炸板」段（除非同段写清今昨对比或与主线联动/边缘），见 `references/xiaohongshu-output.md`。
4. **小红书终稿**：**唯一规范**为本包 **`references/xiaohongshu-output.md`**（已合并原独立小红书 Skill）。**不再存在** `xiaohongshu-review-post` 独立 Skill 路径。

## 工作流（顺序固定）

### Step 0：确定复盘日

- 用户给 `YYYYMMDD` / `YYYY-MM-DD`；「今天」→ 当日已收盘交易日；不确定则问用户或取最新 `每日复盘表_*.md`。

### Step 1：本地取数（必做）

1. 读取 `jumpingnow_all/outputs/review/每日复盘表_<复盘日>.md`。  
2. 若存在：`验证报告_<复盘日>.md`；`执行手册_<次交易日>.md`、`速查_<次交易日>.md`。  
3. 提取：指数、量能环比、涨跌家数、涨停跌停、最高板、晋级率摘要、题材 Top **今昨对比**、核心封单 **今 vs 昨**、关键位。  
4. 缺失写 **未披露**，不编造。

### Step 2：全网检索（仅「全流程」时必做）

用户 **仅要小红书** 时 **跳过** 本节。

否则：至少 **4 次** Web 检索，覆盖 **≥10 类** 来源维度（见 `references/source-cheat-sheet.md`）；长文内列表：**来源类型｜关键词｜补充维度（不替代本地数字）**。

### Step 3：撰写《多源复盘长文》（仅「全流程」时必做）

用户 **仅要小红书** 时 **跳过**。

- 默认路径：`jumpingnow_all/outputs/review/多源复盘长文_<复盘日>.md`  
- 结构：`references/longform-outline.md`；**观点 + 本地数据**。  
- 只要对话不落盘时注明即可。

### Step 4：生成小红书正文（用户需要时必做）

1. **Read** `references/xiaohongshu-output.md`，严格按 **输出形态、标题、禁忌** 执行。  
2. 素材：**多源长文结论**（若已写）+ **Step 1 事实**；数字再核对一遍。  
3. 叠加：开篇必为交易矛盾；风险样本须点明与主线联动或边缘；「只看三件事」须具体。

### Step 5：收尾

- 全流程：汇报长文路径 + 小红书正文。  
- 仅小红书：只输出 **可复制正文**（除非用户也要保存 md）。  
- 无本地复盘表：提示先跑 `daily-review-v2` 或 `generate_review_from_tushare.py`。

## 与现有 Skill 的关系

| Skill | 关系 |
|------|------|
| `daily-review-workflow-v2` | 产出本地复盘表/手册/速查；本 Skill **依赖**其为事实源 |
| ~~`xiaohongshu-review-post`~~ | **已删除**；小红书规则见 `references/xiaohongshu-output.md` |

## References

- `references/longform-outline.md`：长文章节骨架。  
- `references/source-cheat-sheet.md`：检索来源速查。  
- `references/xiaohongshu-output.md`：**小红书正文唯一规范**。
