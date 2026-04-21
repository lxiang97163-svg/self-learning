# Step 2 使用指南

对应脚本：`step2_fetch_limits.py`

- **作用**：涨跌停、概念、龙虎榜等与涨跌停相关的数据。
- **输出**：`step2_limits_data.json`（位于本目录）。

## 运行

```bash
cd /home/linuxuser/cc_file/jumpingnow_all/pipeline
python3 step2_fetch_limits.py --trade-date 20260407
```

与 Step 1 无顺序依赖时，可与 Step 1/3/4/5 由编排脚本并行执行。
