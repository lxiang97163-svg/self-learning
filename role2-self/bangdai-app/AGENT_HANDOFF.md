# 帮带 CarryLink — 交接给下一任 Agent

## 项目是什么

**国际航班「宠物帮带」信息发布与撮合演示站**（中文 UI）。平台**不运输、不持货、不代理报关、不提供应用内支付**；仅记录双方确认的**约定金额**并**试算平台服务费**（比例来自环境变量），线下付款由用户自理。

**垂直定位**：已从泛「行李余量 × 小件需求」切换为 **宠物帮带**；数据模型为 `PetCarryOffer` / `PetCarryNeed` / `PetCarryMatch`。

**代码位置**：仓库内 **`bangdai-app/`**（Next.js 应用）。

---

## 原始规则分层（摘要）

### Harness（缰绳）

- 合规文案为模板，**非法律意见**；上线前须律师/海关确认。
- 不提供规避海关、走私、虚假申报指引；禁运与免责见 `/legal/*`，注册/发布需勾选确认。
- 密钥不进代码；**密码 bcrypt**；对话与个人信息最小化收集。

### Spec（规格）

- **角色**：携带方（PetCarryOffer）、需求方（PetCarryNeed）、管理员（admin）。
- **实体**：见 `prisma/schema.prisma`（`PetCarryOffer`、`PetCarryNeed`、`PetCarryMatch`、`CommissionRecord` 等）。
- **路由**：`/`，`/auth/register|login`，`/offers`（列表+筛选）、`/offers/new`、`/offers/[id]`，`/needs` 同理，`/matches/[id]`，`/messages`、`/messages/[threadId]`，`/legal/disclaimer`、`/legal/prohibited`，`/admin`。
- **主流程**：注册登录 → 发携带意向/需求 → 浏览 → 表达兴趣 → 对方接受 → 站内消息（accepted 状态）→ 记录约定金额与抽成试算 → 标记交割完成（completed）。

### Context（技术）

- **TypeScript + Next.js 14 App Router + Tailwind + SQLite + Prisma + NextAuth（Credentials）**。
- 部署：`docker compose` 或 `npm run build && npm start`。
- 详细命令与变量见 **`README.md`**、**`.env.example`**。

### 非目标（禁止）

- 真实支付、托管、KYC 强校验、原生 App/小程序、AI 定价、自动海关规则引擎、国际短信实发（可占位）。

---

## 实现层面的特殊说明

- **SQLite + Prisma**：未使用 Prisma `enum`（SQLite 不支持），状态字段均为 **字符串**（如 `"open"`、`"accepted"`），应用内用字面量比较。
- **E2E**：`e2e/bangdai.spec.ts`；`playwright.config.ts` 会 `loadEnv`（`.env` / `.env.local`）。若不想下载 Playwright 自带 Chromium，可在 `.env` 设 **`PLAYWRIGHT_CHANNEL=msedge`**（或 `chrome`）。
- **管理员**：仅 **`npm run db:seed`**（或环境变量中的 `SEED_ADMIN_*`）创建/提升为 `admin`；普通注册为 `user`。

---

## 已完成

| 项 | 说明 |
|----|------|
| 工程与库表 | Prisma schema（宠物帮带模型）、seed、`db:push` |
| 认证 | NextAuth Credentials、bcrypt、`role` 进 JWT/session |
| 携带意向/需求 | 列表筛选、发布、详情 |
| 撮合 | 表达兴趣、接受/拒绝、约定金额、`CommissionRecord` 试算、标记完成 |
| 消息 | `threadId = petCarryMatchId`，仅 **accepted** 时可发 |
| 法务页 | 免责、禁运模板 |
| Admin | 用户列表、帖子列表、举报列表 |
| 文档 | `README.md`、`.env.example`、本文件、`docs/BUSINESS_SPEC_petcarry.md` |

---

## 未完成 / 待下一任处理

| 项 | 说明 |
|----|------|
| **E2E 在你本机跑绿** | 需配置 `.env`；任选 **`playwright install chromium`** 或 **`PLAYWRIGHT_CHANNEL=msedge`** 后执行 `npm run test:e2e`。 |
| **Docker 镜像** | 有 `Dockerfile` / `compose.yml`，**未保证在本环境完整跑通**，需按需验证 `NEXTAUTH_*` 与数据卷。 |
| **生产加固** | Rate limit、审计日志、HTTPS、更细权限等未做。 |

---

## 给下一任 Agent 的快速命令

```bash
cd bangdai-app
npm install
# 若自旧版升级：删除 prisma/dev.db 或换 DATABASE_URL 后
npx prisma db push && npm run db:seed   # 可选
npm run dev          # http://localhost:3000
npm run lint && npm run build
npm run test:e2e
```

**详细步骤仍以 `bangdai-app/README.md` 为准。**
