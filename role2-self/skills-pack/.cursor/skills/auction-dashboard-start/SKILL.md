---
name: auction-dashboard-start
description: 启动盯盘三 Tab 网站（竞价/复盘/预案仪表盘）。用户说「开盯盘网站」「启动 npm 仪表盘」「访问竞价监控页」「跑盘中监控网站」或含义相近时启用；在 self-learning/role1-stock/盘中监控脚本（或与 jumpingnow_all 同级结构）执行 npm start，默认端口 3456。
---

# 盯盘仪表盘：启动网站

## 做什么

在仓库内启动 Node 服务，浏览器即可访问**复盘 / 明日预案 / 竞价监控**三 Tab 页面。

## 命令（复制即用）

```bash
cd /home/linuxuser/cc_file/self-learning/role1-stock/盘中监控脚本
npm start
```

（若仍在旧仓库根下开发，路径亦可为 `jumpingnow_all/盘中监控脚本`，二者与 `pipeline/`、`outputs/` 同级时行为一致。）

- **访问地址**：http://localhost:3456  
- **端口**：默认 `3456`（可用环境变量 `PORT=其他端口 npm start` 改）

## 依赖

- 该目录已 `npm install`（有 `node_modules` 与 `express`）。若缺依赖：`cd` 同上后执行 `npm install`。

## 重启

当前终端 **Ctrl+C** 停掉后，再执行上面的 `cd` + `npm start`。

若进程在后台找不到终端：

```bash
pkill -f "node server.js"
cd /home/linuxuser/cc_file/self-learning/role1-stock/盘中监控脚本
npm start
```

## 与 Python 的关系（可选）

**竞价 Tab** 的实时数据来自 `speedcard_monitor.py` 写入的 `outputs/cache/dashboard_latest.json`。仅开网站、不看实时竞价时，只跑 `npm start` 即可；要看竞价刷新，需另开终端跑监控脚本（见该目录 `README.md`）。
