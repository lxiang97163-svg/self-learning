---
name: jumping-daily-ops
description: Jumping VPN 网站每日运维检查。当用户说"帮我检查网站"、"做每日检查"、"健康检查"、"服务状态"、"检查备份"时触发。执行 Docker 容器状态、网站可访问性、数据库连接、SSL 证书、磁盘空间、备份文件的全面检查，并输出结构化报告。
---

# Jumping 每日运维检查

## 检查流程

依次执行以下 5 个步骤，每步用 Shell 工具运行命令，收集结果后统一输出报告。

### Step 1：Docker 容器状态

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}" | grep -E "xboard|NAME"
```

预期：所有容器状态为 `Up`。若有 `Exited` 或 `Restarting` 立即标记为 ❌。

### Step 2：网站可访问性

```bash
curl -sL -o /dev/null -w "落地页: %{http_code} | 耗时: %{time_total}s\n" --max-time 10 https://jumpingnow.com
curl -sL -o /dev/null -w "API:   %{http_code} | 耗时: %{time_total}s\n" --max-time 10 -X POST https://jumpingnow.com/api/v1/passport/comm/pv
```

预期：落地页 200，API 200/422/429 均为正常。

### Step 3：数据库连接 + 用户数

```bash
docker exec xboard-db sh -c "mysql --default-character-set=utf8mb4 -uxboard -pxboard_pass_2024 xboard -e 'SELECT COUNT(*) as 用户总数 FROM v2_user; SELECT COUNT(*) as 活跃订阅 FROM v2_user WHERE expired_at > UNIX_TIMESTAMP();' 2>/dev/null"
```

预期：返回数字，无报错。

### Step 4：SSL 证书有效期

```bash
echo | openssl s_client -connect jumpingnow.com:443 -servername jumpingnow.com 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null
```

判断：
- 剩余 > 30 天：✅
- 剩余 8–30 天：⚠️ 提醒续期
- 剩余 ≤ 7 天：❌ 立即续期

### Step 5：备份文件 + 磁盘空间

```bash
echo "=== 最近备份 ===" && ls -lht /opt/Xboard/ops/backups/*.sql.gz 2>/dev/null | head -5 || echo "无备份文件"
echo "=== 磁盘使用 ===" && df -h /opt | tail -1
echo "=== 日志大小 ===" && du -sh /opt/Xboard/storage/logs/ 2>/dev/null
```

判断：
- 今日备份存在且 > 1MB：✅
- 磁盘使用 < 80%：✅，80–90%：⚠️，> 90%：❌

---

## 输出报告格式

检查完成后，用以下格式输出：

```
## Jumping 每日健康报告 · YYYY-MM-DD HH:MM

| 检查项       | 状态 | 详情                    |
|------------|------|-------------------------|
| Docker 容器  | ✅   | 6/6 运行中               |
| 落地页访问   | ✅   | HTTP 200, 0.45s          |
| API 访问    | ✅   | HTTP 200, 0.12s          |
| 数据库      | ✅   | 用户 42 / 活跃订阅 18     |
| SSL 证书    | ✅   | 剩余 67 天               |
| 今日备份    | ✅   | 8.2MB, 03:00 完成        |
| 磁盘空间    | ✅   | 34% 已用 (12G/35G)       |

### 需要关注
（无异常时写"一切正常"；有问题时列出并给出处理建议）
```

---

## 异常处理指引

| 异常 | 快速处理命令 |
|------|-------------|
| 容器 Exited | `cd /opt/Xboard && docker compose up -d <服务名>` |
| 网站 502/504 | `docker logs xboard-web-1 --tail 30` 查原因 |
| 数据库连接失败 | `docker logs xboard-db --tail 20` |
| 无今日备份 | `bash /opt/Xboard/ops/backup.sh` 手动触发 |
| 磁盘 > 90% | `docker exec xboard-web-1 php /www/artisan reset:log` 清日志 |
| SSL ≤ 7 天 | `certbot renew && docker exec xboard-nginx nginx -s reload` |

---

## 项目关键路径（备查）

| 资源 | 路径 |
|------|------|
| 落地页 | `/opt/Xboard/landing/index.html` |
| 主题样式 | `/opt/Xboard/theme/Xboard/jumping.css` |
| 仪表盘脚本 | `/opt/Xboard/theme/Xboard/theme-dashboard-modules.js` |
| nginx 配置 | `/opt/Xboard/nginx.conf` |
| 备份目录 | `/opt/Xboard/ops/backups/` |
| 应用日志 | `/opt/Xboard/storage/logs/laravel.log` |
| 手动备份 | `bash /opt/Xboard/ops/backup.sh` |
| 完整健康检查 | `bash /opt/Xboard/ops/health-check.sh` |
