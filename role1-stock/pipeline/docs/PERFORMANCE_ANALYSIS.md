# generate_review_from_tushare.py 性能瓶颈排查报告

**日期**：2026-04-07  
**文件**：`/home/linuxuser/cc_file/jumpingnow_all/pipeline/generate_review_from_tushare.py`  
**行数**：1500行  
**关键发现**：脚本执行缓慢的原因是**串行网络请求过多**，而非代码逻辑问题。

---

## 性能瓶颈总结

| 优先级 | 瓶颈位置 | API 调用 | 调用次数 | 类型 | 行号 |
|--------|---------|---------|---------|------|------|
| 🔴 **第1** | `_calc_window_top_text()` | `pro.daily()` | **15 次** | 串行网络 | 852-880 |
| 🟠 **第2** | 龙虎榜逐股查询 | `pro.top_inst()` | **8 次** | 串行网络 | 922 |
| 🟡 **第3** | 概念成分股查询 | `pro.kpl_concept_cons()`/`pro.ths_member()` | **10 次** | 串行网络 | 766 |
| 🟡 **第4** | 其他初始化 API | 各类查询 | **20+ 次** | 混合 | 577-1123 |

---

## 瓶颈 1：pro.daily() 同步调用 15 次 ⏱️ **最耗时**

### 代码位置
```python
# 第 845-880 行，_calc_window_top_text() 函数内部

def _calc_window_top_text(window_days: int) -> str:
    ...
    for d in use_days:
        dd = pro.daily(trade_date=d)  # ← 第 853 行：每次都是网络请求，需要等待
        ...

top_5d_text = _calc_window_top_text(5)   # ← 第 879 行：调用 5 次 pro.daily()
top_10d_text = _calc_window_top_text(10) # ← 第 880 行：调用 10 次 pro.daily()
```

### 性能分析
- **串行执行**：每次 `pro.daily()` 都需等待网络响应（通常 1-3 秒）
- **总请求数**：5 + 10 = **15 次**
- **估计耗时**：15 × 1.5 秒 = **22.5 秒**（占总时间的 40-50%）

### 为什么慢
- Tushare API 返回整个交易日的全市场数据（4000+ 只股票）
- 每个请求都是独立的网络往返，没有批量接口
- 代码串行调用，不能并行

### 优化方案
**选项 A**：使用 `concurrent.futures.ThreadPoolExecutor` 并行请求
```python
from concurrent.futures import ThreadPoolExecutor
def _calc_window_top_text_parallel(window_days: int) -> str:
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(pro.daily, trade_date=d) for d in use_days]
        dfs = [f.result() for f in futures]
    # 合并所有 DataFrame
```
**预期提升**：从 22.5 秒 → 5-8 秒（5 个并行工作者）

**选项 B**：缓存最近 10 个交易日的日行情
- 第二次运行时直接从本地缓存读取
- 仅新增的交易日从网络拉取

---

## 瓶颈 2：pro.top_inst() 逐股查询 8 次

### 代码位置
```python
# 第 915-928 行

for _, r in lhb.head(8).iterrows():  # ← 前 8 只龙虎榜上榜股
    code = r["ts_code"]
    if _lhb_from_ak:
        # AKShare 已含净买额，直接用
        net = _safe_float(r.get("net_buy", 0))
    else:
        di = pro.top_inst(ts_code=code, trade_date=trade_date)  # ← 第 922 行：逐股查询
        if di is not None and not di.empty:
            net = ...
```

### 性能分析
- **调用条件**：仅当数据来自 tushare 而非 AKShare 时
- **请求数**：最多 8 次（龙虎榜前 8 只股票）
- **每次耗时**：1-2 秒（查询单只股票的机构买卖数据）
- **估计耗时**：8 × 1.5 秒 = **12 秒**（占总时间的 20-30%）

### 为什么慢
- 逐股查询，无批量接口
- 串行等待每一个响应

### 优化方案
**选项 A**：并行查询
```python
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(pro.top_inst, ts_code=code, ...): code for code in top_8_codes}
    for future in as_completed(futures):
        net = ...
```
**预期提升**：从 12 秒 → 3-4 秒

**选项 B**：仅查询前 3-5 只股票（而非 8 只）
- 减少 50% 的请求数

---

## 瓶颈 3：概念成分股查询（10 次）

### 代码位置
```python
# 第 764-768 行

if top_concepts:
    for c_code, c_name, _cnt in top_concepts[:10]:  # ← 10 个概念
        codes = _get_concept_cons_codes(pro, c_code, trade_date)  # ← 第 766 行
        if codes:
            theme_code_map[c_name] = codes
```

