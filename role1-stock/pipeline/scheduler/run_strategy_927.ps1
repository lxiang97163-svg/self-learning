$ErrorActionPreference = "Stop"
$logDir  = "E:\李响git工作空间\self-learning\role1-stock\pipeline\scheduler\logs"
$logFile = "$logDir\strategy_927_$(Get-Date -Format 'yyyy-MM-dd').log"

function Log($msg) {
    $ts = Get-Date -Format 'HH:mm:ss'
    $line = "$ts $msg"
    $line | Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Host $line
}

Log "=== StrategyCollect_0927 START ==="

try {
    $script = "E:\李响git工作空间\self-learning\role1-stock\三一传统策略\dashboard\collect_strategy.py"
    & python $script 2>&1 | ForEach-Object { Log $_ }
    Log "=== DONE ==="
} catch {
    Log "ERROR: $_"
    exit 1
}
