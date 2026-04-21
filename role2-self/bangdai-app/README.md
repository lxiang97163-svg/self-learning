# CarryLink 宠物帮带（演示）

> 在 **`self-learning`** 仓库中的路径：**`role2-self/bangdai-app/`**（由 `jumpingnow_all/bangdai-app` 迁入；项目内无硬编码父目录路径）。

国际航班**宠物帮带**场景：旅客「携带意向」与宠物主「帮带需求」的**信息发布与撮合**演示应用。技术栈：**TypeScript + Next.js 14（App Router）+ Tailwind CSS + SQLite + Prisma + NextAuth（Credentials）**。

升级自泛「帮带」模型后，数据库表已更换；若本地仍有旧 `dev.db`，请删除后重新执行 `npx prisma db push`（或改用新库路径）。详见 `docs/BUSINESS_SPEC_petcarry.md`。

**非法律意见**：合规与禁运表述为模板，上线前须由律师及当地海关/监管要求确认。

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | SQLite 路径，默认 `file:./dev.db` |
| `NEXTAUTH_SECRET` | 随机长密钥（勿提交仓库） |
| `NEXTAUTH_URL` | 站点根 URL，本地 `http://localhost:3000` |
| `PLATFORM_FEE_RATE` | 平台服务费比例，如 `0.08` |
| `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` | 可选，供 `db:seed` 创建管理员 |
| `PLAYWRIGHT_CHANNEL` | 可选：设为 `msedge` 或 `chrome` 时，E2E 使用**本机已安装**的浏览器，可**不执行** `playwright install chromium`（见下文 E2E） |

## 初始化数据库

```bash
cd bangdai-app
npm install
copy .env.example .env   # Windows；或手动复制并编辑
npx prisma db push
npm run db:seed
```

## 创建管理员账号

- **默认**：`npm run db:seed` 会按 `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`（或示例默认值） upsert 一名 `admin` 用户。
- 新用户通过注册页创建时 **role 为 `user`**，不会自动成为管理员。

## 本地访问

```bash
npm run dev
```

浏览器打开：**http://localhost:3000**

## 认证说明

- 使用 **NextAuth Credentials**：邮箱 + 密码；密码使用 **bcrypt** 哈希存储（见 Prisma `User.passwordHash`）。
- 未实现真实短信/邮箱 OTP；后续可接验证码占位。

## 撮合逻辑说明（README 要求）

- **携带意向详情** `/offers/[id]`：需求方选择「我的需求」→ **表达兴趣**。
- **需求详情** `/needs/[id]`：携带方选择「我的携带意向」→ **表达兴趣**。
- 二者二选一即可，逻辑一致：同一 `PetCarryMatch` 由 `offerId + needId` 唯一确定；目的地须一致，且需求方宠物体重不得超过携带意向声明的上限。
- 旧路径 `/trips/*`、`/requests/*` 已 **301 重定向** 至 `/offers/*`、`/needs/*`。

## 构建与单机运行

```bash
npm run build
npm start
```

## Docker Compose

```bash
docker compose up --build
```

镜像内会 `prisma db push` 后启动 `next start`；数据库文件挂载在 `data/`（见 `docker-compose.yml`）。

## 脚本

| 命令 | 说明 |
|------|------|
| `npm run lint` | ESLint |
| `npm run build` | `prisma generate` + `next build` |
| `npm run test:e2e` | 先 `prisma db push`，再 Playwright（需已配置 `.env`） |

## E2E

依赖 Playwright 与本地 `.env`（含 `NEXTAUTH_SECRET`）。

### 区分两件事

1. **npm 包（CLI）**：随 `npm install` 安装。可用下面命令确认（应有输出如 `Version 1.x.x`）：
   ```bash
   npx playwright --version
   ```
2. **浏览器二进制**：需单独下载，与 CLI 不是一回事。未下载时跑测试会报 `Executable doesn't exist`。

### 验证当前环境

在 `bangdai-app` 目录：

```bash
npm run playwright:verify
```

会打印 CLI 版本，并检查 `%LOCALAPPDATA%\ms-playwright` 下是否已有 Chromium 缓存。

### 安装浏览器（首次）

```bash
npx playwright install chromium
```

安装过程在**非交互终端**里可能**长时间无输出**（仍在下载），可另开 PowerShell 用任务管理器看网络，或把输出重定向到文件：

```powershell
npx playwright install chromium 2>&1 | Tee-Object -FilePath playwright-install.log
```

然后再执行 `npm run playwright:verify`，应显示已找到 `chrome-headless-shell.exe`。

### 跳过 Playwright 自带 Chromium 下载（可选）

若不想下载 `%LOCALAPPDATA%\ms-playwright` 下的 Chromium，可在 `.env` 中增加一行（**二选一**，不要两行同时生效）：

```env
PLAYWRIGHT_CHANNEL=msedge
```

或（本机已装 Google Chrome 时）：

```env
PLAYWRIGHT_CHANNEL=chrome
```

`playwright.config.ts` 会加载 `.env` / `.env.local`，测试将走系统里的 Edge/Chrome，**无需** `npx playwright install chromium`。未设置 `PLAYWRIGHT_CHANNEL` 时，仍使用 Playwright 自带的 Chromium，需先 install。

### 跑 E2E

```bash
npm run test:e2e
```

`test:e2e` 会先执行 `prisma db push` 再启动 `playwright test`（`playwright.config.ts` 会拉起 `npm run dev`）。

## 验收与非目标

- 无应用内支付、无资金托管、无 KYC 强校验。
- 无 AI 定价、无自动海关规则引擎。
