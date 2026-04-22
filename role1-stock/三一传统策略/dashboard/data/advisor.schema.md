# advisor.json · Schema 说明

> 盘中盯盘操作指引消息流。由 `advisor.py` 规则引擎 + `server.py /append-note` 写入。

## 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `updated_at` | ISO8601 string | 最后更新时间 |
| `messages[]` | array | 消息列表，**最新在前**，最多 20 条 |
| `messages[].ts` | ISO8601 string | 消息产生时间 |
| `messages[].type` | string | 消息类型：`rule` / `user` / `system` |
| `messages[].level` | string | 等级：`info` / `warn` / `critical` |
| `messages[].text` | string | 消息正文（已替换模板变量） |

## 消息类型说明

| type | 含义 | 示例 |
|------|------|------|
| `rule` | `advisor.py` 规则命中 | 「XX 题材分歧，空仓/不接力」 |
| `user` | 用户手动敲入的备注 | 「龙一反包，盯住尾盘」 |
| `system` | 系统消息（启动/错误/数据缺失） | 「data/auction.json 缺失」 |

## 等级 level 用途

- `info`：绿色/蓝色标签，正常提示
- `warn`：黄色，需要注意但不强制
- `critical`：红色，涉及铁律或清仓级别

## 写入规则

- 新消息**头插**（`messages.insert(0, msg)`）
- 超过 20 条截断尾部
- 同 `type` + `text` 在 5 分钟内的重复消息去重（advisor.py 规则消息）
- 用户 `user` 消息不参与去重
