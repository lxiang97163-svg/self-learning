$ErrorActionPreference = "Continue"

$logDir  = "E:\李响git工作空间\self-learning\role1-stock\pipeline\scheduler\logs"
$dashDir = "E:\李响git工作空间\self-learning\role1-stock\三一传统策略\dashboard"

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$today   = Get-Date -Format 'yyyy-MM-dd'
$mainLog = "$logDir\sanyi_monitor_$today.log"

function Log($msg) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $msg"
    $line | Out-File -FilePath $mainLog -Append -Encoding utf8
    Write-Host $line
}

Log "=== SanyiMonitor START ==="

# 检查是否已在运行，避免重复启动
function Is-Running($scriptName) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -like "*$scriptName*") { return $true }
    }
    return $false
}

$pythonExe = "C:\ProgramData\anaconda3\python.exe"

# 优先用 Task Scheduler 启动（进程不受 Job Object 限制），降级到 WMI
function Start-Daemon($taskName) {
    $taskPath = "\ClaudeCode\"
    $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) { Log "ERROR: Task $taskName 不存在"; return $null }
    Start-ScheduledTask -TaskPath $taskPath -TaskName $taskName
    Start-Sleep -Seconds 2
    $info = Get-ScheduledTaskInfo -TaskPath $taskPath -TaskName $taskName
    return $info.LastRunTime
}

# ── feeder.py ──
if (Is-Running "feeder.py") {
    Log "feeder.py 已在运行，跳过启动"
} else {
    Start-Daemon "SanyiFeeder_0900"
    Log "feeder.py 通过 Task Scheduler 已启动"
    Start-Sleep -Seconds 3
}

# ── advisor.py ──
if (Is-Running "advisor.py") {
    Log "advisor.py 已在运行，跳过启动"
} else {
    Start-Daemon "SanyiAdvisor_0901"
    Log "advisor.py 通过 Task Scheduler 已启动"
}

Log "=== SanyiMonitor DONE ==="
