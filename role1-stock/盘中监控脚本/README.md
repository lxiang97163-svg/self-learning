# 速查早盘监控（`盘中监控脚本/speedcard_monitor.py`）

## 作用

在 **9:15～9:50** 按分钟读取当日 `outputs/review/速查_YYYY-MM-DD.md`，输出 **一行中文** 监控结论，并追加到 `outputs/logs/speedcard_monitor_YYYY-MM-DD.log`。

- **不**调用 `verify_daily` 盘后验证逻辑。
- **不**设置 `REALTIME_USE_EM_TOP10`（全市场成交额前十与本脚本无关）。

## 数据与边界

| 数据 | 来源 | 时段与限制 |
|------|------|------------|
| 个股/指数涨跌幅 | 腾讯 `qt.gtimg`（与 `realtime_engine` 一致） | 连续竞价后更接近盘口；竞价段为未连续撮合价。 |
| 概念板块名次/涨幅 | 东财 `push2(.delay) clist`，`fs=m:90+t:3` | 与行情软件「概念板块」列表同源类接口；**9:15～9:25 为竞价/盘前展示**，与收盘涨跌幅不一致，**仅作横向对比**。 |
| 竞价额、竞价涨跌幅 | `verify_daily.fetch_auction` → Tushare `stk_auction` | 需有效 token；**9:25 前**快照未定格，脚本对风标额判定多为 **fuzzy**。 |
| **昨竞价额、竞价比** | 速查文末附录表「竞价成交额(亿)」（`append_speedcard_auction_snapshot.py` 生成） | **竞价比** = 今日 `stk_auction` 成交额 ÷ 附录中的昨竞价额；附录缺失则只显示当日竞价额。 |
| 封单排行、短线侠 | — | **无稳定 HTTP API**；切换确认第 3 条在候选解析中标记为 **需人工**。 |

## 机器可读 meta（可选）

在速查 **文末** 可增加 HTML 注释（单行 JSON）覆盖默认解析：

```html
<!-- speedcard-meta: {"key_support":3871.30,"step0":{"huawei":["华为概念"],"rivals":["芯片","锂电"]}} -->
```

- `key_support`：上证关键位（覆盖正文自动提取）。
- `step0.huawei`：第零步表里「主线板块」名称关键词（用于东财板块名次）。
- `step0.rivals`：用于「是否被支线超越」的对比关键词（可选）。

`--dump-meta` 会将快照写入 `outputs/cache/speedcard_snapshot_YYYY-MM-DD.json`。

## 规则摘要（实现口径）

1. **第零步四信号**（前三个参与 A/B，第四个参与「其它题材抽血」提示）：  
   - 华为（或 meta 指定）板块名次 vs 全市场概念总数：约 **前 1/3 为 ok**，**跌出约 1/2 或** 被芯片/锂电名次超越为 **fail**，中间为 **fuzzy**。  
   - 风标竞价额 vs 正文解析的「昨日 X.XX 亿」：`≥0.7×` 偏 ok，`<0.5×` 偏 fail。  
   - 宽度票 `≥+3%` 只数：`<2` 为 fail。  
   - 池内其它票（排除第一/二优先链 + 风标）`≥+5%` 只数：`≥2` 为 fail（资金外溢）。

2. **模式**：前 3 项 **全 ok → A**；前 3 项 **≥2 个 fail → B**；其余 **FUZZY（偏空仓）**。

3. **B 候选「切换确认」**：从各候选「切换确认」小节解析 **板块名次 / 池内涨幅只数 /（油气候选）龙头竞价**；含「封单/短线侠」的条目计为 **自动化项数 −1**（通常为 **x/2** 或 **x/3**）。

4. **健康度**：A 模式下沿用速查表 **华为链 3 条**、**锂电链 3 条**，不满足时降档提示（不替代人工）。

## 命令

在 **`self-learning/role1-stock/盘中监控脚本/`** 下执行（`$WORKSPACE` 即包含 `pipeline/` 与 `outputs/` 的 `role1-stock` 根目录）：

```bash
cd "$WORKSPACE/盘中监控脚本"
python3 speedcard_monitor.py
python3 speedcard_monitor.py --once --card "/path/to/速查_YYYY-MM-DD.md"
python3 speedcard_monitor.py --once --dump-meta
```

## 与 `pipeline/realtime_engine.py` 的关系

- 共用上级目录 `pipeline/` 中的 `parse_card` / `fetch_stocks` / `get_indices`。
- 与本目录 **`speedcard_data.py`** 同包（东财板块 + meta 合并 + 关键位辅助解析）。
