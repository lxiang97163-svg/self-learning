# Reference 地图与自检清单

本包**不依赖**其他 Skill 目录；所有业务规则在 `daily-review-workflow-v2/` 内闭环。

**命名约定**：`执行手册_*.md` 与 `速查_*.md` 文件名中的日期 = **复盘日之次个交易日**（与复盘表脚本「下一交易日」一致），**不是**自然日的「次日」。

---

## 按步骤：应读哪些文件

| 流程步骤 | 必读 references |
|----------|-----------------|
| Step 0（验证） | `step2-analysis.md`（验证与 Step2 衔接）、`experience-appendix.md`（若需写经验库） |
| Step 1（脚本） | 无；异常见 `troubleshooting.md` |
| Step 2（核心） | `step2-analysis.md`（顺序+txt+判断要点）、`output-templates.md`（手册/速查骨架与生成规则）、`calibration-and-bidding.md`（竞价量纲）、`experience-appendix.md`（经验库写入）、`intraday-b-c-layers.md`（盘中 B/C 观察包规则，写速查 B/C 表前必读） |
| Step 2.5 | `calibration-and-bidding.md`（命令 + 更新「当前校准值」） |
| Step 3 | `output-templates.md` + `calibration-and-bidding.md` + `intraday-b-c-layers.md`（速查含 B/C 观察包时） |
| Step 4 | `troubleshooting.md`（PDF/Edge） |
| 单独「验证」 | `experience-appendix.md` 末尾「单独触发验证」 |

---

## 如何判断是否漏读了 reference（给你和 AI 用）

### 1. 对照「步骤 → 文件」表

每完成一步，在心上勾一遍：**该步骤列出的文件是否已读过**。若某步只跑脚本、不写文，可跳过纯 AI 规则文件。

### 2. 用本包内自检（推荐）

在仓库根目录执行（PowerShell），应对 **0 行**（无命中）：

```powershell
Select-String -Path ".cursor\skills\daily-review-workflow-v2\**\*" -Pattern "v1|daily-review-workflow/SKILL|旧版单文件|详见.*SKILL\.md" -Recurse
```

若出现命中，说明又有人写进了「去别处看」的依赖，应改回本包 `references/`。

### 3. 用主 SKILL 的索引表

打开 `daily-review-workflow-v2/SKILL.md` 底部 **「References 索引」**：生成执行手册/速查前，应至少包含：

- `step2-analysis.md`
- `output-templates.md`
- `calibration-and-bidding.md`
- `experience-appendix.md`（写过经验库时）

### 4. 结果侧漏检（跑完复盘后）

- **速查**缺少 `ts_code`、缺少健康度验证/完整链 → 多半未读 `output-templates.md` 生成规则段。
- **健康度**标的与「完整链」龙二/三/五不一致，或第一优先多题材却拆成多个 `#### 票池`、或未对齐 `速查_2026-04-16.md` 体例、**一带一路缺 3.4 龙二** → 未执行主 `SKILL.md`「流程基因」第 6～7 条与 `output-templates.md`「速查标题层级」「防错（强制）」。
- **速查**缺少「📡 盘中 B/C 观察包」或观察包不足 2 个题材/每包不足 5 只 → 未读 `output-templates.md` 本节或 `intraday-b-c-layers.md`。
- **竞价条件**出现固定亿数、或全场 ×0.3 → 未读 `calibration-and-bidding.md`。
- **经验库**未追加「未覆盖但赚钱」的题材行 → 未读 `experience-appendix.md` 强制写入规则。
- **校准值**与 `calc_calibration.py` 输出不一致 → Step2.5 未更新 `calibration-and-bidding.md` 第二节。

### 5. 与历史备份做差异核对（可选）

若你本地另有**单文件备份**，可偶尔用对比工具看章节标题是否一致（非必须）。**日常以本 v2 包为准**，避免两套规则并行修改。

---

## 本包文件一览

| 文件 | 用途 |
|------|------|
| `SKILL.md` | 主流程、命令、索引 |
| `references/step2-analysis.md` | Step2 读数、txt 方法论、判断要点、流程图 |
| `references/output-templates.md` | 执行手册/速查骨架 + 口诀与验证链规则 |
| `references/calibration-and-bidding.md` | 脚本说明、当前校准值、竞价量纲全文 |
| `references/experience-appendix.md` | 经验库表格与写入规范 |
| `references/troubleshooting.md` | Cookie、错误与 Edge |
| `references/intraday-b-c-layers.md` | 盘中 B/C 层：板块 ON、个股确认、顺位上车（与优先级一/二/A 层衔接） |
| `references/reference-map.md` | 本文件：地图与自检 |
