---
name: add-xboard-node
description: 为 Xboard 面板端到端配置节点，支持 Hysteria2 和 VLESS+Reality 两种协议。包括 DNS 解析、TLS 证书申请、Xboard 后台注册节点、独立 sing-box/xray 服务配置、用户同步脚本、连通性验证全流程。当用户提供"协议类型、节点名称、子域名、服务器IP"时触发。
---

# 新增 Xboard 节点（Hysteria2 / VLESS+Reality）

## 环境信息

- Xboard 地址：`https://jumpingnow.com`
- 通讯密钥：`jiiZt9n8YonJS0SIEmNp2ip6WqYTJ`
- 节点域名后缀：`amxyao.uk`
- Cloudflare API Token：`cfut_MlUdGmHAXKoCoq131ASOfDeCjRtwtTbh0iGL1hIc59abc835`
- 权限组 ID：`1`（基础版）
- Xboard 目录：`/opt/Xboard`
- 证书目录：`/etc/V2bX/cert/`

## 已有节点机器

| 机器 | IP | SSH 密码 | 现有节点 |
|------|----|----------|----------|
| 韩国 | `158.247.220.253` | `J.z8a)2YhtCUdPX6` | 节点1（Hy2）、节点2（VLESS）、节点3（VMess） |
| 日本 | `45.76.219.250` | `p3V-(kFm]upvK3h?` | 节点6（Hy2）、节点7（VMess）、节点8（VLESS） |

**用户同步**：两台机器均已部署 `/usr/local/bin/sync-all.py`，每分钟自动从面板同步用户。
新加节点只需在对应机器的 `/etc/xboard-sync/nodes.json` 追加一条记录。

## 架构说明

**不使用 V2bX 运行协议服务**（V2bX 对 Hysteria2 和 Reality 的配置翻译有 bug）。

| 协议 | 服务端 | 用户同步 |
|------|--------|----------|
| Hysteria2 | 独立 sing-box（systemd 服务） | 定时脚本从 Xboard API 同步 |
| VLESS+Reality | 独立 xray（systemd 服务） | 定时脚本从 Xboard API 同步 |

每个节点对应一个独立的 systemd 服务和用户同步脚本。

---

## 执行流程

### 第一步：确认输入信息

需要以下五项：
- **协议类型**：`hysteria2` 或 `vless-reality`
- **节点名称**：如"日本-01"
- **子域名前缀**：如"jp01"（完整域名 = `jp01.amxyao.uk`）
- **服务器 IP**：如"1.2.3.4"
- **SSH 密码**：节点机器的 root 密码（韩国 158.247.220.253 / 日本 45.76.219.250 已知，新机器需提供）

---

### 第二步：Cloudflare DNS 解析

```bash
ZONE_ID=$(curl -s "https://api.cloudflare.com/client/v4/zones?name=amxyao.uk" \
  -H "Authorization: Bearer cfut_MlUdGmHAXKoCoq131ASOfDeCjRtwtTbh0iGL1hIc59abc835" \
  -H "Content-Type: application/json" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'][0]['id'])")

curl -s -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
  -H "Authorization: Bearer cfut_MlUdGmHAXKoCoq131ASOfDeCjRtwtTbh0iGL1hIc59abc835" \
  -H "Content-Type: application/json" \
  --data '{"type":"A","name":"子域名前缀","content":"服务器IP","ttl":1,"proxied":false}'
```

验证解析生效（等待 DNS 传播）：
```bash
dig +short 子域名.amxyao.uk
```

---

### 第三步：申请 TLS 证书

**仅 Hysteria2 需要**。VLESS+Reality 不需要 TLS 证书（使用 Reality 自带的伪装机制）。

```bash
export CF_Token="cfut_MlUdGmHAXKoCoq131ASOfDeCjRtwtTbh0iGL1hIc59abc835"
~/.acme.sh/acme.sh --issue --dns dns_cf -d 子域名.amxyao.uk --keylength ec-256

mkdir -p /etc/V2bX/cert/子域名
~/.acme.sh/acme.sh --install-cert -d 子域名.amxyao.uk --ecc \
  --cert-file /etc/V2bX/cert/子域名/cert.pem \
  --key-file /etc/V2bX/cert/子域名/key.pem \
  --fullchain-file /etc/V2bX/cert/子域名/fullchain.pem
```

