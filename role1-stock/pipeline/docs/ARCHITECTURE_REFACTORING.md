# 脚本拆分重构方案（文件拆分 + 多 Agent 并行）

**目标**：从串行执行 → 并行执行，减少总耗时 60-75%

---

## 当前架构（单文件 + ThreadPool）

```
generate_review_from_tushare.py (1500 行)
├─ 初始化（token、API）
├─ 基础数据（stock_basic、指数历史）  
├─ 涨跌停池、概念、龙虎榜（串行调用，已 ThreadPool）
├─ 日行情、成分股、机构数据（已 ThreadPool）
├─ 竞价成交
├─ 热力追踪
└─ 模板渲染 + 写文件

执行流程：
step1 → step2 → step3 → step4 → step5 → 渲染
总耗时：60-75 秒（或 ThreadPool 优化后 30-40 秒）
```

---

## 新架构（拆分 + 并行）

```
outputs/
├─ step1_fetch_base_data.py       (5-8秒)
│  └─ 输出：step1_base_data.json
├─ step2_fetch_limits.py          (8-10秒)
│  └─ 输出：step2_limits_data.json
├─ step3_fetch_fundamentals.py    (10-15秒，含 ThreadPool 优化)
│  └─ 输出：step3_fundamentals_data.json
├─ step4_fetch_auction.py         (3-5秒)
│  └─ 输出：step4_auction_data.json
├─ step5_fetch_rotation.py        (8-12秒)
│  └─ 输出：step5_rotation_data.json
├─ step6_merge_and_render.py      (5秒)
│  └─ 最终输出：每日复盘表_YYYY-MM-DD.md
└─ orchestrate_parallel_steps.py   (编排脚本)
   └─ 使用 ProcessPoolExecutor 并行运行 step1-5

执行流程（并行）：
┌─ step1 (5-8秒)
├─ step2 (8-10秒)
├─ step3 (10-15秒)  ← 最长的那个
├─ step4 (3-5秒)
└─ step5 (8-12秒)
       ↓ （等待全部完成）
     step6 (5秒)

总耗时：max(8, 10, 15, 5, 12) + 5 = 20 秒（对比原始 60-75 秒）
```

---

## 文件拆分详细说明

### Step 1：基础数据抓取（step1_fetch_base_data.py）

**职责**：初始化 API、加载股票映射、获取指数历史

**输入**：
- `--trade-date YYYYMMDD`

**输出**：
```json
{
  "name_map": {
    "000001.SZ": "平安银行",
    "600000.SH": "浦发银行"
  },
  "tdays": ["2026-03-28", "2026-03-30", "2026-03-31", ...],
  "t_idx": 47,
  "prev_trade": "2026-04-06",
  "sh": {"close": 3500.12, "pct_chg": 1.23, ...},
  "sz": {"close": 11500.45, "pct_chg": 0.89, ...},
  "cyb": {"close": 2800.67, "pct_chg": -0.45, ...},
  "sh_prev": {"close": 3456.78, ...},
  "trade_date": "2026-04-07"
}
```

**特性**：
- 独立运行，无依赖
- 包含本地缓存逻辑（stock_basic_cache.csv）
- 错误处理：API 失败时返回 error 字段

---

### Step 2：涨跌停、概念、龙虎榜（step2_fetch_limits.py）

**职责**：获取市场热点数据

**输入**：
- `--trade-date YYYYMMDD`
- `--base-data step1_base_data.json`（可选，用于 name_map）

**输出**：
```json
{
  "df_zt": [{ts_code: "000001.SZ", name: "平安银行", ...}, ...],
  "df_dt": [...],
  "df_zb": [...],
  "df_kpl": [...],
  "top_concepts": [
    ["TS0001", "科技股", 45],
    ["TS0002", "AI概念", 38],
    ...
  ],
  "df_cpt": [...],
  "lhb": [...],
  "zt_cnt": 45,
  "dt_cnt": 8,
  "zb_cnt": 12
}
```

**特性**：
- 包含所有 AKShare 备用函数
- 自动 failover（API 失败 → AKShare）

---

### Step 3：日行情、成分股、机构（step3_fetch_fundamentals.py）

**职责**：核心数据拉取（5日+10日涨幅、概念成分、龙虎榜机构）

