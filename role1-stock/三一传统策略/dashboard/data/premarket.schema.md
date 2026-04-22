# premarket.json · Schema 说明

> 盘前快照。由 `parsers/yihong.py`、`parsers/tidui_fupan.py`、手工维护共同生成。

## 字段

| 字段 | 类型 | 说明 | 取值范围 |
|------|------|------|---------|
| `updated_at` | ISO8601 string | 最后更新时间 | 带时区 |
| `trade_date` | string | 交易日 | `YYYY-MM-DD` |
| `indices[]` | array | 指数关键位 + IF-THEN | 通常 2-4 个 |
| `indices[].name` | string | 指数名 | 上证指数 / 创业板指 / 科创50 / 深证成指 |
| `indices[].point` | number or null | 前一日收盘点位 | > 0 |
| `indices[].key_support` | number or null | 关键支撑位 | > 0 |
| `indices[].key_resistance` | number or null | 关键压力位 | > 0 |
| `indices[].ifthen` | string | IF-THEN 提示短句 | 中文 |
| `overseas[]` | array | 隔夜外盘参考 | |
| `overseas[].name` | string | 名称 | |
| `overseas[].symbol` | string | 代码 | KWEB / PGJ / NQ 等 |
| `overseas[].change_pct` | number or null | 隔夜涨跌幅 % | -20.0 ~ 20.0 |
| `overseas[].note` | string | 备注 | |
| `sentinels[]` | array | 情绪风标候选 | |
| `sentinels[].role` | string | 角色 | `多头风标候选` / `空头风标候选` |
| `sentinels[].code` | string | 代码 | `600xxx` / `000xxx` 等 |
| `sentinels[].name` | string | 股名 | |
| `sentinels[].yesterday_pct` | number or null | 昨日涨跌 % | -10.0 ~ 20.0 |
| `sentinels[].reason` | string | 判定理由 | |
| `themes.main[]` | array | 主线题材 | 最多 5 个 |
| `themes.main[].name` | string | 题材名 | |
| `themes.main[].strength_pct` | number or null | 强度（平均涨幅） | -10.0 ~ 10.0 |
| `themes.main[].leaders[]` | string[] | 龙头代码列表 | |
| `themes.sub[]` | array | 支线题材 | 同 main |
| `ladder` | object | 涨停梯队分布（板数 → 只数） | 键 `1..9`，值 ≥0 |
| `duanban[]` | array | 断板统计 | |
| `duanban[].code` | string | 代码 | |
| `duanban[].name` | string | 股名 | |
| `duanban[].highest_board` | int | 断板前最高板 | 1-20 |
| `duanban[].reason` | string | 所在题材 / 原因 | |
| `notes` | string | 备注 | |

## 关联规则

- `ladder.9 >= 1` → `advisor.py` 触发「情绪周期高潮」提醒
- `duanban[]` 非空且最高板为昨日最高板 → 触发铁律：**断板次日 = 情绪 0 分，强制空仓**
- `indices[].point` 跌破 `key_support` → 触发「指数跌破关键位」critical 提醒