---

### 第四步：在 Xboard 后台创建节点

#### Hysteria2 节点

```bash
docker exec -i xboard-web-1 php artisan tinker --no-interaction << 'EOF'
$server = new \App\Models\Server();
$server->type = 'hysteria';
$server->name = '节点名称';
$server->host = '子域名.amxyao.uk';
$server->port = '443';
$server->server_port = 443;
$server->show = true;
$server->group_ids = [1];
$server->route_ids = [];
$server->tags = [];
$server->rate = '1.00';
$server->rate_time_enable = false;
$server->rate_time_ranges = [];
$server->protocol_settings = [
    'version' => 2,
    'bandwidth' => ['up' => 1000, 'down' => 1000],
    'obfs' => ['open' => false, 'type' => 'salamander', 'password' => null],
    'tls' => ['server_name' => '子域名.amxyao.uk', 'allow_insecure' => false],
    'hop_interval' => null
];
$server->save();
echo 'Node ID: ' . $server->id . "\n";
EOF
```

#### VLESS+Reality 节点

先生成 X25519 密钥对和 UUID：
```bash
# 生成 UUID
python3 -c "import uuid; print(uuid.uuid4())"

# 生成 X25519 密钥对（用已有的 xray）
/usr/local/bin/xray x25519
# 输出：
# Private key: <私钥>
# Public key: <公钥>

# 生成 ShortId（8位随机hex）
python3 -c "import secrets; print(secrets.token_hex(4))"
```

**重要**：Reality 私钥必须存入 Xboard 数据库，否则 V2bX/xray 从 API 拿到的 private_key 为 null。

```bash
docker exec -i xboard-web-1 php artisan tinker --no-interaction << 'EOF'
$server = new \App\Models\Server();
$server->type = 'vless';
$server->name = '节点名称';
$server->host = '服务器IP';
$server->port = '8443';
$server->server_port = 8443;
$server->show = true;
$server->group_ids = [1];
$server->route_ids = [];
$server->tags = [];
$server->rate = '1.00';
$server->rate_time_enable = false;
$server->rate_time_ranges = [];
$server->protocol_settings = [
    'tls' => 2,
    'tls_settings' => null,
    'flow' => 'xtls-rprx-vision',
    'network' => 'tcp',
    'network_settings' => [],
    'reality_settings' => [
        'allow_insecure' => false,
        'server_port' => null,
        'server_name' => 'www.lovelive-anime.jp',
        'public_key' => '生成的公钥',
        'private_key' => '生成的私钥',
        'short_id' => '生成的ShortId'
    ]
];
$server->save();
echo 'Node ID: ' . $server->id . "\n";
EOF
```

**伪装目标选择原则**：必须选纯 IPv4 的域名（无 AAAA 记录），否则服务器 IPv6 出口不通时 Reality 握手会超时。
已验证可用：`www.lovelive-anime.jp`

验证方法：
```bash
dig +short AAAA 候选域名  # 输出为空才可用
curl -4 -sv --connect-timeout 5 https://候选域名 2>&1 | grep "Connected"
```

---

### 第五步：配置独立服务端

#### Hysteria2 —— 独立 sing-box

确认 sing-box 已安装：
```bash
which sing-box || (cd /tmp && wget -q "https://github.com/SagerNet/sing-box/releases/download/v1.10.7/sing-box-1.10.7-linux-amd64.tar.gz" -O sb.tar.gz && tar xzf sb.tar.gz && cp sing-box-1.10.7-linux-amd64/sing-box /usr/local/bin/sing-box)
```

获取当前用户列表并生成配置：
```bash
# 从 Xboard API 获取用户列表
USERS=$(curl -s "https://jumpingnow.com/api/v1/server/UniProxy/user?node_id=NODE_ID&node_type=hysteria&token=jiiZt9n8YonJS0SIEmNp2ip6WqYTJ")
echo $USERS | python3 -m json.tool
```

创建 sing-box 配置（`/etc/sing-box/hy2-NODE_ID.json`）：
```json
{
  "log": {"level": "warning", "timestamp": true},
  "inbounds": [
    {
      "type": "hysteria2",
      "tag": "hy2-NODE_ID",
      "listen": "0.0.0.0",
      "listen_port": 443,
      "users": [
        {"password": "用户UUID"}
      ],
      "masquerade": "https://子域名.amxyao.uk",
      "tls": {
        "enabled": true,
        "server_name": "子域名.amxyao.uk",
        "certificate_path": "/etc/V2bX/cert/子域名/fullchain.pem",
        "key_path": "/etc/V2bX/cert/子域名/key.pem"
      }
    }
  ],
  "outbounds": [{"type": "direct", "tag": "direct"}]
}
```

