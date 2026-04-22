# postmarket.json · Schema 说明

> 盘后快照。由 `parsers/tidui_fupan.py` + `parsers/lhb.py`（P2）或人工复盘填充。

## 字段

| 字段 | 类型 | 说明 | 取值范围 |
|------|------|------|---------|
| `updated_at` | ISO8601 string | 最后更新时间 | |
| `trade_date` | string | 交易日 | `YYYY-MM-DD` |
| `limit_up_count` | int | 今日涨停数（不含 ST / 科创/创业板） | ≥0 |
| `limit_down_count` | int | 今日跌停数 | ≥0 |
| `ratio` | number or null | `limit_up / max(limit_down, 1)` | |
| `blast_count` | int | 炸板数 | ≥0 |
| `dragon_tiger[]` | array | 龙虎榜要点 | |
| `dragon_tiger[].code` | string | 代码 | |
| `dragon_tiger[].name` | string | 股名 | |
| `dragon_tiger[].seat` | string | 席位名（游资/机构） | |
| `dragon_tiger[].direction` | string | `买入` / `卖出` | |
| `dragon_tiger[].amount_yi` | number or null | 金额（亿） | |
| `dragon_tiger[].note` | string | 备注 | |
| `pattern_hit_rate[]` | array | 模式命中率（今日复盘） | |
| `pattern_hit_rate[].pattern` | string | 模式名 | 三一买点 / 一红定江山 / 断板弱转强 / 单核带队 等 |
| `pattern_hit_rate[].triggered_count` | int | 今日触发次数 | ≥0 |
| `pattern_hit_rate[].hit_count` | int | 次日兑现次数 | ≥0 |
| `pattern_hit_rate[].hit_rate` | number or null | 命中率 % | 0-100 |
| `pattern_hit_rate[].remark` | string | 命中判定规则 | |
| `next_day_plan[]` | array | 次日预案 | |
| `next_day_plan[].theme` | string | 题材名 | |
| `next_day_plan[].leaders[]` | string[] | 龙头代码 | |
| `next_day_plan[].watch_points` | string | 盯盘要点 | |
| `next_day_plan[].plan_tag` | string | 预案标签 | 观察 / 接力 / 低吸 / 回避 |

## 关联规则

- `ratio < 0.5` → 明日情绪偏弱
- `limit_up_count > 80` → 情绪过热，警惕分歧
- `blast_count > 20` → 情绪降温，对炸板六原则要求更严
- `next_day_plan[]` 将由 `advisor.py` 次日盘前读取并转成指引
