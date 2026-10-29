# 快速停止小鲸鱼相关服务（退出时调用，无 sleep、尽量少的查询）

. (Join-Path $PSScriptRoot '_paths.ps1')
# 快速停止小鲸鱼相关服务（退出时调用，无 sleep、尽量少的查询）
# 只动：AstrBot(6185/6199)、控制台(8787)、NapCat 启动器、便携 QQ（qq-9.9.33 路径）、<AstrBotRoot> 下的 pythonw
$ErrorActionPreference = 'Continue'

try {
    $ports = 6185, 6199, 8787
    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $ports }
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
} catch {}

try {
    $qq = Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
        Where-Object { $_.ExecutablePath -like '*qq-9.9.33*' }
    foreach ($p in $qq) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {}

try {
    Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
} catch {}

try {
    Get-Process pythonw -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -like (Get-AstrBotPath '*') } |
        Stop-Process -Force -ErrorAction SilentlyContinue
} catch {}