创建 systemd 服务（`/etc/systemd/system/sing-box-hy2-NODE_ID.service`）：
```ini
[Unit]
Description=sing-box Hysteria2 Node NODE_ID
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/hy2-NODE_ID.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable sing-box-hy2-NODE_ID
systemctl start sing-box-hy2-NODE_ID
```

#### VLESS+Reality —— 独立 xray

确认 xray 已安装：`which xray`（通常在 `/usr/local/bin/xray`）

创建 xray 配置（`/etc/xray/vless-reality-NODE_ID.json`）：
```json
{
  "log": {"loglevel": "warning"},
  "inbounds": [
    {
      "port": 8443,
      "listen": "0.0.0.0",
      "protocol": "vless",
      "settings": {
        "clients": [
          {"id": "用户UUID", "flow": "xtls-rprx-vision"}
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "www.lovelive-anime.jp:443",
          "xver": 0,
          "serverNames": ["www.lovelive-anime.jp"],
          "privateKey": "生成的私钥",
          "shortIds": ["生成的ShortId"]
        }
      }
    }
  ],
  "outbounds": [{"protocol": "freedom"}]
}
```

创建 systemd 服务（`/etc/systemd/system/xray-vless-NODE_ID.service`）：
```ini
[Unit]
Description=Xray VLESS+Reality Node NODE_ID
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/xray run -c /etc/xray/vless-reality-NODE_ID.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable xray-vless-NODE_ID
systemctl start xray-vless-NODE_ID
```

---

### 第六步：注册到通用用户同步系统

两台节点机上已部署统一的 `sync-all.py`，每分钟自动从面板拉取用户、有变化才 reload 服务。
**新加节点只需在对应机器的配置文件里加一条记录，无需再写新脚本。**

#### 配置文件位置
```
/etc/xboard-sync/nodes.json
```

#### Hysteria2 节点 —— 在目标机器上执行

```bash
# 读取现有配置，追加新节点
python3 << PYEOF
import json
path = "/etc/xboard-sync/nodes.json"
with open(path) as f:
    nodes = json.load(f)
nodes.append({
    "node_id": NODE_ID,
    "node_type": "hysteria",
    "config_file": "/etc/sing-box/hy2-NODE_ID.json",
    "service": "sing-box-hy2-NODE_ID.service",
    "users_path": "inbounds.0.users",
    "user_format": "hy2"
})
with open(path, "w") as f:
    json.dump(nodes, f, indent=2)
print("done")
PYEOF

# 立即同步一次验证
python3 /usr/local/bin/sync-all.py
```

#### VLESS+Reality 节点 —— 在目标机器上执行

```bash
python3 << PYEOF
import json
path = "/etc/xboard-sync/nodes.json"
with open(path) as f:
    nodes = json.load(f)
nodes.append({
    "node_id": NODE_ID,
    "node_type": "vless",
    "config_file": "/etc/xray/vless-reality-NODE_ID.json",
    "service": "xray-vless-NODE_ID.service",
    "users_path": "inbounds.0.settings.clients",
    "user_format": "vless"
})
with open(path, "w") as f:
    json.dump(nodes, f, indent=2)
print("done")
PYEOF

python3 /usr/local/bin/sync-all.py
```

#### VMess 节点（如有）

```bash
python3 << PYEOF
import json
path = "/etc/xboard-sync/nodes.json"
with open(path) as f:
    nodes = json.load(f)
nodes.append({
    "node_id": NODE_ID,
    "node_type": "vmess",
    "config_file": "/etc/xray/vmess-NODE_ID.json",
    "service": "xray-vmess-NODE_ID.service",
    "users_path": "inbounds.0.settings.clients",
    "user_format": "vmess"
})
with open(path, "w") as f:
    json.dump(nodes, f, indent=2)
print("done")
PYEOF

python3 /usr/local/bin/sync-all.py
```

#### 验证同步正常

