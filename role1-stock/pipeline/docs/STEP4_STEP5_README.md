# 步骤4-5 脚本提取与独立化指南

**版本**：1.0  
**创建日期**：2026-04-07  
**源文件**：`generate_review_from_tushare.py`

---

## 目录

1. [概览](#概览)
2. [脚本列表](#脚本列表)
3. [快速开始](#快速开始)
4. [依赖关系](#依赖关系)
5. [详细文档](#详细文档)
6. [常见问题](#常见问题)

---

## 概览

从 `generate_review_from_tushare.py` 中提取两个独立脚本：

| 脚本 | 功能 | 输入 | 输出 |
|------|------|------|------|
| **step4_fetch_auction.py** | 获取竞价成交数据 | trade_date | step4_auction_data.json |
| **step5_fetch_rotation.py** | 轮动热力追踪分析 | trade_date + past_5_days | step5_rotation_data.json |

**关键特点**：
- ✅ 完全独立运行，无需完整的复盘流程
- ✅ JSON 输出格式，易于集成下游系统
- ✅ 包含所有必需的辅助函数
- ✅ 支持并行执行
- ✅ 自动化脚本集成

---

## 脚本列表

### 核心脚本

```
outputs/
├── step4_fetch_auction.py          [新建] 竞价成交数据获取
├── step5_fetch_rotation.py         [新建] 轮动热力追踪
├── run_step4_step5.sh              [新建] 集成运行脚本
├── STEP4_STEP5_README.md           [新建] 本文档
├── STEP4_STEP5_USAGE.md            [新建] 详细使用指南
└── STEP4_STEP5_OUTPUT_EXAMPLES.md  [新建] 输出示例与说明
```

### 现有文件（可保持）

```
├── generate_review_from_tushare.py  [原] 完整复盘脚本
├── stock_basic_cache.csv            [存在时复用] 股票映射缓存
└── calibration_cache.json           [存在时复用] 竞价校准数据
```

---

## 快速开始

### 最小化用法（5分钟上手）

```bash
cd /home/linuxuser/cc_file/jumpingnow_all/pipeline

# 方式1：运行单个脚本
python3 step4_fetch_auction.py --trade-date 20260305
python3 step5_fetch_rotation.py --trade-date 20260305

# 方式2：运行集成脚本
./run_step4_step5.sh 20260305
```

### 推荐用法（指定过去5个交易日）

```bash
# 使用手动指定的过去5个交易日
./run_step4_step5.sh 20260305 "20260227,20260228,20260301,20260304,20260305"
```

### 与自动化工作流集成

```bash
# 在 crontab 或 workflow 中
python3 step4_fetch_auction.py --trade-date $(date +%Y%m%d)
python3 step5_fetch_rotation.py --trade-date $(date +%Y%m%d) \
  --tdays-json step1_output.json
```

---

## 依赖关系

### step4 依赖关系图

```
step4_fetch_auction.py
  ├── 输入参数：
  │   └── --trade-date (YYYYMMDD)
  ├── 外部依赖：
  │   ├── chinamindata (tushare 分钟级)
  │   ├── pandas
  │   └── requests (间接)
  └── 输出：
      └── step4_auction_data.json
```

### step5 依赖关系图

```
step5_fetch_rotation.py
  ├── 输入参数：
  │   ├── --trade-date (YYYYMMDD)
  │   ├── --past-5-days (逗号分隔，可选)
  │   └── --tdays-json (step1 输出，推荐)
  ├── 外部依赖：
  │   ├── chinadata (tushare API)
  │   ├── pandas
  │   ├── concurrent.futures
  │   └── requests (间接)
  └── 输出：
      └── step5_rotation_data.json
```

### 文件依赖

| 文件 | 用途 | 来源 | 是否必需 |
|------|------|------|--------|
| stock_basic_cache.csv | 股票名称映射 | 首次自动生成 | 推荐 |
| step1_output.json | 交易日历 | 来自 step1 | 可选（自动查询）|

---

## 详细文档

### 使用文档
👉 **[STEP4_STEP5_USAGE.md](STEP4_STEP5_USAGE.md)**
- 每个脚本的完整参数说明
- 运行示例和命令
- 故障排查

### 输出示例
👉 **[STEP4_STEP5_OUTPUT_EXAMPLES.md](STEP4_STEP5_OUTPUT_EXAMPLES.md)**
- JSON 完整输出示例
- 字段说明和数据类型
- 边界情况处理
- Python/Markdown 集成示例

---

## 常见问题

### Q1: step4 和 step5 需要按顺序运行吗？

**A**: 不需要。它们完全独立：
- step4 输出 → step4_auction_data.json（竞价数据）
- step5 输出 → step5_rotation_data.json（轮动追踪）

可以并行运行：
```bash
python3 step4_fetch_auction.py --trade-date 20260305 &
python3 step5_fetch_rotation.py --trade-date 20260305 &
wait
```

### Q2: step5 的 past_5_days 参数从哪里来？

**A**: 三种方式（按优先级）：

1. **最佳**：使用 step1 的输出（如有）
   ```bash
   python3 step5_fetch_rotation.py --trade-date 20260305 \
     --tdays-json step1_market_data.json
   ```

2. **推荐**：手动指定
   ```bash
   python3 step5_fetch_rotation.py --trade-date 20260305 \
     --past-5-days "20260227,20260228,20260301,20260304,20260305"
   ```

3. **自动查询**（慢，不推荐）
   ```bash
   python3 step5_fetch_rotation.py --trade-date 20260305
   # 自动拉取50天历史数据再计算
   ```

### Q3: 输出 JSON 可以直接用于报告吗？

**A**: 完全可以！

- step4 的 `auc_text` → 直接嵌入报告
- step5 的 `rotation_content` → 是 Markdown，直接嵌入

示例：
```python
import json
from pathlib import Path

with open('step4_auction_data.json') as f:
    auc = json.load(f)

# 在执行手册中
report = f"""
## 竞价观察
{auc['auc_text']}
"""
```

### Q4: 如何处理 API 超时或数据缺失？

**A**: 脚本有自动降级机制：

- step4：使用 pro_min（分钟级）或回退 AKShare
- step5：缺失概念成分时显示警告，但继续生成

推荐方式：加入错误处理
```bash
set -e  # 任何命令失败则退出
python3 step4_fetch_auction.py --trade-date 20260305 || {
  echo "❌ step4 失败"
  exit 1
}
```

### Q5: 可以自定义输出格式吗？

**A**: JSON 格式固定，但可以后处理：

```bash
# 提取特定字段
jq '.auc_text' step4_auction_data.json

# 转换为 CSV
jq -r '.auc_rows | .[] | [.ts_code, .name, .pct] | @csv' \
  step4_auction_data.json > auction.csv

# 合并两个输出
jq -s '{auction: .[0], rotation: .[1]}' \
  step4_auction_data.json step5_rotation_data.json > merged.json
```

### Q6: 如何在生产环境中自动运行？

**A**: 使用 crontab 或工作流编排：

```cron
# crontab -e
# 每个交易日 18:00 运行
0 18 * * 1-5 cd /path/to/outputs && \
  ./run_step4_step5.sh $(date +\%Y\%m\%d) >> logs/run_$(date +\%Y%m%d).log 2>&1
```

或使用 GitHub Actions / GitLab CI：
```yaml
schedule:
  - cron: '0 18 * * 1-5'  # 周一至周五 18:00
```

---

## 源文件对应关系

### step4_fetch_auction.py

| 来源 | 行号 | 内容 |
|------|------|------|
| generate_review_from_tushare.py | 932-944 | 竞价数据获取与清洗 |
| generate_review_from_tushare.py | 174-194 | 辅助函数（_safe_float、_fmt_pct） |
| generate_review_from_tushare.py | 212-222 | _is_excluded() 过滤函数 |

**新增内容**：
- 命令行参数接口
- JSON 输出序列化
- 缓存管理逻辑

### step5_fetch_rotation.py

| 来源 | 行号 | 内容 |
|------|------|------|
| generate_review_from_tushare.py | 321-568 | _build_rotation_section() 核心函数 |
| generate_review_from_tushare.py | 232-257 | _get_concept_cons_codes() |
| generate_review_from_tushare.py | 225-229 | _parse_theme_cell() |
| generate_review_from_tushare.py | 174-204 | 辅助工具函数 |

**新增内容**：
- 命令行参数接口
- JSON 输出序列化
- 日期自动查询逻辑
- 并行概念查询优化

---

## 验证清单

在使用前，请确认：

- [ ] Python 3.8+ 已安装
- [ ] 依赖包已安装：`pip install pandas requests chinadata chinamindata`
- [ ] 脚本文件存在于 outputs/ 目录
- [ ] 首次运行 step4 生成 stock_basic_cache.csv
- [ ] 如使用 step1 输出，确认文件路径正确

### 快速验证

```bash
# 检查脚本语法
python3 -m py_compile step4_fetch_auction.py step5_fetch_rotation.py

# 运行 help
python3 step4_fetch_auction.py --help
python3 step5_fetch_rotation.py --help

# 测试运行（如有网络和API访问权限）
python3 step4_fetch_auction.py --trade-date 20260305
```

---

## 文件清单

```
step4_fetch_auction.py               5.8 KB   Python 脚本
step5_fetch_rotation.py              20  KB   Python 脚本
run_step4_step5.sh                   2.8 KB  Bash 集成脚本
STEP4_STEP5_README.md               ~10 KB  本文档
STEP4_STEP5_USAGE.md                ~15 KB  详细使用指南
STEP4_STEP5_OUTPUT_EXAMPLES.md       ~12 KB  输出示例
```

总计：~65 KB

---

## 更新和维护

### 何时需要更新脚本？

- [ ] 源脚本 generate_review_from_tushare.py 修改了相关逻辑
- [ ] tushare API 接口变更
- [ ] 需要新增功能（参数、输出字段）

### 更新流程

1. 在源脚本中修改相应逻辑
2. 重新提取相关函数到 step4/step5
3. 测试新的 JSON 输出格式
4. 更新本文档和示例

---

## 许可和引用

这些脚本从 `generate_review_from_tushare.py` 提取，保留原有的逻辑和注释。

如需引用或分发，请注明来源。

---

## 支持和反馈

遇到问题或有改进建议？

1. 检查 [STEP4_STEP5_USAGE.md](STEP4_STEP5_USAGE.md) 的故障排除部分
2. 查看 [STEP4_STEP5_OUTPUT_EXAMPLES.md](STEP4_STEP5_OUTPUT_EXAMPLES.md) 的示例
3. 验证输入参数和数据来源
4. 查看脚本日志输出（[DEBUG] 行）

---

## 下一步

1. **立即使用**：运行 `./run_step4_step5.sh 20260305`
2. **深入学习**：阅读 [STEP4_STEP5_USAGE.md](STEP4_STEP5_USAGE.md)
3. **集成系统**：根据 [STEP4_STEP5_OUTPUT_EXAMPLES.md](STEP4_STEP5_OUTPUT_EXAMPLES.md) 的示例开发下游处理
4. **自动化运行**：设置 crontab 或工作流定时执行

---

**更新时间**：2026-04-07  
**版本**：1.0
