# 步骤4-5 独立脚本使用指南

本指南说明如何独立运行 `step4_fetch_auction.py` 和 `step5_fetch_rotation.py` 两个新脚本。

---

## 概览

### 脚本1: `step4_fetch_auction.py`
**功能**：获取竞价成交数据，进行数据清洗并排除 ST 股。

**输入**：
- 交易日期（YYYYMMDD）
- 股票基础信息映射（来自 `stock_basic_cache.csv`）

**输出**：
- `step4_auction_data.json` - 包含竞价成交数据和文本摘要

**依赖**：
- chinamindata (tushare 分钟级数据)
- pandas

---

### 脚本2: `step5_fetch_rotation.py`
**功能**：生成近5日题材热力追踪与轮动方向分析。

**输入**：
- 交易日期（YYYYMMDD）
- 过去5个交易日（自动或手动提供）
- 股票基础信息映射

**输出**：
- `step5_rotation_data.json` - 包含热力追踪内容和热门概念列表

**依赖**：
- chinadata (tushare API)
- pandas
- concurrent.futures (并行查询概念成分)

---

## 快速开始

### 前置条件

1. **Python 3.8+** 和必要的包：
   ```bash
   pip install pandas requests akshare
   ```

2. **股票基础信息缓存** (可选，脚本会自动生成)：
   ```bash
   python3 step4_fetch_auction.py --trade-date 20260305
   # 首次运行时会自动下载并缓存 stock_basic_cache.csv
   ```

3. **tushare Token**（已内置在脚本中）

---

## 运行步骤4

### 基础用法

```bash
python3 step4_fetch_auction.py --trade-date 20260305
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--trade-date` | 交易日期（YYYYMMDD格式） | 20260305 |
| `--name-map-path` | 股票映射缓存文件路径 | stock_basic_cache.csv |
| `--output` | 输出 JSON 文件路径 | step4_auction_data.json |

### 输出示例

`step4_auction_data.json`:
```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "auc_text": "股票A 金额100.50万，竞价涨跌+2.15%；股票B 金额98.30万，竞价涨跌-1.20%",
  "auc_count": 5,
  "auc_rows": [
    {
      "ts_code": "000001.SZ",
      "name": "平安银行",
      "amount": 100500000,
      "price": 10.20,
      "pre_close": 9.99,
      "pct": 2.10
    }
  ]
}
```

---

## 运行步骤5

### 基础用法（自动查询过去5个交易日）

```bash
python3 step5_fetch_rotation.py --trade-date 20260305
```

### 指定过去5个交易日（推荐）

如果已有 step1 的输出（包含 tdays 列表）：

```bash
python3 step5_fetch_rotation.py \
  --trade-date 20260305 \
  --tdays-json step1_market_data.json
```

### 手动指定过去5个交易日

```bash
python3 step5_fetch_rotation.py \
  --trade-date 20260305 \
  --past-5-days "20260227,20260228,20260301,20260304,20260305"
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--trade-date` | 交易日期（YYYYMMDD格式） | 20260305 |
| `--past-5-days` | 过去5个交易日，逗号分隔 | 自动查询 |
| `--tdays-json` | 包含 tdays 的 JSON 文件 | None |
| `--name-map-path` | 股票映射缓存文件 | stock_basic_cache.csv |
| `--output` | 输出 JSON 文件路径 | step5_rotation_data.json |

### 输出示例

`step5_rotation_data.json`:
```json
{
  "trade_date": "20260305",
  "trade_date_h": "2026-03-05",
  "past_5_days": ["20260227", "20260228", "20260301", "20260304", "20260305"],
  "rotation_content": "#### 热力趋势表\n\n| 题材 | ... |",
  "top_concepts": [
    {
      "code": "885601.TI",
      "name": "商业航天",
      "today_count": 12
    }
  ]
}
```

---

## 数据依赖关系

### step4 的输入依赖

```
step4_fetch_auction.py
  ├─ 参数：--trade-date (YYYYMMDD)
  ├─ 文件：stock_basic_cache.csv (股票名称映射)
  └─ API：chinamindata.min.stk_auction()
```

### step5 的输入依赖

```
step5_fetch_rotation.py
  ├─ 参数：--trade-date (YYYYMMDD)
  ├─ 参数：--past-5-days 或 --tdays-json (推荐来自step1输出)
  ├─ 文件：stock_basic_cache.csv
  └─ API：
      ├─ pro.limit_cpt_list()        (5日概念涨停)
      ├─ pro.limit_list_d()          (5日涨停个股)
      ├─ pro.kpl_concept_cons()      (概念成分)
      └─ pro.ths_member()            (回退概念成分)
```

---

## 与原 generate_review_from_tushare.py 的对应关系

### step4 提取内容

**源文件行号**：932-944

**主要逻辑**：
```python
auc = pro_min.stk_auction(trade_date=trade_date)
auc["name"] = auc["ts_code"].map(name_map)
auc = auc[~auc.apply(lambda r: _is_excluded(...), axis=1)]
auc["pct"] = (auc["price"] - auc["pre_close"]) / auc["pre_close"] * 100
```

**提取的辅助函数**：
- `_safe_float()` - 安全浮点转换
- `_fmt_pct()` - 百分比格式化
- `_is_excluded()` - ST股/北交所/科创板过滤

### step5 提取内容

**源文件行号**：1135-1141（调用点）、321-568（函数体）

