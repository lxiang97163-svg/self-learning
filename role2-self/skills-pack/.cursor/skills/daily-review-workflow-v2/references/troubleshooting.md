# 故障与维护

## 韭研 Cookie

1. 登录 https://www.jiuyangongshe.com  
2. F12 → Network → 打开或刷新 `https://www.jiuyangongshe.com/action`  
3. 请求头中复制 `Cookie:`（整段或 `SESSION=...`）  
4. 写入 `pipeline/fetch_jiuyan_daily.py` 内 `COOKIE = "SESSION=..."`（约第 16 行）

## 常见错误与处理

| 现象 | 处理 |
|------|------|
| tushare 脚本报错 | 该日期可能为非交易日，改用最近交易日 |
| tushare Token 失效 | 检查脚本中 `TOKEN` 和 `TOKEN_MIN` |
| 韭研脚本报错（Cookie 过期） | 按上文更新 `COOKIE` |
| 韭研脚本报错（Node.js 未找到） | 安装 Node.js，`node --version` 验证 |
| 复盘表多字段为「—」 | 执行手册注明数据不足，建议补数据后再决策 |
| PDF 转换「未找到 Edge」 | 安装 Microsoft Edge，路径常见为 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
