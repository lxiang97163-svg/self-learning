---
name: daily-review-workflow-v2
description: 每日股票复盘（v2 分包 Skill）。用户说「YYYYMMDD复盘」「跑今天复盘」「生成复盘/执行手册/跑复盘脚本」时启用。流程：Step0 条件验证 → Step1 并行 tushare 复盘表 + 韭研异动 → Step2 AI 读数据写经验库（见 references）→ Step2.5 calc_calibration → Step3 生成「复盘日之次个交易日」用的执行手册与速查（文件名日期非自然日次日）→ Step4 PDF → Step5 收尾。竞价/涨幅等事实须先跑脚本。Use when user says 复盘, 生成执行手册, 跑复盘脚本, or a date + 复盘.
---

# 每日复盘工作流（v2 · 主 SKILL）

## 设计说明（给 Agent）

本包按 **skill-creator** 拆成「主流程 + references」：此处只保留**必做顺序、路径、命令、何时读哪份 reference**，避免把近千行细则塞进单次触发正文。细则、模板全文、竞价量纲与经验库表结构均在 `references/` 中，**按步骤按需 Read**，不要一次性读完所有 reference。

---

## 流程基因（不可省略）

1. **纠偏在方法论与选股/题材**，不在单一数值上纠缠；条件用相对逻辑（两市前排、今日≥昨日×系数、涨幅≥校准值）。
2. **有依据才判定**：涉及竞价成交额、涨幅、封单等，**必须先运行脚本或接口**，禁止凭全日走势反推竞价。
3. **数据缺口**：发现复盘表缺字段 → 改对应 `.py` 提取逻辑 → 重跑 → 更新经验库「数据缺口记录」。
4. **双模态硬约束（v2.1 新增）**：速查**必须**包含「第零步：主线存活判断」4信号表 + B模式「备用主线候选」2个（每个5只股票 + 3条切换确认信号 + 「不满足2条不进」声明）+ 「今日不操作」空仓条件。**禁止**生成只有A模式、无B模式的速查。候选选取见 `references/step2-analysis.md`「备用主线候选选择方法」。
5. **速查完整性（v2 硬约束，与「极简」无关）**：低吸池**不得**仅因与第一/第二优先重叠而删票，须从复盘表 **3.5 节** 补位至每题材 **3～5 只**（有数据时）；「如果则」中涉及验证链/题材确认时 **风标前提不得省略**；「❌ 不做」须覆盖复盘表 **空头风标** 与 **数据异常高标**。全文见 `references/output-templates.md`。
6. **速查格式固定（不可「每天换一种」）**：体例**必须与**仓库内样例 **`jumpingnow_all/outputs/review/速查_2026-04-16.md` 一致**：`### 📋 票池速查` 下**仅** `### ✅ 第一优先（…）`、`### ✅ 第二优先（…）` 各一段（各含：买入表 → `> ⚠️` 健康度 → **一个** `#### xxx完整链`）；**禁止**用多个 `#### 子题材：票池` 把第一优先/第二优先再拆成两截；并列题材合并进**同一段**票池/备注/blockquote。**溢出路径**写在 **风标三阶段** 表后（引用块），与样例一致。详见 `references/output-templates.md`「速查标题层级」。
7. **多题材拆链（内容规则）**：健康度三只须与本段 **完整链** 龙二、龙三、龙五一致；**禁止**从第二优先、§3.2 其他多头风标借票。**一带一路** 在 3.4 有数据时 **龙二不得省略**。双题材共用跟风须标注 **「双题材锚」**。细则见 `references/output-templates.md`「题材验证链生成规则」「防错（强制）」。

---

## 工作区根路径

以下凡写 `WORKSPACE` 均指本仓库的 **`jumpingnow_all`** 目录（与 `outputs/`、`pipeline/`、`scripts/` 同级）。