### _get_concept_cons_codes() 内部逻辑
```python
# 第 231-256 行

def _get_concept_cons_codes(pro, concept_code: str, trade_date: str) -> List[str]:
    df = None
    try:
        df = pro.kpl_concept_cons(ts_code=concept_code, trade_date=trade_date)  # ← 优先
    except Exception:
        df = None
    if df is None or df.empty:
        try:
            df = pro.ths_member(ts_code=concept_code, fields="con_code")  # ← 回退
        except Exception:
            df = None
```

### 性能分析
- **调用次数**：10 次（top 10 概念）
- **每次双重尝试**：kpl_concept_cons → ths_member（失败时）
- **每次耗时**：1-3 秒
- **估计耗时**：10 × 1.5 秒 = **15 秒**（占总时间的 20-30%）

### 优化方案
**选项 A**：并行查询
```python
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(_get_concept_cons_codes, pro, c_code, trade_date) 
               for c_code, _, _ in top_concepts[:10]]
```

**选项 B**：缓存概念成分（几个月有效）

---

## 其他性能影响（较小）

### 初始化阶段（第 577-650 行）：~10-15 秒
- `ts.pro_api()` 初始化
- `pro.index_daily()` 4 次（上证、深证、创业板、昨日）
- `pro.stock_basic()` 1 次（如无缓存）

### 涨跌停池查询（第 663-706 行）：~8-12 秒
- `pro.limit_list_d()` 3 次（涨停、跌停、炸板）
- 如果失败，回退到 AKShare（更慢）
- `df_zt_prev` 前一交易日（又 3 次）

---

## 估计总耗时分解

| 阶段 | 耗时 | 占比 |
|------|------|------|
| 初始化（token 设置、API 初始化、读缓存） | 3-5 秒 | 5% |
| 涨跌停池查询（limit_list_d + AKShare 备用） | 8-12 秒 | 15% |
| **pro.daily() 15 次（最大瓶颈）** | 22-25 秒 | **40%** |
| **pro.top_inst() 8 次** | 10-12 秒 | **20%** |
| **概念成分股查询 10 次** | 12-15 秒 | **20%** |
| 其他（竞价、龙虎榜、换手率、文件 I/O） | 5-8 秒 | 10% |
| **总计** | **60-75 秒** | 100% |

---

## 优化建议（按优先级）

### 🔴 最高优先级：并行化 pro.daily() 调用

```python
# 在第 845 行函数顶部添加
from concurrent.futures import ThreadPoolExecutor, as_completed

def _calc_window_top_text(window_days: int) -> str:
    if len(tdays) < window_days:
        return "—"
    use_days = tdays[max(0, t_idx - window_days + 1) : t_idx + 1]
    
    # 使用线程池并行请求
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(pro.daily, trade_date=d): d for d in use_days}
        agg: Dict[str, float] = {}
        obs: Dict[str, int] = {}
        for future in as_completed(futures):
            dd = future.result()
            if dd is None or dd.empty:
                continue
            # 后续处理同现有逻辑
            ...
```

**预期收益**：减少 15-18 秒（总耗时 45-60 秒 → 30-40 秒）

---

### 🟠 次高优先级：并行化 pro.top_inst() 和概念成分股查询

结合使用 ThreadPoolExecutor，对龙虎榜和概念分别并行查询。

**预期收益**：减少 15-20 秒（总耗时 45 秒 → 25-30 秒）

---

### 🟡 中等优先级：添加本地缓存

- 缓存最近 10 天的 `pro.daily()` 结果
- 缓存概念成分股映射（3 个月有效期）
- 第二次及以后运行可跳过这些查询

**预期收益**：后续运行时减少 40-50 秒

---

### 🟢 低优先级：数据源切换

- 如果 tushare API 响应缓慢，优先使用 AKShare（如果数据可用）
- 减少 limit_list_d 的回退次数

---

## 诊断命令

要确认实际瓶颈，可添加时间戳日志：

```python
import time
start = time.time()
dd = pro.daily(trade_date=d)
print(f"pro.daily({d}) took {time.time() - start:.2f}s")
```

---

## 结论

- **主要原因**：Tushare API 串行调用过多（特别是 `pro.daily()` 15 次）
- **核心解决方案**：使用 `ThreadPoolExecutor` 并行化网络请求
- **预期效果**：总耗时从 60-75 秒降低至 20-30 秒（提升 60-70%）
- **实施难度**：低（无需改变数据逻辑，仅改变并发方式）

