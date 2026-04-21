# 步骤4-5 输出示例文档

本文档展示 `step4_fetch_auction.py` 和 `step5_fetch_rotation.py` 的输出 JSON 结构与示例。

---

## 步骤4：竞价成交数据

### 文件：`step4_auction_data.json`

#### 完整示例

```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "auc_text": "航天科技 金额2150.30万，竞价涨跌+3.25%；北斗导航 金额1980.50万，竞价涨跌+2.10%；芯片制造 金额1750.20万，竞价涨跌+1.85%；新能源 金额1520.80万，竞价涨跌-0.50%；锂电产业 金额1380.60万，竞价涨跌-1.15%",
  "auc_count": 5,
  "auc_rows": [
    {
      "ts_code": "000921.SZ",
      "name": "航天科技",
      "amount": 215030000.0,
      "price": 10.35,
      "pre_close": 10.03,
      "pct": 3.1906
    },
    {
      "ts_code": "002174.SZ",
      "name": "北斗导航",
      "amount": 198050000.0,
      "price": 25.68,
      "pre_close": 25.17,
      "pct": 2.0261
    },
    {
      "ts_code": "600900.SH",
      "name": "芯片制造",
      "amount": 175020000.0,
      "price": 15.92,
      "pre_close": 15.63,
      "pct": 1.8568
    },
    {
      "ts_code": "300750.SZ",
      "name": "新能源",
      "amount": 152080000.0,
      "price": 38.50,
      "pre_close": 38.70,
      "pct": -0.5168
    },
    {
      "ts_code": "000100.SZ",
      "name": "锂电产业",
      "amount": 138060000.0,
      "price": 12.35,
      "pre_close": 12.49,
      "pct": -1.1208
    }
  ]
}
```

#### 字段说明

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `trade_date` | string | 交易日期（YYYYMMDD格式） | `20260305` |
| `trade_date_h` | string | 交易日期（YYYY-MM-DD格式，便于显示） | `2026-03-05` |
| `auc_text` | string | **竞价成交文本摘要**（直接用于报告） | `"航天科技 金额2150.30万，竞价涨跌+3.25%；..."` |
| `auc_count` | int | 竞价成交股票总数 | `5` |
| `auc_rows` | array | 竞价成交股票详细信息（按成交金额降序，最多5条） | 见下表 |

#### auc_rows[i] 字段说明

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `ts_code` | string | 股票代码（tushare 格式） | `000921.SZ` |
| `name` | string | 股票名称 | `航天科技` |
| `amount` | float | 竞价成交金额（元） | `215030000.0` |
| `price` | float | 竞价成交价格 | `10.35` |
| `pre_close` | float | 昨日收盘价 | `10.03` |
| `pct` | float | 竞价涨跌幅（%） | `3.1906` |

#### 数据清洗规则

1. **排除条件**：
   - 名称包含 "ST" （特别处理股）
   - ts_code 以 ".BJ" 结尾（北交所）
   - ts_code 以 "68" 开头（科创板）

2. **排序规则**：按成交金额（amount）降序，取前5只

3. **文本摘要格式**：
   ```
   股票名 金额X.XXX万，竞价涨跌+/-Y.YY%；股票名 金额X.XXX万，竞价涨跌+/-Y.YY%；...
   ```

#### 边界情况

**无竞价成交数据**：
```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "auc_text": "—",
  "auc_count": 0,
  "auc_rows": []
}
```

---

## 步骤5：轮动热力追踪

### 文件：`step5_rotation_data.json`

#### 完整示例