- **当前环境（Linux）示例**：`/home/linuxuser/cc_file/jumpingnow_all`
- **`outputs/`**：`review/`（日更 md/json/pdf）、`knowledge/`（经验库与方法论文本等）、`cache/`（校准与接口缓存）、`logs/`（监控日志）。脚本在 **`pipeline/`**，读写路径由 `pipeline/_paths.py` 统一解析；命令行请使用下述绝对路径。
- **Linux 兼容提示（2026-04-11 补充）**：若系统没有 `python` 命令，统一改用 `python3`。本机已验证 `python` 不存在时会直接失败。
- **交易日历兜底（2026-04-11 补充）**：`trade_cal` 失效或 Token 过期时，复盘/校准脚本已回退到 `akshare` 交易日历；若你看到“次交易日”异常，先重跑脚本，不要手改输出日期。

---

## 产出物（归档，勿删中间 md）

| 产物 | 路径模式 |
|------|----------|
| 复盘表 | `outputs/review/每日复盘表_YYYY-MM-DD.md`（+ 同基名 `.pdf`） |
| 韭研异动 | `outputs/review/韭研异动_YYYY-MM-DD.md` |
| 执行手册（**次交易日**） | `outputs/review/执行手册_YYYY-MM-DD.md`（+ `.pdf`）**其中 YYYY-MM-DD = 复盘日之次个交易日** |
| 速查卡（**次交易日**） | `outputs/review/速查_YYYY-MM-DD.md`（+ `.pdf`）**同上** |
| 验证报告 | `outputs/review/验证报告_YYYY-MM-DD.md`（Step0 存在速查时） |
| 校准缓存 | `outputs/cache/calibration_cache.json`（勿手改） |
| 经验库 | `outputs/knowledge/经验库.md`（追加，勿整文件重写） |

---

## Step 0：昨日速查是否存在 → 是否跑验证

在用户指定复盘日 `YYYYMMDD`（「今天」= 当日交易日）下，先检查：

`outputs/review/速查_YYYY-MM-DD.md`（日期与**本次复盘日**一致）

- **存在** → 运行验证（事实输出，本步不写 AI 结论）：

```bash
python3 "/home/linuxuser/cc_file/jumpingnow_all/pipeline/verify_daily.py" --date YYYYMMDD
```

- **不存在** → 跳过 Step 0。

产物：`outputs/review/验证报告_YYYY-MM-DD.md`。

验证报告解读、与 Step2 合并分析的规则见 `references/step2-analysis.md`。

---

## Step 1：并行拉取当日结构化数据

解析日期后 **并行** 执行：

**1a — tushare 复盘表**

```bash
python3 "/home/linuxuser/cc_file/jumpingnow_all/pipeline/generate_review_from_tushare.py" --trade-date YYYYMMDD
```

**1b — 韭研公社异动（默认当天；Cookie 在脚本内）**

```bash
python3 "/home/linuxuser/cc_file/jumpingnow_all/pipeline/fetch_jiuyan_daily.py" --date YYYYMMDD
```

历史日期说明（2026-04-11 补充）：

- `fetch_jiuyan_daily.py` 在线抓取默认只保证**当天**页面可用。
- 当 `--date YYYYMMDD` 为**历史日期**时，脚本会**优先复用已存在**的 `韭研异动_YYYY-MM-DD.md/.json`。
- 若历史日期文件不存在，脚本会明确报错，避免把“今天”的韭研数据误写成历史日。

Cookie 失效时操作步骤见 `references/troubleshooting.md`。

---

## Step 2：AI 分析 + 写经验库（先经验，后出「次交易日」操作稿）

**必读顺序与校验协议**（含：经验库「数据缺口」置顶、复盘表 3.4/3.5、韭研、验证报告分层解读、经验库各表、`outputs/knowledge/` 下 txt 方法论、题材顺位逻辑）→ 全文见：

→ **`references/step2-analysis.md`**

生成「执行手册 / 速查」须遵守的**固定骨架与表格列** → 全文见：

→ **`references/output-templates.md`**

盘中 **B/C 观察包**（板块启动、个股确认、顺位上车，与优先级一/二互补）→ 全文见：

→ **`references/intraday-b-c-layers.md`**

