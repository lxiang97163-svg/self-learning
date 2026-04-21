# 交易与复盘 SOP：单一入口

> **用途**：按时间找「说什么触发 AI」「依赖哪些文件」「可选跑什么命令」。  
> **路径基准**：本文件所在目录 = 工作区根目录（下文记作 `根/`）。  
> **技能细节**：完整步骤以 `.cursor/skills/*/SKILL.md` 为准；本页只作索引。

---

## 快速对照表

| 时段（北京时间） | 触发词（对 AI 说） | 主要依赖文件 | 可选命令 |
|------------------|-------------------|--------------|----------|
| **08:30～09:00** | 盘前报告、盘前进攻、今天打什么、早盘方向、盘前分析 | `.cursor/skills/premarket-attack/SKILL.md`；产出见 `A股信息整理/outputs/盘前进攻_YYYY-MM-DD.md` | 见 [盘前进攻](#盘前进攻-830900) |
| **09:15～09:25** | 竞价验证、验证盘前、9:25 验证、竞价认账 | 当日 `A股信息整理/outputs/盘前进攻_YYYY-MM-DD.md`；tushare token | 见 [竞价验证](#竞价验证-925-前后) |
| **09:30～10:00** | 今天什么盘型、今天开盘怎么样、早盘盘型、开盘八法 | `outputs/knowledge/开盘八法.txt`；脚本输出即事实源 | `python pipeline/opening_pattern_data.py` |
| **09:15～15:00** | `.`、`监控`、`结论`、`开启监控` | 当日 `outputs/review/速查_YYYY-MM-DD.md`；`outputs/logs/realtime_monitor_log.txt` | `python pipeline/realtime_engine.py --once`（单次快照）；循环见下 |
| **收盘后 / 任意** | `YYYYMMDD复盘`、`帮我生成复盘`、`跑今天复盘`、`生成执行手册` | `outputs/knowledge/经验库.md`；`.cursor/skills/daily-review-workflow-v2/SKILL.md` | 见 [每日复盘](#每日复盘工作流) |
| **收盘后（次日验证）** | 同上复盘流中 Step0/Step4 自动带 | `outputs/review/速查_YYYY-MM-DD.md`（若存在） | `python pipeline/verify_daily.py --date YYYYMMDD` |
| **任意** | md 转 pdf、导出 PDF | `scripts/md_to_pdf.py` | `python scripts/md_to_pdf.py <输入.md> <输出.pdf>` |
| **任意** | 发小红书、复盘发社媒 | `outputs/review/每日复盘表_YYYY-MM-DD.md` | 无（AI 读表生成文案） |

---

## 盘前进攻（8:30～9:00）

**触发词**：盘前报告、盘前进攻、今天打什么、早盘方向、盘前分析  

**依赖**  
- Skill：`.cursor/skills/premarket-attack/SKILL.md`  
- 脚本：`A股信息整理/scripts/fetch_premarket.py`（概念参数按当日分析填写）  
- 产出目录：`A股信息整理/outputs/`（如 `盘前进攻_YYYY-MM-DD.md`、`盘前数据_YYYY-MM-DD.json`）

**典型命令**（示例，概念以当日为准）：

```bash
python "A股信息整理/scripts/fetch_premarket.py" --concepts 概念A:首日 概念B:第2日 --date YYYYMMDD
```

**说明**：流程中含 AI 联网搜索与期货—概念映射；完整步骤见对应 SKILL。

---

## 竞价验证（9:25 前后）

**触发词**：竞价验证、验证盘前、9:25 验证、竞价认账  

**依赖**  
- 当日盘前进攻报告：`A股信息整理/outputs/盘前进攻_YYYY-MM-DD.md`  
- 脚本：`A股信息整理/scripts/pre_market_verify.py`  
- 需 tushare / `chinamindata` 等（见脚本内说明）

**典型命令**：

```bash
python "A股信息整理/scripts/pre_market_verify.py" --date YYYYMMDD
```

**产出**：`A股信息整理/outputs/竞价验证_YYYY-MM-DD.md`

---

## 开盘八法 / 今日盘型（9:30 后，前三根 5 分钟齐）

**触发词**：今天什么盘型、今天开盘怎么样、早盘盘型、开盘八法  

**依赖**  
- `outputs/knowledge/开盘八法.txt`（定性用语与操作建议）  
- `pipeline/opening_pattern_data.py`（**必须先跑**，禁止用新闻替代行情）

**命令**：

```bash
python pipeline/opening_pattern_data.py
```

---

## 实时监控（9:15～15:00）

**触发词**：`.`、`监控`、`结论`、`开启监控`  

**依赖**  
- 当日 `outputs/review/速查_YYYY-MM-DD.md`（脚本按**系统日期**解析文件名；无则当日卡不存在）  
- 日志：`outputs/logs/realtime_monitor_log.txt`（由引擎写入）

**命令**：

```bash
python pipeline/realtime_engine.py --once
```

持续循环（交易时段每分钟）：`python pipeline/realtime_engine.py`（无 `--once`）

**说明**：腾讯个股涨跌幅解析以 `realtime_engine.py` 为准（昨收字段需与接口一致）；完整协议见 `.cursor/skills/realtime-market-monitor/SKILL.md`。

---

## 每日复盘工作流

**触发词**：`YYYYMMDD复盘`、`帮我生成复盘`、`跑今天复盘`、`生成执行手册`、`生成速查`  

**依赖**  
- Skill：`.cursor/skills/daily-review-workflow-v2/SKILL.md`（Step0～Step4 全流程）  
- 核心产出：`outputs/review/`（日更 md/pdf）、`outputs/knowledge/`（经验库等）、`outputs/cache/`、`pipeline/`（脚本）

**常用命令（日期自行替换）**：

```bash
python pipeline/verify_daily.py --date YYYYMMDD
python pipeline/generate_review_from_tushare.py --trade-date YYYYMMDD
python pipeline/fetch_jiuyan_daily.py
python pipeline/calc_calibration.py --end-date YYYYMMDD --trade-days 30
python scripts/md_to_pdf.py "outputs/review/执行手册_YYYY-MM-DD.md"
```

**说明**：Step2 由 AI 读表写执行手册/速查；韭研脚本默认抓「当天」，Cookie 见 SKILL 内维护说明。

---

## Markdown → PDF

**触发词**：md 转 pdf、导出 pdf、复盘导出  

**依赖**：`scripts/md_to_pdf.py`；Windows + Edge（见 `.cursor/skills/md-to-pdf/SKILL.md`）

```bash
python -m pip install markdown
python scripts/md_to_pdf.py "outputs/review/每日复盘表_YYYY-MM-DD.md" "outputs/review/每日复盘表_YYYY-MM-DD.pdf"
```

---

## 小红书发文

**触发词**：发小红书、复盘发社媒、根据复盘表发小红书  

**依赖**：`outputs/review/每日复盘表_YYYY-MM-DD.md`；可选 `outputs/review/验证报告_YYYY-MM-DD.md`  

详见：仓库根 `.cursor/skills/multi-source-daily-review/SKILL.md`（仅小红书时跳过检索与长文）；正文格式见同目录 `references/xiaohongshu-output.md`。

---

## 相关规则与扩展

| 项 | 位置 |
|----|------|
| 数据与结论须有依据 | `.cursor/rules/agent-integrity.mdc` |
| 找装技能 / 技能市场 | 用户规则中的 `find-skills`、`skillhub-preference` skill |

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-03-30 | 初版：时间表 + 触发词 + 依赖 + 命令索引 |
