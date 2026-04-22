# ============================================================================
# 每日复盘自动调度 - 任务 A（16:15）
# 调用 daily-review-workflow-v2 skill，生成本地复盘表/执行手册/速查/验证报告
# ============================================================================
# 由 Windows 任务计划程序于每交易日 16:15 触发
# 对应搭档脚本：run_multi_source.ps1（17:15 跑）
# ============================================================================

$ErrorActionPreference = "Continue"   # 不要让单步失败炸脚本；自己判断 exit code
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING     = "utf-8"

# ---- 路径常量 ----
$projectRoot = "E:\李响git工作空间\self-learning\role1-stock"
$logDir      = Join-Path $projectRoot "pipeline\scheduler\logs"
$today       = Get-Date -Format "yyyy-MM-dd"
$logFile     = Join-Path $logDir "daily_$today.log"
$claudeDir   = "C:\Users\Administrator\.claude"

# ---- 日志目录兜底 ----
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Write-Log([string]$msg) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line  = "[$stamp] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

Write-Log "===== DAILY-REVIEW-V2 START (date=$today) ====="

# ---- 周末过滤 ----
$dow = (Get-Date).DayOfWeek
if ($dow -eq "Saturday" -or $dow -eq "Sunday") {
    Write-Log "weekend ($dow) — skip"
    exit 0
}

# ---- 保证 claude 可用 ----
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

# ---- 调 Claude ----
# --bare          ：跳过 hooks、auto-memory、CLAUDE.md 等所有会话级装饰，保持干净
# --dangerously-skip-permissions ：cron 不能等权限询问；settings.json 已授权
# --add-dir       ：显式允许项目根 + .claude 目录（--bare 不会自动继承）
# --max-budget-usd ：成本上限（daily-v2 以脚本执行为主，3 美元足够）
$prompt = "跑今天（$today）复盘，使用 daily-review-workflow-v2 skill，生成每日复盘表、执行手册、速查、验证报告到 E:\李响git工作空间\self-learning\role1-stock\outputs\review\ 目录。本地数据缺失时立即报错停止。"

Write-Log "prompt=$prompt"
Write-Log "invoke claude ..."

& claude -p $prompt `
    --model "claude-sonnet-4-6" `
    --dangerously-skip-permissions `
    --add-dir $projectRoot `
    --add-dir $claudeDir `
    --output-format text `
    --max-budget-usd 3 `
    *>&1 | ForEach-Object { Write-Log $_ }

$code = $LASTEXITCODE
Write-Log "claude exit=$code"

# ---- 产出校验：今日复盘表是否已生成 ----
$reviewFile = Join-Path $projectRoot "outputs\review\每日复盘表_$today.md"
if (Test-Path $reviewFile) {
    Write-Log "OK review file present: $reviewFile"
    Write-Log "===== DAILY-REVIEW-V2 END (success) ====="
    exit 0
} else {
    Write-Log "WARN review file MISSING: $reviewFile"
    Write-Log "===== DAILY-REVIEW-V2 END (no-file) ====="
    exit 3
}
