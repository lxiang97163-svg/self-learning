/**
 * 验证：1) Playwright CLI（npm 包） 2) 本机是否已下载 Chromium 浏览器缓存
 * 用法：在 bangdai-app 目录下 npm run playwright:verify
 */
const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const os = require("os");

function main() {
  console.log("=== 1. Playwright CLI（npx playwright --version）===");
  try {
    const v = execSync("npx playwright --version", {
      encoding: "utf-8",
      cwd: __dirname + "/..",
      stdio: ["ignore", "pipe", "pipe"],
    });
    console.log(v.trim());
  } catch (e) {
    console.error("失败：未找到 Playwright CLI，请在 bangdai-app 下执行 npm install");
    process.exit(1);
  }

  const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  const base = path.join(localAppData, "ms-playwright");
  console.log("\n=== 2. 浏览器缓存目录 ===");
  console.log(base);

  if (!fs.existsSync(base)) {
    console.log("状态：目录不存在 → 尚未执行 playwright install 或未下载任何浏览器。");
    console.log("请在本机终端执行：cd bangdai-app && npx playwright install chromium");
    process.exit(2);
  }

  const entries = fs.readdirSync(base).filter((d) => d.startsWith("chromium"));
  console.log("chromium* 子目录：", entries.length ? entries.join(", ") : "（无）");

  const headlessDirs = fs.readdirSync(base).filter((d) => d.startsWith("chromium_headless_shell"));
  let foundExe = false;
  for (const d of headlessDirs) {
    const exe = path.join(base, d, "chrome-headless-shell-win64", "chrome-headless-shell.exe");
    if (fs.existsSync(exe)) {
      console.log("状态：已找到 headless shell →", exe);
      foundExe = true;
    }
  }

  if (!foundExe && entries.length === 0 && headlessDirs.length === 0) {
    console.log("状态：未检测到 Chromium 缓存。请执行：npx playwright install chromium");
    process.exit(3);
  }
  if (!foundExe) {
    console.log("状态：有部分 chromium 目录但未找到可执行文件，可尝试重新 install。");
    process.exit(4);
  }

  console.log("\n结论：CLI 与浏览器缓存均就绪，可运行 npm run test:e2e");
  process.exit(0);
}

main();