竞价成交额量纲、涨幅校准、`calc_calibration.py` 与「当前校准值」维护 → 见：

→ **`references/calibration-and-bidding.md`**

经验库追加表格格式、失误类型、禁止数据穿越等 → 见：

→ **`references/experience-appendix.md`**

---

## Step 2.5：运行校准脚本（生成速查前）

在经验库写入本轮结论之后、生成「次交易日」的 `执行手册`/`速查` **之前**执行：

```bash
python3 "/home/linuxuser/cc_file/jumpingnow_all/pipeline/calc_calibration.py" --end-date YYYYMMDD --trade-days 30
```

将输出同步到 **`references/calibration-and-bidding.md`** 内「当前校准值」快照（勿手填数字，以脚本打印为准）。

---

## Step 3：生成执行手册与速查 md（文件名日期 = 次交易日）

依据 Step2.5 最新校准与 Step2 结论，写入（**文件名中的日期 = 复盘日之次个交易日**，与复盘表脚本「下一交易日」一致；遇周末/节假日跳过非交易日，非自然日「次日」）：

- `outputs/review/执行手册_<次交易日>.md`
- `outputs/review/速查_<次交易日>.md`

**次交易日**来源：以复盘表脚本 print 或复盘表正文「下一交易日 / 次日交易日」字段为准。

速查中个股须带 `**名称**(ts_code)`，供 `verify_daily` 匹配。

**Step3.1（生成速查 md 后必跑）**：在速查文件**最下方**写入「附录：速查标的·竞价快照」表（**生成速查当日**的 `stk_auction`，即速查**文件名日期的前一交易日**，与复盘日一致；供盘中监控对齐昨竞价额/涨幅）。须由脚本拉取事实数据，**禁止手填**：

```bash
python3 "/home/linuxuser/cc_file/jumpingnow_all/pipeline/append_speedcard_auction_snapshot.py" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/速查_YYYY-MM-DD.md"
```

- **当日**竞价 = 生成速查时所在的那个交易日 = 文件名日期的**前一交易日**（`fetch_prev_trade_date`，与复盘表日期一致）。若需指定：`--trade-date YYYYMMDD`。
- 重复运行会替换 `<!-- speedcard-auction-snapshot:start/end -->` 之间内容。
- **Step4 导出 PDF 前**执行本脚本，使 PDF 含附录表。

**Step3 落笔前自检（与「流程基因」第 4/5/6 条一致）**

1. 打开当日 **`每日复盘表_*` §3.4**：第一优先涉及几个题材，就准备几段 **「完整链」**；每段龙一～龙五与 **3.4 该题材表** 同行对齐（勿跳龙二）。  
2. **健康度**三只 = 该段完整链的 **龙二、龙三、龙五**（名称+代码与表内一致）；与 `references/output-templates.md` 中「防错（强制）」逐条对照。  
3. 「如果则」里凡写「验证链 / 健康度」，**侧必须与上述 A/B 块一致**，不得再出现已删除的错配标的（如用医药验航天）。  
4. 执行手册第三步「题材顺位」与速查 **同源**：执行手册可写分析句，**顺位与候选以 3.4+韭研为准**。
5. **B模式自检**：速查已含「第零步」4信号表？备用主线候选一、候选二各有5只股票？每个候选有3条切换确认信号且数值非占位符？「今日不操作」条件已写入「❌不做」？如有任一项未满足，补完再输出。
6. **唯一链 / 完整链去重**：双题材或跨概念重叠票，须按 `references/output-templates.md`「防错（强制）」第 4～5 条与复盘 **§3.4.1「建议主归因」** 只进入**一条**「第一优先 / 第二优先」内的完整链主表；另一条链用 **§3.4 顺位递补**补位，**禁止**同一 `ts_code` 在同一速查两套主链重复出现。

---

## Step 4：导出 PDF

对**复盘表（复盘日）**、**执行手册（次交易日）**、**速查（次交易日）**分别转换（路径中 `YYYY-MM-DD` 按实际替换；**复盘表日期 = 复盘日**，**执行手册/速查日期 = 同一次交易日**）：