```bash
tail -5 /var/log/sync-all.log
# 应出现：node NODE_ID (协议): no change (N users)
# 或：    node NODE_ID (协议): updated X -> Y users
```

> **说明**：`sync-all.py` 已通过 crontab 每分钟运行，无需额外操作。
> 日志：`/var/log/sync-all.log`
> 配置：`/etc/xboard-sync/nodes.json`（支持 hy2 / vless / vmess / trojan / ss 格式）

---

### 第七步：配置流量 push 脚本（必须，否则面板流量永远为 0）

**原理**：节点必须定期把各用户的流量增量 POST 给面板，面板才能统计已用流量。只拉用户不 push 流量，面板显示 0 B 已用。

#### xray 节点（vmess / vless）—— stats API 方案

**第一，在 xray 配置文件里加入 stats 相关字段**（选一个未占用端口，如 10089）：

```json
{
  "stats": {},
  "policy": {
    "levels": {"0": {"statsUserUplink": true, "statsUserDownlink": true}},
    "system": {"statsInboundUplink": true, "statsInboundDownlink": true}
  },
  "api": {"tag": "api", "services": ["StatsService"]},
  "inbounds": [
    {
      "listen": "127.0.0.1", "port": 10089,
      "protocol": "dokodemo-door",
      "settings": {"address": "127.0.0.1"}, "tag": "api"
    }
    // ... 原有 inbound ...
  ],
  "routing": {
    "rules": [
      {"inboundTag": ["api"], "outboundTag": "api", "type": "field"}
      // ... 原有 rules ...
    ]
  }
}
```

重启服务后验证 API 端口在监听：
```bash
systemctl restart xray-vless-NODE_ID  # 或 xray-vmess-NODE_ID
ss -tlnp | grep 10089
xray api statsquery --server=127.0.0.1:10089 --pattern='' | head -5
```

**第二，创建 push 脚本** `/usr/local/bin/push-traffic-NODE_ID.sh`：

```bash
#!/bin/bash
NODE_ID=NODE_ID; NODE_TYPE=vless  # 或 vmess
API_HOST=https://jumpingnow.com; API_KEY=jiiZt9n8YonJS0SIEmNp2ip6WqYTJ
XRAY_API=127.0.0.1:10089; STATE_FILE=/var/run/xray-traffic-nodeNODE_ID.json

USERS_JSON=$(curl -s "${API_HOST}/api/v1/server/UniProxy/user?node_id=${NODE_ID}&node_type=${NODE_TYPE}&token=${API_KEY}")
[ -z "$USERS_JSON" ] && exit 1

python3 << PYEOF
import json, subprocess, os
users = json.loads('''$USERS_JSON''').get("users", [])
uuid_to_id = {u["uuid"]: u["id"] for u in users}
state_file = "$STATE_FILE"
prev = {}
if os.path.exists(state_file):
    try:
        with open(state_file) as f: prev = json.load(f)
    except: pass
traffic = {}; curr_state = {}
for uuid, uid in uuid_to_id.items():
    up_total = down_total = 0
    for direction, key in [("up","uplink"),("down","downlink")]:
        try:
            r = subprocess.run(["/usr/local/bin/xray","api","statsquery","--server=$XRAY_API",f"--pattern=user>>>{uuid}>>>traffic>>>{key}"],capture_output=True,text=True,timeout=5)
            for line in r.stdout.splitlines():
                if '"value"' in line:
                    val = int(line.split(":")[1].strip().rstrip(",").strip('"'))
                    if direction=="up": up_total=val
                    else: down_total=val
        except: pass
    curr_state[uuid] = {"up": up_total, "down": down_total}
    delta_up = max(0, up_total - prev.get(uuid,{}).get("up",0))
    delta_down = max(0, down_total - prev.get(uuid,{}).get("down",0))
    if delta_up > 0 or delta_down > 0:
        traffic[str(uid)] = [delta_up, delta_down]
with open(state_file,"w") as f: json.dump(curr_state,f)
if traffic:
    import urllib.request
    url = "$API_HOST/api/v1/server/UniProxy/push?node_id=$NODE_ID&node_type=$NODE_TYPE&token=$API_KEY"
    req = urllib.request.Request(url, data=json.dumps(traffic).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f"push ok: {traffic}")
    except Exception as e: print(f"push error: {e}")
else: print("no delta")
PYEOF
```

#### sing-box 节点（hysteria2）—— 日志解析方案

