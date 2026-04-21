import { existsSync, readFileSync } from "fs";
import { resolve } from "path";
import { defineConfig } from "@playwright/test";

/** 无 dotenv 依赖：从项目根加载 .env.local / .env（不覆盖已有环境变量） */
function loadEnvFile(name: string) {
  const p = resolve(process.cwd(), name);
  if (!existsSync(p)) return;
  const text = readFileSync(p, "utf8");
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (process.env[key] === undefined) process.env[key] = val;
  }
}

loadEnvFile(".env.local");
loadEnvFile(".env");

/**
 * 使用本机已安装的浏览器，可跳过 `npx playwright install chromium`：
 * 在 .env 或环境变量中设置其一：
 *   PLAYWRIGHT_CHANNEL=msedge   （Windows 通常自带 Edge）
 *   PLAYWRIGHT_CHANNEL=chrome   （需已安装 Chrome）
 * 不设则使用 Playwright 自带的 Chromium（需先 install）。
 */
const channel = process.env.PLAYWRIGHT_CHANNEL as "chrome" | "msedge" | undefined;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: {
    // 与 .env 中 NEXTAUTH_URL 常用 localhost 对齐，避免 127.0.0.1 与 localhost 混用导致 Cookie 不生效
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    trace: "on-first-retry",
    ...(channel ? { channel } : {}),
  },
  webServer: {
    // 使用生产启动，避免 dev 下偶发 clientModules 等与 HMR 相关错误
    command: process.env.PW_WEBSERVER === "dev" ? "npm run dev" : "npm run start",
    url: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