```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "past_5_days": ["20260227", "20260228", "20260301", "20260304", "20260305"],
  "rotation_content": "#### 热力趋势表（退潮题材2个·全量显示，当前活跃题材取前3个作背景参考）\n\n| 题材 | 02/27 | 02/28 | 03/01 | 03/04 | 今日(03/05) | 趋势 | 阶段 |\n|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n| 商业航天 | **15** | 12 | 8 | 5 | 3 | ↓ | ✅低吸窗口 |\n| 芯片设计 | 12 | **18** | 14 | 7 | 2 | ↓ | ✅低吸窗口 |\n| 锂电池 | 8 | 10 | 11 | **14** | 13 | → | 🔥高潮 |\n| AI大模型 | 6 | 7 | **9** | 8 | 8 | → | 📈发酵 |\n| 新能源车 | 4 | 5 | 6 | 7 | 8 | ↑ | 📈发酵 |\n\n> 峰值数字**加粗**。✅低吸窗口 = 深度退潮，有资金记忆，等信号低吸；⚠️退潮中 = 刚开始退潮，观察为主；🔥/📈 = 当前活跃题材，参考背景用，不属于轮动低吸候选。\n\n#### 退潮题材龙头池\n\n**商业航天**（峰值 15只 · 2026-02-27 → 今日 3只 · ✅低吸窗口）\n\n| 顺位 | 股票 | 峰值板数 | 峰值封单 | 涨停历史 | 开板次数 |\n|:---:|---|:---:|---|---|:---:|\n| 龙1 | **航天科技** | 3板 | 2.15亿 | 连涨停 | ✅未开板 |\n| 龙2 | **中国卫星** | 2板 | 1.80亿 | 2023-01-15 | 开1次 |\n| 龙3 | **高新技术** | 2板 | 0.95亿 | — | ✅未开板 |\n\n**芯片设计**（峰值 18只 · 2026-02-28 → 今日 2只 · ✅低吸窗口）\n\n| 顺位 | 股票 | 峰值板数 | 峰值封单 | 涨停历史 | 开板次数 |\n|:---:|---|:---:|---|---|:---:|\n| 龙1 | **芯动科技** | 4板 | 2.80亿 | 连涨停 | ✅未开板 |\n| 龙2 | **集成电路** | 3板 | 1.50亿 | 2023-03-20 | 开2次 |\n",
  "top_concepts": [
    {
      "code": "BK6614",
      "name": "商业航天",
      "today_count": 3
    },
    {
      "code": "BK0474",
      "name": "芯片设计",
      "today_count": 2
    },
    {
      "code": "BK0493",
      "name": "锂电池",
      "today_count": 13
    },
    {
      "code": "BK1046",
      "name": "AI大模型",
      "today_count": 8
    },
    {
      "code": "BK0527",
      "name": "新能源车",
      "today_count": 8
    }
  ]
}
```

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `trade_date` | string | 交易日期（YYYYMMDD格式） |
| `trade_date_h` | string | 交易日期（YYYY-MM-DD格式） |
| `past_5_days` | array | 过去5个交易日列表（YYYYMMDD格式） |
| `rotation_content` | string | **轮动追踪完整 Markdown 内容**（直接用于执行手册） |
| `top_concepts` | array | 热门概念列表（可用于下游分析） |

#### top_concepts[i] 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | string | 概念代码（如 BK6614） |
| `name` | string | 概念名称（如 商业航天） |
| `today_count` | int | 今日涨停数量 |

#### rotation_content 结构

`rotation_content` 是完整的 Markdown 文本，包含两个主要部分：

**1. 热力趋势表**
- 行标题：题材、过去5个交易日、趋势、阶段
- 数据行：每个热门题材的5日涨停数、趋势箭头、阶段标签
- 峰值数字加粗标记
- 阶段图标：`🔥高潮`、`📈发酵`、`⚠️退潮中`、`✅低吸窗口`、`👀观察`

**2. 退潮题材龙头池**
- 按题材分组
- 每个题材下展示前5个龙头股票
- 包含板数、封单资金、涨停历史、开板次数

#### 阶段判断规则

| 阶段 | 条件 | 用途 |
|------|------|------|
| `高潮` | 今日涨停数 ≥ 峰值 × 0.8 | 谨慎，可能高位接盘 |
| `发酵` | 环比上升，今日 ≥ 5只 | 可考虑参与 |
| `退潮中` | 峰值后下降，但 > 峰值 × 0.6 | 观察为主 |
| `深度退潮` | 今日 ≤ max(3, 峰值 × 0.25) | **低吸窗口** |
| `观察` | 其他 | 等待信号 |

#### 排序规则