**⚠️ 重要**：sing-box 官方 release（包括 apt 源）均不含 `with_v2ray_api`，在配置里加 `experimental.v2ray_api` 会导致服务启动失败并循环重启。**不要用 v2ray_api 或 clash_api 方案**。

**第一，在 sing-box 配置里开启 info 日志到文件**：

```json
"log": {"level": "info", "timestamp": true, "output": "/var/log/sing-box-hy2-NODE_ID.log"}
```

重启服务：`systemctl restart sing-box-hy2-NODE_ID`

**第二，创建 push 脚本** `/usr/local/bin/push-traffic-NODE_ID.sh`：

```bash
#!/bin/bash
NODE_ID=NODE_ID; NODE_TYPE=hysteria
API_HOST=https://jumpingnow.com; API_KEY=jiiZt9n8YonJS0SIEmNp2ip6WqYTJ
LOG_FILE=/var/log/sing-box-hy2-NODE_ID.log
STATE_FILE=/var/run/sb-hy2-nodeNODE_ID-pos.txt

USERS_JSON=$(curl -s "${API_HOST}/api/v1/server/UniProxy/user?node_id=${NODE_ID}&node_type=${NODE_TYPE}&token=${API_KEY}")
[ -z "$USERS_JSON" ] && exit 1

python3 << PYEOF
import json, os, re
users = json.loads('''$USERS_JSON''').get("users", [])
uuid_to_id = {u["uuid"]: u["id"] for u in users}
log_file = "$LOG_FILE"; state_file = "$STATE_FILE"
last_pos = 0
if os.path.exists(state_file):
    try:
        with open(state_file) as f: last_pos = int(f.read().strip())
    except: last_pos = 0
traffic = {}
if os.path.exists(log_file):
    file_size = os.path.getsize(log_file)
    if last_pos > file_size: last_pos = 0
    with open(log_file, 'rb') as f:
        f.seek(last_pos); new_data = f.read(); new_pos = f.tell()
    pattern = re.compile(r'connection closed.*?\[([0-9a-f-]{36})@.*?upload:\s*(\d+)\s*bytes.*?download:\s*(\d+)\s*bytes', re.IGNORECASE)
    for m in pattern.finditer(new_data.decode('utf-8', errors='ignore')):
        uuid = m.group(1); up = int(m.group(2)); down = int(m.group(3))
        if uuid in uuid_to_id:
            uid = str(uuid_to_id[uuid])
            if uid not in traffic: traffic[uid] = [0, 0]
            traffic[uid][0] += up; traffic[uid][1] += down
    with open(state_file, 'w') as f: f.write(str(new_pos))
if traffic:
    import urllib.request
    url = "$API_HOST/api/v1/server/UniProxy/push?node_id=$NODE_ID&node_type=$NODE_TYPE&token=$API_KEY"
    req = urllib.request.Request(url, data=json.dumps(traffic).encode(), headers={"Content-Type":"application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10); print(f"push ok: {traffic}")
    except Exception as e: print(f"push error: {e}")
else: print("no new closed connections")
PYEOF
```

#### 加入 crontab（两种方案通用）

```bash
chmod +x /usr/local/bin/push-traffic-NODE_ID.sh
(crontab -l 2>/dev/null | grep -v "push-traffic-NODE_ID"; \
 echo "* * * * * /usr/local/bin/push-traffic-NODE_ID.sh >> /var/log/push-traffic-NODE_ID.log 2>&1") | crontab -
```

#### 验证

等 1 分钟后查看日志：
```bash
tail -5 /var/log/push-traffic-NODE_ID.log
# 无流量时显示: no delta / no new closed connections
# 有流量时显示: push ok: {"用户ID": [上传, 下载]}
```

---

### 第八步：开放防火墙端口

```bash
# Hysteria2
ufw allow 443/udp

# VLESS+Reality
ufw allow 8443/tcp

# VMess（如有）
ufw allow 9443/tcp

ufw reload
```

---

### 第九步：部署 xray watchdog（xray 节点必须）

**背景**：xray 进程在长时间运行后会出现「端口在监听、进程存活、但不处理新连接」的卡死状态，客户端表现为 Timeout，重启即恢复。必须部署 watchdog 自动检测并重启。

在节点机上执行（根据实际服务名调整 `SERVICES` 和 `PORTS` 数组）：

