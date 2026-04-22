$logDir  = "E:\李响git工作空间\self-learning\role1-stock\pipeline\scheduler\logs"
$mainLog = "$logDir\sanyi_monitor_$(Get-Date -Format 'yyyy-MM-dd').log"

function Log($msg) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $msg"
    $line | Out-File -FilePath $mainLog -Append -Encoding utf8
    Write-Host $line
}

Log "=== SanyiMonitor STOP ==="

$targets = @("feeder.py", "advisor.py")
foreach ($script in $targets) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -like "*$script*" }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Log "$script PID=$($p.ProcessId) 已终止"
    }
    if (-not $procs) { Log "$script 未在运行" }
}

Log "=== STOP DONE ==="