1. **热力趋势表**：
   - 退潮题材（深度退潮/退潮中）全部显示，按峰值降序
   - 其他活跃题材（高潮/发酵）最多显示5个，按今日数降序

2. **龙头池**：
   - 仅展示退潮题材
   - 每个题材最多显示5个龙头

#### 数据过滤

1. **概念层过滤**：
   - 排除名称包含 "ST" 的概念
   - 仅保留5日内 **至少1天涨停数 ≥ 8** 的概念

2. **个股层过滤**：
   - 排除 ST 股、北交所股、科创板股（68开头）

3. **概念成分查询优先级**：
   - ① 优先用 `theme_code_map`（当日活跃概念映射）
   - ② 回退用 `limit_cpt_list` 历史概念代码 + `kpl_concept_cons()`
   - ③ 最终兜底：个股行业字段匹配

#### 边界情况

**无热门题材**（5日内无涨停数 ≥ 8）：
```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "past_5_days": ["20260227", "20260228", "20260301", "20260304", "20260305"],
  "rotation_content": "> 5日内无显著热门题材（峰值涨停数均低于8只），轮动追踪暂无数据。\n",
  "top_concepts": []
}
```

**数据不足**（少于2个交易日）：
```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "past_5_days": ["20260305"],
  "rotation_content": "> 交易数据不足（少于2个交易日），无法生成轮动追踪。\n",
  "top_concepts": []
}
```

---

## 数据使用示例

### 在 Python 中加载

#### step4 数据
```python
import json

with open('step4_auction_data.json', 'r', encoding='utf-8') as f:
    auc_data = json.load(f)

# 获取竞价摘要
print(auc_data['auc_text'])  # 直接用于报告

# 获取逐股数据
for row in auc_data['auc_rows']:
    print(f"{row['name']}: {row['pct']:+.2f}%")
```

#### step5 数据
```python
import json

with open('step5_rotation_data.json', 'r', encoding='utf-8') as f:
    rot_data = json.load(f)

# 获取 Markdown 内容（直接嵌入执行手册）
print(rot_data['rotation_content'])

# 获取热门概念
for concept in rot_data['top_concepts'][:5]:
    print(f"{concept['name']}: 今日{concept['today_count']}只涨停")
```

### 在 Markdown 中嵌入

```markdown
# 执行手册 - 2026-03-05

## 轮动方向

<!-- 直接粘贴 step5 的 rotation_content -->

## 竞价观察

<!-- 直接粘贴 step4 的 auc_text -->

竞价成交情况：{auc_text}
```

### 合并两个输出

```bash
jq -s '{auction: .[0], rotation: .[1]}' \
  step4_auction_data.json \
  step5_rotation_data.json \
  > merged.json
```

---

## 性能和大小参考

### 步骤4 输出
- **文件大小**：5-50 KB（取决于竞价股票数）
- **行数**：10-200 行
- **竞价文本长度**：100-500 字符

### 步骤5 输出
- **文件大小**：20-100 KB（热力追踪内容是主要）
- **Markdown 长度**：500-2000 行
- **热门概念数**：通常 5-15 个

### API 调用次数
- **步骤4**：1 次（stk_auction）
- **步骤5**：3-15 次（limit_cpt_list、limit_list_d、概念查询）

---

## 验证和调试

### JSON 验证

```bash
# 检查 JSON 格式
python3 -m json.tool step4_auction_data.json > /dev/null && echo "✅ step4 JSON 有效"
python3 -m json.tool step5_rotation_data.json > /dev/null && echo "✅ step5 JSON 有效"
```

### 字段验证

```bash
# 检查必需字段
jq 'keys' step4_auction_data.json
jq 'keys' step5_rotation_data.json

# 检查数据类型
jq '.auc_count | type' step4_auction_data.json  # 应为 "number"
jq '.top_concepts | type' step5_rotation_data.json  # 应为 "array"
```

### 输出预览

```bash
# 竞价摘要
jq '.auc_text' step4_auction_data.json

# Markdown 预览（前30行）
jq '.rotation_content' step5_rotation_data.json | head -30
```
