# T2 监视器：轮询 log 与产出文件，只把关键行发到 stdout
$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8

$log  = "E:\李响git工作空间\self-learning\role1-stock\pipeline\scheduler\logs\multi_2026-04-21.log"
$xhs  = "E:\李响git工作空间\self-learning\role1-stock\outputs\review\小红书_2026-04-21.md"
$long = "E:\李响git工作空间\self-learning\role1-stock\outputs\review\多源复盘长文_2026-04-21.md"

$seenLogLines = 0
$announcedLong = $false
$patternKey    = 'START|END|ERROR|WARN|exit=|claude=|prereq|invoke claude|desktop copy|MISSING|xhs|longform'

$tStart = Get-Date
while ($true) {
    # 1) 日志新增行
    if (Test-Path $log) {
        $all = Get-Content -Path $log -Encoding utf8
        if ($all) {
            $n = $all.Count
            if ($n -gt $seenLogLines) {
                for ($i = $seenLogLines; $i -lt $n; $i++) {
                    $line = $all[$i]
                    if ($line -match $patternKey) {
                        Write-Output ("LOG: " + $line)
                    }
                }
                $seenLogLines = $n
            }
        }
    } else {
        $elapsed = (New-TimeSpan -Start $tStart -End (Get-Date)).TotalSeconds
        if ($elapsed -gt 90 -and $elapsed -lt 100) {
            Write-Output "LOG: (still not created after 90s — T2 host may have crashed early)"
        }
    }

    # 2) 长文落盘
    if ((Test-Path $long) -and -not $announcedLong) {
        Write-Output ("OUT: 长文 MD created (" + (Get-Item $long).Length + " bytes)")
        $announcedLong = $true
    }

    # 3) 小红书落盘 = 任务完成
    if (Test-Path $xhs) {
        Write-Output ("OUT: 小红书 MD created (" + (Get-Item $xhs).Length + " bytes) — DONE")
        break
    }

    # 4) 总超时（9 分钟兜底，让 Monitor 的 600s 先触发）
    if ((New-TimeSpan -Start $tStart -End (Get-Date)).TotalMinutes -gt 9) {
        Write-Output "WATCH: 9-minute watchdog, giving up waiting for xhs MD"
        break
    }

    Start-Sleep -Seconds 8
}
