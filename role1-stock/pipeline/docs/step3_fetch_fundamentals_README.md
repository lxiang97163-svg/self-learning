# Step 3: Fetch Fundamentals Data

从 `generate_review_from_tushare.py` 中提取的独立脚本，获取基本面数据。

## 功能

1. **日行情排行**（第 845-894 行提取）
   - 计算近 5 日和 10 日的累计涨幅排行（并行化）
   - 使用 ThreadPoolExecutor 并行请求多个交易日数据
   - 输出：`top_5d_text`, `top_10d_text`

2. **概念成分股**（第 764-778 行提取）
   - 获取涨停概念及其成分股代码
   - 优先使用 `kpl_concept_cons`，回退 `ths_member`
   - 使用 ThreadPoolExecutor 并行查询 10 个概念
   - 输出：`theme_code_map: {theme_name: [ts_code, ...]}`

3. **龙虎榜数据**（第 917-944 行提取）
   - 获取龙虎榜前 8 只股票及其机构净买额
   - 查询 `pro.top_list()` 和 `pro.top_inst()`
   - 输出：`lhb_rows: [{name, reason, net_buy_yi}, ...]`

4. **换手率异常**（第 896-905 行提取）
   - 获取当日换手率排行（前 5）
   - 查询 `pro.daily_basic(trade_date, fields="ts_code,turnover_rate,amount")`
   - 输出：`turn_text`, `db` (DataFrame as list)

## 依赖

### 输入文件
- `step1_base_data.json` - 包含 `name_map` （股票代码→名称映射）
- `step2_limits_data.json` - 包含 `trade_date` （交易日期）

### Python 包
- `pandas`
- `chinadata` (chinadata.ca_data)
- `concurrent.futures`

### API
- Tushare Pro (token in script)

## 使用方法

```bash
python3 step3_fetch_fundamentals.py --trade-date YYYYMMDD [--output-dir /path/to/outputs]
```

### 示例
```bash
python3 step3_fetch_fundamentals.py --trade-date 20260401 --output-dir ./outputs
```

## 输出

**文件**: `step3_fundamentals_data.json`

**结构**:
```json
{
  "top_5d_text": "string (e.g., '股票A(+5.20%);股票B(+4.80%)' or '—')",
  "top_10d_text": "string (e.g., '股票A(+10.50%)...' or '—')",
  "theme_code_map": {
    "theme_name": ["000001.SZ", "000002.SZ", ...],
    "another_theme": ["600000.SH", ...]
  },
  "lhb_rows": [
    {"name": "股票名", "reason": "上榜原因", "net_buy_yi": 0.25},
    {"name": "股票名2", "reason": "", "net_buy_yi": -0.15},
    ...
  ],
  "turn_text": "string (e.g., '股票A(45.50%);股票B(42.30%)...' or '—')",
  "db": [
    {"ts_code": "000001.SZ", "name": "平安银行", "turnover_rate": 45.5, "amount": 12345.6},
    ...
  ]
}
```

## 优化点

### ThreadPoolExecutor 并行化

1. **日行情窗口计算**（`calc_window_top_text`）
   - 并行请求 5 个或 10 个交易日的数据
   - `max_workers=5`
   - 减少网络延迟

2. **概念成分股查询**（`fetch_fundamentals`）
   - 并行查询 10 个概念的成分股代码
   - 使用 `as_completed()` 处理结果
   - 优雅降级：单个概念查询失败不影响其他

## 错误处理

- 依赖文件缺失：抛出 `FileNotFoundError`
- 指数数据获取失败：返回默认值 `"—"` 或空列表
- 单个概念查询失败：记录警告，继续处理其他概念
- 龙虎榜为空：返回空行（自动补齐到 5 行）
- 换手率数据缺失：`turn_text = "—"`, `db = []`

## 核心函数

| 函数 | 作用 |
|------|------|
| `load_dependencies()` | 从 step1/step2 加载 name_map 和 trade_date |
| `calc_window_top_text()` | 计算 N 日涨幅排行（ThreadPoolExecutor） |
| `_get_concept_cons_codes()` | 获取概念成分股（kpl_concept_cons / ths_member） |
| `fetch_fundamentals()` | 主逻辑：获取所有基本面数据 |
| `_safe_float()` | 安全浮点数转换 |
| `_is_excluded()` | 过滤 ST/北交所/科创板 |

## 集成说明

- **独立可运行**：无需依赖其他步骤的脚本，只需输入 JSON 文件
- **JSON 格式**：所有输出使用 JSON（便于后续步骤集成）
- **向后兼容**：所有字段和数据格式与原脚本保持一致

## 注意事项

1. 必须先运行 step1 和 step2，生成相应的 JSON 文件
2. Tushare token 硬编码在脚本中；如需更改，编辑 `TOKEN` 常量
3. ThreadPoolExecutor 使用 5 个工作线程，可根据需要调整 `max_workers` 参数
4. 股票过滤逻辑（`_is_excluded`）排除 ST、北交所（.BJ）和科创板（68 开头）
