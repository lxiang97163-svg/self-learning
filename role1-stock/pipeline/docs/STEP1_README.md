# Step 1 使用指南

对应脚本：`step1_fetch_base_data.py`

- **作用**：初始化 Tushare/相关数据源，拉取基础市场数据（指数、交易日历、股票基础等）。
- **输出**：`step1_base_data.json`（位于本目录）。

## 运行

```bash
cd /home/linuxuser/cc_file/jumpingnow_all/pipeline
python3 step1_fetch_base_data.py --trade-date 20260407
```

单独调试时可先跑 Step 1，再跑后续 Step 2–5。