**输入**：
- `--trade-date YYYYMMDD`
- `--base-data step1_base_data.json`
- `--limits-data step2_limits_data.json`

**输出**：
```json
{
  "top_5d_text": "美亚柏科(12.56%)；三维通信(11.23%)；...",
  "top_10d_text": "美亚柏科(18.67%)；三维通信(15.89%)；...",
  "theme_code_map": {
    "科技股": ["600000.SH", "000001.SZ", ...],
    "AI概念": ["300750.SZ", ...],
    ...
  },
  "lhb_rows": [
    ["股票1", "理由", 1.23],
    [...],
    ["", "", 0.0]
  ],
  "turn_text": "N日涨(10.2%)；N日跌(5.3%)；...",
  "db": [...]
}
```

**特性**：
- **已包含 ThreadPoolExecutor 优化**：
  - pro.daily() 15 次 → 5 worker 并行
  - 概念成分股 10 次 → 5 worker 并行

---

### Step 4：竞价成交（step4_fetch_auction.py）

**职责**：获取开盘竞价成交数据

**输入**：
- `--trade-date YYYYMMDD`
- `--base-data step1_base_data.json`

**输出**：
```json
{
  "auc": [{ts_code: "000001.SZ", amount: 1230000, price: 15.23, ...}, ...],
  "auc_text": "美亚柏科 金额123.45万，竞价涨跌+2.34%；..."
}
```

---

### Step 5：热力追踪（step5_fetch_rotation.py）

**职责**：近 5 日题材热力追踪

**输入**：
- `--trade-date YYYYMMDD`
- `--base-data step1_base_data.json`
- `--limits-data step2_limits_data.json`

**输出**：
```json
{
  "rotation_content": "## 近5日主线轮动...",
  "top_concepts": [...]
}
```

---

### Step 6：合并和渲染（step6_merge_and_render.py）

**职责**：加载 5 个 JSON、合并、填充模板、输出最终 Markdown

**输入**：
- `--trade-date YYYYMMDD`

**流程**：
1. 等待 5 个 JSON 文件完成（超时 300 秒）
2. 加载并验证数据完整性
3. 填充 markdown 模板（或使用 `每日复盘表_模板.md`）
4. 写入 `outputs/每日复盘表_YYYY-MM-DD.md`

**输出**：
- `outputs/每日复盘表_YYYY-MM-DD.md`

---

## 编排脚本（orchestrate_parallel_steps.py）

**功能**：管理并行执行

```bash
python3 orchestrate_parallel_steps.py --trade-date 20260407 --workers 5 --timeout 60
```

**工作流**：
1. 启动 5 个 ProcessPoolExecutor worker
2. 并行提交 step1-5 的任务
3. 监听完成消息，汇总结果
4. 如果全部成功，启动 step6
5. 返回最终文件路径

---

## 性能对比

| 指标 | 原始 | ThreadPool | 文件拆分 | 改进幅度 |
|------|------|-----------|---------|---------|
| **总耗时** | 60-75s | 30-40s | 20-30s | **60-75%** |
| **并行度** | 0（串行） | 2（local threads） | 5（processes） | **5x** |
| **单点故障** | 全脚本崩溃 | 全脚本崩溃 | 单个 step 隔离 | ✅ |
| **可测试性** | 差 | 中 | 好 | ✅ |
| **可维护性** | 差（1500行） | 中（1500行） | 好（分散） | ✅ |

---

## 迁移策略

**Phase 1**（当前）：ThreadPool 优化
- 修改原脚本的关键循环
- 测试性能提升

**Phase 2**（备选）：文件拆分
- 如果 Phase 1 效果有限（> 40秒），启动本方案
- 创建 6 个新文件 + 1 个编排脚本
- 逐步测试各 step 的独立运行

**Phase 3**（可选）：分布式部署
- step1-5 运行在不同机器或容器
- step6 在聚合节点收集结果
- 适用于日期批量处理场景

---

## 实施清单

- [x] Step1 脚本创建
- [x] Step2 脚本创建
- [x] Step3 脚本创建
- [x] Step4 脚本创建
- [ ] Step5 脚本创建（Agent 进行中）
- [ ] Step6 脚本创建（Agent 进行中）
- [ ] 编排脚本创建（已完成）
- [ ] 单个 step 测试
- [ ] 端到端集成测试
- [ ] 性能基准测试