```bash
cat > /usr/local/bin/xray-watchdog.sh << 'EOF'
#!/bin/bash
# xray watchdog: 检测 xray 是否能处理连接，卡住则重启
# 根据本机实际节点修改以下两个数组（顺序一一对应）
SERVICES=("xray-vless-8" "xray-vmess-7")   # 日本示例
PORTS=("8443" "9443")
LOG=/var/log/xray-watchdog.log

for i in "${!SERVICES[@]}"; do
  SVC="${SERVICES[$i]}"
  PORT="${PORTS[$i]}"
  if ! timeout 3 bash -c "echo > /dev/tcp/127.0.0.1/$PORT" 2>/dev/null; then
    echo "$(date) $SVC port $PORT not responding, restarting..." >> "$LOG"
    systemctl restart "$SVC"
  else
    echo "$(date) $SVC port $PORT OK" >> "$LOG"
  fi
done
# 只保留最近200行日志
tail -200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
EOF
chmod +x /usr/local/bin/xray-watchdog.sh

# 加入 crontab 每 5 分钟执行
(crontab -l 2>/dev/null | grep -v xray-watchdog; \
 echo "*/5 * * * * /usr/local/bin/xray-watchdog.sh >> /var/log/xray-watchdog.log 2>&1") | crontab -

# 验证
crontab -l | grep watchdog
```

**韩国机对应配置**：
```bash
SERVICES=("xray-vless-2" "xray-vmess-3")   # 根据实际服务名
PORTS=("8443" "9443")
```

> **注意**：sing-box（Hy2）不需要 watchdog，它自带 `Restart=on-failure` 且不会出现卡死问题。

---

### 第十步：连通性验证

#### 验证服务端正常运行

```bash
# Hysteria2
systemctl status sing-box-hy2-NODE_ID --no-pager | head -5
ss -ulnp | grep ':443'

# VLESS+Reality / VMess
systemctl status xray-vless-NODE_ID --no-pager | head -5
ss -tlnp | grep -E ':8443|:9443'
```

#### 验证订阅内容包含新节点

```bash
curl -s -A "FlClash/0.8.92" \
  "https://jumpingnow.com/api/v1/client/subscribe?token=GZu8JHLctHNOpNBavJvMdfAULQuxDSUp" \
  | grep "节点名称"
```

#### 用 mihomo 实际测试连通性（必须做，不能只靠端口监听判断）

**⚠️ 重要经验**：xray 端口在监听不代表能处理连接（进程卡死时端口仍在监听但返回 502）。**必须用 mihomo 实际发起代理请求**验证。

```bash
# 确认 mihomo 已安装（面板机 /tmp/mihomo 已有）
ls -la /tmp/mihomo || (cd /tmp && curl -fsSL -o mihomo.gz \
  "https://github.com/MetaCubeX/mihomo/releases/download/v1.19.21/mihomo-linux-amd64-v1.19.21.gz" \
  && gunzip mihomo.gz && chmod +x mihomo)

mkdir -p /tmp/mihomo-test
```

Hysteria2 测试配置：
```yaml
mixed-port: 17890
mode: rule
log-level: warning
proxies:
  - name: test-hy2
    type: hysteria2
    server: 子域名.amxyao.uk
    port: 443
    password: 用户UUID
    sni: 子域名.amxyao.uk
    skip-cert-verify: false
proxy-groups:
  - name: PROXY
    type: select
    proxies: [test-hy2]
rules:
  - MATCH, PROXY
```

VLESS+Reality 测试配置（`client-fingerprint` 必须用 `chrome`）：
```yaml
mixed-port: 17890
mode: rule
log-level: warning
proxies:
  - name: test-vless
    type: vless
    server: 服务器IP或域名
    port: 8443
    uuid: 用户UUID
    flow: xtls-rprx-vision
    tls: true
    servername: www.lovelive-anime.jp
    reality-opts:
      public-key: 生成的公钥
      short-id: 生成的ShortId
    client-fingerprint: chrome
    network: tcp
proxy-groups:
  - name: PROXY
    type: select
    proxies: [test-vless]
rules:
  - MATCH, PROXY
```