```bash
python3 "/home/linuxuser/cc_file/jumpingnow_all/scripts/md_to_pdf.py" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/每日复盘表_YYYY-MM-DD.md" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/每日复盘表_YYYY-MM-DD.pdf"

python3 "/home/linuxuser/cc_file/jumpingnow_all/scripts/md_to_pdf.py" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/执行手册_YYYY-MM-DD.md" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/执行手册_YYYY-MM-DD.pdf"

python3 "/home/linuxuser/cc_file/jumpingnow_all/scripts/md_to_pdf.py" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/速查_YYYY-MM-DD.md" "/home/linuxuser/cc_file/jumpingnow_all/outputs/review/速查_YYYY-MM-DD.pdf"
```

（`每日复盘表` 两条路径中的日期均为**复盘日**；`执行手册` 与 `速查` 各自两条路径中的日期均为**复盘日之次个交易日**，与 Step3 一致。）

Edge 未安装等见 `references/troubleshooting.md`。

---

## Step 5：收尾

保留所有 `.md` 与 `.pdf`，不删除。向用户汇总生成文件路径。

---

## 单独触发「验证」

用户仅说「验证YYYYMMDD」时：运行 Step0 的 `verify_daily.py`，并按 `references/experience-appendix.md` 追加经验库；**不**重新生成执行手册/速查（除非用户另行要求）。

---

## 单独触发「仅补速查」（执行手册已有）

适用：**复盘表与执行手册已生成**，但同一次交易日的 **`速查_<次交易日>.md` 缺失**（例如只跑了手册或中途中断）。用户明确「从执行手册补速查」「不要重复前面步骤」时启用。

**不要**再跑 Step0～Step2.5（不重拉 tushare/韭研、不重跑 `calc_calibration.py`），除非用户要求校准刷新。

**必做顺序**：

1. 打开 **`执行手册_<次交易日>.md`**（内文「复盘日」一行可反推复盘日日期）。
2. 打开 **`每日复盘表_<复盘日>.md`**，核对 **§3.2 空头风标、§3.4 各题材完整链、§3.4.1 双题材锚、§3.5 轮动池**（速查「低吸/盘中观察/❌不做」与手册须同源）。
3. 按需 Read **`references/output-templates.md`**（固定骨架、B 模式 5+5、健康度与完整链规则）。
4. 写入 **`outputs/review/速查_<次交易日>.md`**（与执行手册**同名日期**）；个股一律 `**名称**(ts_code)`。
5. 仅当用户要归档 PDF 时，再对该 md 执行 Step4 的 `md_to_pdf.py`。

---

## 流程总览（简图）

```
输入(日期+复盘) → [Step0 速查存在? verify_daily]
               → Step1 并行: tushare + 韭研
               → Step2 读数据/写经验库（references）
               → Step2.5 calc_calibration
               → Step3 执行手册 + 速查 md（日期=次交易日）
               → Step4 md_to_pdf（复盘表日期=复盘日；手册+速查日期=次交易日）
               → Step5 汇报路径
```

完整分支说明见 `references/step2-analysis.md` 末尾「流程图补充」。

---

## References 索引

| 文件 | 何时读 |
|------|--------|
| `references/reference-map.md` | **首次使用或自检**：步骤与文件对照、如何发现漏读 |
| `references/step2-analysis.md` | 执行 Step2 时 |
| `references/output-templates.md` | 写执行手册/速查时 |
| `references/intraday-b-c-layers.md` | 写速查「盘中观察」（板块够强+分时确认）、维护阈值；用户分发版勿写路径/脚本名 |
| `references/calibration-and-bidding.md` | 写竞价条件、跑校准、更新阈值快照时 |
| `references/experience-appendix.md` | 追加经验库、单独验证时 |
| `references/troubleshooting.md` | 脚本失败、PDF、Cookie、Token |

维护约定：只在本包 `daily-review-workflow-v2/` 内改规则；重大变更可在 `outputs/knowledge/经验库.md` 或本 SKILL 顶部备注日期。
