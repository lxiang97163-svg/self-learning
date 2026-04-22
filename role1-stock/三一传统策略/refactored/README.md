# 三一传统策略 · 重构版 (refactored/)

工程化重构后的 5 个短线策略脚本，去除硬编码 token，抽出共享模块，落地知识库的情绪节点 / 陷阱过滤 / reason_tag。

> 本目录所有输出仅作**研究参考，不构成投资建议**。

## 1. 目录结构

```
refactored/
├── common/
│   ├── config.py              # 读取 config.local.json / env
│   ├── trading_calendar.py    # 今/昨/前日 + 过去 N 日
│   ├── auction.py             # 竞价拉取 + 9:28 完整性等待
│   ├── stock_pool.py          # 股票池 & 流通市值映射
│   ├── sentiment.py           # 情绪节点判断
│   ├── filters.py             # 陷阱过滤 + 仓位权重
│   ├── notifier.py            # PushPlus + --no-push/--output-file
│   └── reason_tag.py          # 推荐股挂短标签
├── strategies/
│   ├── jingjia_31_duanban.py        # 原: 竞价三一_断板弱转强.py
│   ├── tidui_baoliang_yihong.py     # 原: 一红+爆量.py
│   ├── danhe_daidui.py              # 原: 单核带队.py
│   ├── sector_scan_9431.py          # 原: 9431.py (并发化 + --quick)
│   ├── tidui_fupan.py               # 原: 梯队复盘.py
│   └── run_all.py                   # 一键顺序/并行执行
├── config.example.json
├── .gitignore
└── README.md
```

## 2. 老脚本 → 新脚本对照

| 老脚本 | 新脚本 | 新增的标签 / 过滤 |
|--------|--------|-------------------|
| `竞价三一_断板弱转强.py` | `strategies/jingjia_31_duanban.py` | 情绪节点告警、断板次日强制空仓 banner、每条推荐挂 `reason_tag`、小盘陷阱标签 |
| `一红+爆量.py` | `strategies/tidui_baoliang_yihong.py` | 同上 (reason_tag + 断板次日告警 + 小盘陷阱) |
| `单核带队.py` | `strategies/danhe_daidui.py` | Cookie 走 config；Selenium 失败优雅回退 md |
| `9431.py` | `strategies/sector_scan_9431.py` | 12 worker 并发、JSON 日缓存、`--quick` 剪裁到含涨停股的概念 |
| `梯队复盘.py` | `strategies/tidui_fupan.py` | token/推送走 config；`--output-excel` 可配置路径 |
| —（新增）— | `strategies/run_all.py` | 一键串行/并行, 支持统一 `--no-push --output-dir` |

## 3. 配置 `config.local.json`

把 `config.example.json` 复制成 `config.local.json` 填写：

| 字段 | 必填 | 说明 |
|------|------|------|
| `tushare_token` | ✅ | chinadata (ca_data) 日级 API token |
| `tushare_min_token` | ✅ | chinamindata (min) 分钟级 API token |
| `pushplus_token` | ⭕ | 空则自动跳过推送 |
| `dxx_cookies.PHPSESSID` | ⭕ | 单核带队 Selenium 抓取所需；缺失时回退 md |
| `dxx_cookies.server_name_session` | ⭕ | 同上 |
| `enable_push` | ⭕ | 全局推送开关, 默认 `true` |

也可以走环境变量：

```
TUSHARE_TOKEN, TUSHARE_MIN_TOKEN, PUSHPLUS_TOKEN,
DXX_PHPSESSID, DXX_SERVER_NAME_SESSION
```

两者都没配置时 `load_config()` 会抛 `RuntimeError` 并给出提示。

## 4. 依赖

原脚本所需依赖保持不变 (`chinadata`, `chinamindata`, `pandas`, `requests`, `selenium`, `openpyxl`)。

## 5. CLI 参数

所有策略脚本都支持：

```
--no-push            不推送（仍会 stdout 打印）
--output-file PATH   仅写文件，不推送不打印
```

扩展：

```
# sector_scan_9431.py
--quick              仅扫描昨日含涨停股的概念 (加速)
--workers N          并行 worker 数 (默认 12)
--no-cache           忽略当日 JSON 缓存

# tidui_fupan.py
--output-excel PATH  指定 xlsx 输出路径

# run_all.py
--parallel                 并行执行所有子脚本
--only <name1> <name2>     仅运行指定脚本 (见 STRATEGY_ORDER)
--output-dir DIR           统一落盘 <DIR>/<name>.txt
```

## 6. Reason Tag 示例与含义

每条推荐下 `🏷` 一行由 `common/reason_tag.py` 生成，`+` 分隔。示例：

```
🏷 题材启动期+断板混合+在储能(+2.30%)+板内涨停4只+流通25.3亿+rank8+因储能
🏷 题材退潮期+市场三一+流通18.2亿+rank120+⚠️小盘陷阱
🏷 题材断板次日期+首板三一+流通35.1亿+rank42+⚠️断板次日
```

| 片段 | 含义 |
|------|------|
| `题材X期` | 情绪节点：启动/上升/高潮/分歧/退潮/断板次日/混沌 |
| 分类 | `断板混合/首板三一/二板三一/高度板三一/弱转强三一/市场三一/...` |
| `在<题材>(pct)` | 所属板块 + 今日板块加权高开 |
| `板内涨停X只` | 板块内昨日涨停个数 |
| `流通X亿` | 流通市值 |
| `rankN` | 人气榜 rank (无则省略) |
| `因<原因>` | KPL 最近一次 lu_desc |
| `⚠️小盘陷阱` | 流通<20亿 且 换手>20% |
| `⚠️断板次日` | 铁律1：前日最高板断板，情绪=0 |

## 7. 铁律落地

* **铁律1 — 断板次日=强制空仓**：`common/sentiment.py::judge_emotion_node` 识别“断板次日”节点；`jingjia_31_duanban` / `tidui_baoliang_yihong` 会在报告顶端插入红色告警 `⚠️ 今日情绪=0分, 铁律强制空仓，以下仅作研究`。
* **铁律2 — 越涨越不加仓**：`filters.weight_by_node` 对“高潮/分歧”降权到 0.3-0.4，不代用户下单，仅在 reason_tag 暴露。
* **铁律3 — 趋势票建仓次日无利润电=认错**：保留给策略层，当前版本未动原始建仓/止损逻辑。

## 8. 自测

每个 common 模块都含 `if __name__ == "__main__": ...`，可单独运行做冒烟：

```
python -m common.config
python -m common.trading_calendar
python -m common.auction
python -m common.stock_pool
python -m common.sentiment
python -m common.filters
python -m common.reason_tag
```

> 需要 tushare 接口可用并在交易日跑。

## 9. 关于“危险三一”

`filters.is_small_cap_trap(circ_mv, turnover)` 默认阈值：流通市值 < 20 亿 **且** 竞价换手率 > 20%。

符合条件的股票**不会被删除**，仍出现在今日推荐中，但在 `reason_tag` 和 flags 上挂 `⚠️小盘陷阱`，让你知情。

## 10. 安全说明

* `config.local.json` 已列入 `.gitignore`，不要提交到版本库。
* `jjlive_data/` 缓存目录也已忽略，避免把 cookie 缓存和中间 JSON 推到远端。