VMess 测试配置：
```yaml
mixed-port: 17890
mode: rule
log-level: warning
proxies:
  - name: test-vmess
    type: vmess
    server: 域名
    port: 9443
    uuid: 用户UUID
    alterId: 0
    cipher: auto
    tls: true
    network: tcp
    servername: 域名
    skip-cert-verify: false
proxy-groups:
  - name: PROXY
    type: select
    proxies: [test-vmess]
rules:
  - MATCH, PROXY
```

```bash
# 启动 mihomo
pkill mihomo; sleep 1
nohup /tmp/mihomo -d /tmp/mihomo-test -f /tmp/mihomo-test/config.yaml >/dev/null 2>&1 &
sleep 5

# 测试（HTTP 204 = 成功）
curl -sS -o /dev/null -w "code=%{http_code} time=%{time_total}s\n" \
  --connect-timeout 20 -x http://127.0.0.1:17890 \
  "http://connectivitycheck.platform.hicloud.com/generate_204"

pkill mihomo
```

**`code=204` 即为成功。若返回 502，说明 xray 进程卡死，执行 `systemctl restart xray-服务名` 后重测。**

---

## 常见问题

### Reality 握手超时
- **原因**：伪装目标有 IPv6 地址，服务器 IPv6 出口不通
- **排查**：`dig +short AAAA 伪装域名` 有输出则不可用
- **解决**：换纯 IPv4 域名，已验证可用：`www.lovelive-anime.jp`

### Hysteria2 报 `tls: no application protocol`
- **原因**：使用了 V2bX 内嵌的 sing-box（v1.13 有 bug）
- **解决**：必须使用独立 sing-box v1.10.7

### VLESS+Reality 握手无响应
- **原因一**：xray 配置缺少 `dest` 字段（V2bX 翻译 bug）
- **原因二**：Xboard 数据库中 `private_key` 为 null
- **解决**：使用独立 xray 服务，配置中必须包含 `dest` 字段

### 新用户订阅后看不到节点
- **原因**：用户同步脚本还未运行
- **解决**：手动执行一次同步脚本，或等待下一分钟 cron 触发

### 面板已用流量一直显示 0 B
- **原因**：节点只拉用户（GET /UniProxy/user），没有 push 流量（POST /UniProxy/push）
- **解决**：按第七步部署 push 脚本并加入 crontab
- **验证**：`tail -f /var/log/push-traffic-NODE_ID.log`，有流量时应出现 `push ok`

### sing-box 加了 v2ray_api 后循环重启
- **原因**：sing-box 官方 release 不含 `with_v2ray_api` 编译 tag
- **报错**：`FATAL create service: create v2ray api server: v2ray api is not included in this build`
- **解决**：去掉配置里的 `experimental.v2ray_api`，改用 info 日志解析方案（见第七步）

### xray stats API 重启后累计值清零
- **现象**：xray 重启后 statsquery 返回值从 0 开始，push 脚本计算出负增量
- **解决**：push 脚本里用 `max(0, 当前 - 上次)` 处理，重启后自动适应，不会上报负值

### xray 节点测速 Timeout / 客户端 502（进程卡死）
- **现象**：`ss -tlnp` 显示端口在监听，进程存活，但客户端测速 Timeout，mihomo 代理返回 502
- **根本原因**：xray 进程在长时间运行后偶发卡死，端口监听但不处理新连接
- **排查**：用 mihomo 对该节点发起 HTTP 请求，返回 502 即确认卡死（不是 timeout 就是 502）
- **修复**：`systemctl restart xray-服务名`，重启后立即恢复
- **预防**：部署 xray watchdog（第九步），每 5 分钟自动检测端口响应，卡死自动重启
- **注意**：sing-box（Hy2）不会出现此问题，只有 xray（VLESS/VMess）需要 watchdog

### VLESS+Reality 订阅里 client-fingerprint 随机导致部分客户端 Timeout
- **现象**：同一节点，某些时候测速正常，某些时候 Timeout；或不同用户表现不一致
- **根本原因**：Xboard 默认用 `getRandFingerprint()` 随机选 `ios/firefox/safari` 等，部分客户端（Clash Verge 等）对非 chrome 指纹的 Reality 握手不稳定
- **修复**：已在 `ClashMeta.php` 中将 Reality 节点的 `client-fingerprint` 固定为 `chrome`（已持久化到 `compose.yaml`）
- **验证**：`curl ... | grep "东京-03"` 确认订阅里 `client-fingerprint: chrome`
