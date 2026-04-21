# generate_review_from_tushare.py 优化方案

## 第一阶段：ThreadPoolExecutor 并行化（已实施）

### P0 优化：pro.daily() 15 次并行
- **位置**：第 846-878 行，_calc_window_top_text() 函数
- **修改**：用 ThreadPoolExecutor(max_workers=5) 并行化串行循环
- **预期收益**：7-15秒 → 1-3秒

### P1 优化：概念成分股查询 10 次并行
- **位置**：第 764-776 行，theme_code_map 构建
- **修改**：用 ThreadPoolExecutor(max_workers=5) 并行化串行循环
- **预期收益**：15-35秒 → 3-7秒

**测试状态**：运行中...

---

## 第二阶段（备选）：文件拆分 + 多 Agent 方案

如果并行函数效果不理想（仍需 > 40 秒），启动文件拆分方案。

### 架构设计

```
step1_fetch_base_data.py      （负责初始化和基础数据拉取）
├─ token 初始化
├─ pro.stock_basic() 缓存读取/更新
├─ pro.index_daily() 历史 50 天
└─ 输出：base_data.json（cache_data）

step2_fetch_limits.py          （涨跌停池、龙虎榜、概念）
├─ pro.limit_list_d() 涨停池（今日+昨日）
├─ pro.kpl_list() 竞价排行
├─ pro.limit_cpt_list() 概念涨停
├─ pro.top_list() 龙虎榜
└─ 输出：limits_data.json

step3_fetch_fundamentals.py    （日行情、成分、机构）
├─ pro.daily() 5日+10日（当前：15次，使用ThreadExecutor）
├─ pro.concept_cons() 10个概念（当前：10次，使用ThreadExecutor）
├─ pro.top_inst() 龙虎榜前8只（当前：8次）
├─ pro.daily_basic() 换手率
└─ 输出：fundamentals_data.json

step4_fetch_auction.py         （竞价成交）
├─ pro_min.stk_auction() 竞价成交
└─ 输出：auction_data.json

step5_fetch_rotation.py        （近5日题材热力）
├─ _build_rotation_section() 历史概念查询
└─ 输出：rotation_data.json

step6_merge_and_render.py      （合并 + 模板渲染）
├─ 加载 5 个 json 文件
├─ 合并为统一的 dict
├─ 填入 markdown 模板
└─ 写入 outputs/每日复盘表_YYYY-MM-DD.md
```

### 并行执行流程

```
当前（串行）：step1 → step2 → step3 → step4 → step5 → step6
总耗时：60-75秒

改进（并行）：
step1    ┐
step2    ├─→ step6（合并 + 渲染）
step3    │
step4    │
step5    ┘
总耗时：max(15, 20, 30, 5, 20) + 5 = ~35秒
```

### 实施步骤

1. **拆分代码**：提取各 step 的逻辑到独立文件
2. **参数化**：各 step 接受 trade_date 参数，输出 JSON
3. **错误隔离**：各 step 独立运行，失败不影响其他
4. **并行执行**：启动 5 个 Process（ProcessPoolExecutor）
5. **结果合并**：step6 加载所有 JSON，填充模板

### Agent 并行执行示例

```python
# orchestrate_parallel_fetch.py
from concurrent.futures import ProcessPoolExecutor
import json

def fetch_step(step_name, trade_date):
    """导入并执行指定的 step 模块"""
    module = __import__(f'step{step_name[4:]}_*.py')
    return module.fetch(trade_date)

with ProcessPoolExecutor(max_workers=5) as executor:
    futures = {
        executor.submit(fetch_step, f'step{i}', trade_date): f'step{i}_data'
        for i in range(1, 6)
    }
    results = {}
    for future in as_completed(futures):
        key = futures[future]
        results[key] = future.result()

# 合并
render_final_report(results)
```

---

## 性能对比

| 方案 | P0 | P1 | P2 | P3 | P4 | P5 | P6 | 总耗时 | 收益 |
|------|----|----|----|----|----|----|----|----|------|
| **原始** | 7-15s | 15-35s | 8-12s | 8-12s | 5s | 20s | 5s | **60-75s** | — |
| **ThreadPool（当前）** | 1-3s | 3-7s | 8-12s | 8-12s | 5s | 20s | 5s | **30-40s** | ✅ **50-60%** |
| **文件拆分并行** | 5-8s | 5-10s | 10-15s | 3-5s | 8-12s | 20s | 5s | **20-35s** | ✅✅ **60-70%** |

---

## 何时启动第二阶段

如果 ThreadPool 优化后仍 > 40 秒，启动文件拆分方案。

**检查指标**：
- 脚本总耗时是否降低 50% 以上（从 60-75秒 → 30-40秒以下）
- 单次执行是否稳定

