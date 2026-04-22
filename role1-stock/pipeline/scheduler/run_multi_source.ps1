# ============================================================================
# 每日复盘自动调度 - 任务 B（17:15）
# 调用 multi-source-daily-review skill「全网复盘」全流程
#   · Step 1：读本地复盘表 / 执行手册 / 速查 / 验证报告
#   · Step 2：全网检索 ≥4 次、≥10 类来源
#   · Step 3：落盘《多源复盘长文_YYYY-MM-DD.md》
#   · Step 4：落盘《小红书_YYYY-MM-DD.md》（见 references/xiaohongshu-output.md 非交互条款）
# ============================================================================
# 由 Windows 任务计划程序于每交易日 17:15 触发
# 依赖：run_daily_review.ps1 已在 16:15 生成本地复盘表
# ============================================================================

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING     = "utf-8"

# ---- 路径常量 ----
$projectRoot = "E:\李响git工作空间\self-learning\role1-stock"
$reviewDir   = Join-Path $projectRoot "outputs\review"
$logDir      = Join-Path $projectRoot "pipeline\scheduler\logs"
$today       = Get-Date -Format "yyyy-MM-dd"
$logFile     = Join-Path $logDir "multi_$today.log"
$xhsFile     = Join-Path $reviewDir "小红书_$today.md"
$longFile    = Join-Path $reviewDir "多源复盘长文_$today.md"
$readyFile   = Join-Path ([Environment]::GetFolderPath("Desktop")) "小红书_${today}_就绪.md"
$claudeDir   = "C:\Users\Administrator\.claude"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Write-Log([string]$msg) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line  = "[$stamp] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

Write-Log "===== MULTI-SOURCE-REVIEW START (date=$today) ====="

# ---- 周末过滤 ----
$dow = (Get-Date).DayOfWeek
if ($dow -eq "Saturday" -or $dow -eq "Sunday") {
    Write-Log "weekend ($dow) — skip"
    exit 0
}

# ---- 前置门禁：今日本地复盘表必须存在 ----
$reviewTable = Join-Path $reviewDir "每日复盘表_$today.md"
if (-not (Test-Path $reviewTable)) {
    Write-Log "ERROR: prerequisite MISSING: $reviewTable"
    Write-Log "       run_daily_review.ps1 (16:15) must finish before this job."
    exit 1
}
Write-Log "prereq OK: $reviewTable"

# ---- claude 可用性 ----
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Write-Log "ERROR: claude not found in PATH"
    exit 2
}
Write-Log "claude=$($claudeCmd.Source)"

# ---- 清除 ANTHROPIC_API_KEY 让 Claude 走 OAuth (.credentials.json) ----
if ($env:ANTHROPIC_API_KEY) {
    Write-Log ("unset bogus ANTHROPIC_API_KEY (was {0} chars) to let CLI use OAuth" -f $env:ANTHROPIC_API_KEY.Length)
    Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
}
Remove-Item Env:ANTHROPIC_AUTH_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:ANTHROPIC_BASE_URL   -ErrorAction SilentlyContinue
$credFile = "C:\Users\Administrator\.claude\.credentials.json"
if (Test-Path $credFile) {
    Write-Log "OAuth credentials file present"
} else {
    Write-Log "WARN: OAuth credentials file missing — claude will fail auth"
}

# ---- 调 Claude：全网复盘全流程，强制落盘小红书单独文件 ----
$prompt = @"
执行「全网复盘」全流程（触发 multi-source-daily-review skill）。复盘日固定为 $today。

流程（严格按 skill）：
1. 读本地：E:\李响git工作空间\self-learning\role1-stock\outputs\review\ 下的 每日复盘表_$today.md、执行手册_$today.md、速查_$today.md、验证报告_$today.md、韭研异动_$today.md（如存在）。
2. 至少 4 次 Web 检索，覆盖 ≥10 类来源（财联社、东财、同花顺、新浪、雪球、淘股吧等）。
3. 落盘长文到：$longFile
4. 必须落盘小红书正文到：$xhsFile（纯文本、段落 emoji 开头、末尾"仅供参考，不构成投资建议"+ 3~8 个 # 话题；不含 Markdown 标记如 ** 或 #）。

本地文件缺失或检索失败时不要编造数字，立即停止并在 stdout 报错退出。
"@

Write-Log "invoke claude opus ..."

& claude -p $prompt `
    --model "claude-opus-4-7" `
    --fallback-model "claude-sonnet-4-6" `
    --dangerously-skip-permissions `
    --add-dir $projectRoot `
    --add-dir $claudeDir `
    --output-format text `
    --max-budget-usd 8 `
    *>&1 | ForEach-Object { Write-Log $_ }

$code = $LASTEXITCODE
Write-Log "claude exit=$code"

# ---- 产出校验 ----
$haveLong = Test-Path $longFile
$haveXhs  = Test-Path $xhsFile
Write-Log "longform file exists = $haveLong ($longFile)"
Write-Log "xhs      file exists = $haveXhs  ($xhsFile)"

if ($haveXhs) {
    # 复制一份到桌面并命名成醒目名字；播放系统提示音
    try {
        Copy-Item -Path $xhsFile -Destination $readyFile -Force
        Write-Log "desktop copy: $readyFile"
    } catch {
        Write-Log "WARN: desktop copy failed: $_"
    }
    try {
        [System.Media.SystemSounds]::Asterisk.Play()
    } catch {}
    Write-Log "===== MULTI-SOURCE-REVIEW END (success) ====="
    exit 0
} else {
    Write-Log "ERROR: xiaohongshu output missing — check log above for skill execution detail"
    Write-Log "===== MULTI-SOURCE-REVIEW END (fail) ====="
    exit 4
}
