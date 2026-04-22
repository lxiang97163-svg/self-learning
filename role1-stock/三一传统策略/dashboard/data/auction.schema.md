# auction.json · Schema 说明

> 竞价快照（9:15 – 9:30 密集刷新）。由 `parsers/jingjia_sanyi.py` + `parsers/nine431.py` + `parsers/danhedaidui.py` 合成。

## 字段

| 字段 | 类型 | 说明 | 取值范围 |
|------|------|------|---------|
| `updated_at` | ISO8601 string | 最后更新时间 | |
| `trade_date` | string | 交易日 | `YYYY-MM-DD` |
| `themes_strength[]` | array | 题材强度排行 | 降序 |
| `themes_strength[].name` | string | 题材名 | |
| `themes_strength[].avg_pct` | number or null | 题材平均涨幅 % | -10.0 ~ 10.0 |
| `themes_strength[].leaders[]` | string[] | 题材龙头代码 | |
| `market_sentiment.score` | number or null | 综合指标 % | 通常 -5.0 ~ 5.0 |
| `market_sentiment.label` | string | 情绪标签 | 冰点 / 偏冷 / 中性 / 偏暖 / 过热 |
| `market_sentiment.note` | string | 备注 | |
| `core_intersection[]` | array | 核心股交集 | 通常 ≤5 只 |
| `core_intersection[].code` | string | 代码 | |
| `core_intersection[].name` | string | 股名 | |
| `core_intersection[].sector` | string | 所属核心股板块 | |
| `core_intersection[].pct_chg` | number or null | 竞价涨跌 % | -10.0 ~ 20.0 |
| `core_intersection[].rank` | int or null | 板块内 rank | ≥1 |
| `recommendations[]` | array | 【今日推荐】 | |
| `recommendations[].code` | string | 代码 | |
| `recommendations[].name` | string | 股名 | |
| `recommendations[].pct` | number or null | 竞价涨跌 % | |
| `recommendations[].rank` | int or null | rank | |
| `recommendations[].circ_mv` | number or null | 流通市值（亿） | ≥0 |
| `recommendations[].reason` | string | 推荐原因（题材/模式） | |
| `recommendations[].concept` | string | 所属概念 | |
| `recommendations[].concept_open_pct` | number or null | 板块今日高开 % | |
| `recommendations[].concept_limitup_count` | int | 板块内涨停数 | ≥0 |
| `recommendations[].reason_tag` | string | 模式标签 | `sanyi` / `duanban_ruozhuanqiang` / `yihong` / `danhe` |
| `recommendations[].small_trap` | bool | 是否小盘陷阱 | `circ_mv < 20 && turnover > 20` |
| `fengdan_top5[]` | array | 竞价封单前五 | 长度 ≤ 5 |
| `fengdan_top5[].code` | string | 代码 | |
| `fengdan_top5[].name` | string | 股名 | |
| `fengdan_top5[].seal_amount_yi` | number or null | 封单金额（亿元） | ≥0 |
| `fengdan_top5[].lu_desc` | string | 涨停原因 | kpl 提供 |
| `fengdan_top5[].concept` | string | 最相关同花顺概念 | |
| `fengdan_top5[].concept_auction_top3[]` | array | 概念下竞价金额/换手前三 | |

## 关联规则

- `recommendations[].small_trap == true` → `advisor.py` 触发「小盘陷阱跳过」warn
- `recommendations[].reason_tag == 'sanyi' && !small_trap` → 触发「符合三一买点」info
- `fengdan_top5[].seal_amount_yi > 5` → 可配合炸板六原则判断回封质量
- `core_intersection[]` 非空 → 头部提示「核心股命中」