**主要逻辑**：
```python
rotation_section_md = _build_rotation_section(
    pro=pro,
    past_5_days=past_5_days,
    trade_date=trade_date,
    name_map=name_map,
    theme_code_map=theme_code_map,
)
```

**提取的函数**：
- `_build_rotation_section()` - 主函数
- `_get_concept_cons_codes()` - 概念成分代码查询
- `_parse_theme_cell()` - 题材名称解析

**提取的辅助函数**：
- `_safe_float()`, `_safe_int()`
- `_fd_yi()` - 亿元格式化
- `_is_excluded()` - 股票过滤

---

## 独立运行场景

### 场景1：仅需竞价数据

```bash
python3 step4_fetch_auction.py --trade-date 20260305
```

此时 step5 不需要运行。

### 场景2：需要轮动分析（推荐工作流）

**步骤1**：先运行 step4（获取缓存）
```bash
python3 step4_fetch_auction.py --trade-date 20260305
```

**步骤2**：运行 step5（需要过去5个交易日）
```bash
# 方法A：自动查询（网络慢，不推荐）
python3 step5_fetch_rotation.py --trade-date 20260305

# 方法B：手动指定（推荐）
python3 step5_fetch_rotation.py \
  --trade-date 20260305 \
  --past-5-days "20260227,20260228,20260301,20260304,20260305"

# 方法C：使用 step1 的输出（最佳）
python3 step5_fetch_rotation.py \
  --trade-date 20260305 \
  --tdays-json step1_market_data.json
```

---

## 故障排查

### 错误：`ModuleNotFoundError: No module named 'chinadata'`

**原因**：chinadata/chinamindata 包未安装

**解决**：
```bash
pip install chinadata chinamindata
# 或从项目包中加载
```

### 错误：`FileNotFoundError: stock_basic_cache.csv`

**原因**：首次运行，缓存文件未生成

**解决**：脚本会自动从 API 下载生成，或手动运行：
```bash
python3 step4_fetch_auction.py --trade-date 20260305
```

### 错误：API 调用超时或 403

**原因**：tushare token 过期或网络问题

**解决**：
1. 检查 TOKEN/TOKEN_MIN 是否有效
2. 增加 API 调用间隔
3. 使用代理或检查网络

### 警告：`过去5个交易日查询缓慢`

**原因**：自动查询模式需要拉取50天历史数据

**解决**：使用 `--past-5-days` 或 `--tdays-json` 参数直接指定

---

## JSON 输出格式详解

### step4_auction_data.json

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | string | 交易日期（YYYYMMDD） |
| trade_date_h | string | 交易日期（YYYY-MM-DD） |
| auc_text | string | 竞价成交文本摘要 |
| auc_count | int | 竞价成交股票数量 |
| auc_rows | array | 逐股明细（包含成交金额、竞价价格、涨跌幅） |

### step5_rotation_data.json

| 字段 | 类型 | 说明 |
|------|------|------|
| trade_date | string | 交易日期（YYYYMMDD） |
| trade_date_h | string | 交易日期（YYYY-MM-DD） |
| past_5_days | array | 过去5个交易日 |
| rotation_content | string | 轮动追踪完整 Markdown 内容 |
| top_concepts | array | 热门概念列表（包含代码、名称、今日涨停数） |

---

## 进阶用法

### 并行运行多个交易日

```bash
for date in 20260301 20260302 20260303; do
  python3 step4_fetch_auction.py --trade-date $date --output "auc_$date.json" &
done
wait
```

### 集成到自动化工作流

```bash
#!/bin/bash
TRADE_DATE="20260305"

# step4 - 竞价数据
python3 step4_fetch_auction.py --trade-date $TRADE_DATE

# step5 - 轮动追踪
python3 step5_fetch_rotation.py \
  --trade-date $TRADE_DATE \
  --output "rotation_$TRADE_DATE.json"

# 合并输出
python3 -c "
import json
with open('step4_auction_data.json') as f1:
    auc = json.load(f1)
with open('rotation_$TRADE_DATE.json') as f2:
    rot = json.load(f2)
merged = {'auction': auc, 'rotation': rot}
with open('merged_$TRADE_DATE.json', 'w') as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)
"
echo "✅ 合并完成：merged_$TRADE_DATE.json"
```

---

## 性能指标

### step4 (竞价数据)

- **运行时间**：1-3 秒
- **API 调用**：1 次
- **输出大小**：~5-50 KB

### step5 (轮动追踪)

- **运行时间**：5-15 秒（含并行概念查询）
- **API 调用**：3-15 次（limit_cpt_list、limit_list_d、概念成分查询）
- **输出大小**：~20-100 KB

---

## 常见问题

**Q: step4 和 step5 是否可以并行运行？**

A: 可以。它们使用不同的 API 实例，没有数据冲突。

**Q: 输出 JSON 是否可以直接用于下游脚本？**

A: 可以。JSON 格式已标准化，可直接加载使用。

**Q: 如何处理节假日或交易日遗漏？**

A: 使用 step1 的 tdays 输出作为过去5个交易日的来源，自动处理日期跳跃。

**Q: 缓存文件何时需要更新？**

A: `stock_basic_cache.csv` 可保留，仅在新股上市或摘牌时建议刷新。

---

## 许可和贡献

这两个脚本从 `generate_review_from_tushare.py` 提取并独立化，保留原有的逻辑和注释风格。

如有 bug 或改进建议，请更新原始脚本后重新提取。
