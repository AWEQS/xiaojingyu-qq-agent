<#
守护进程：定时探测，把健康快照写进 data\console\health.json 供控制台读取；
加 -AutoRestart 时，发现关键组件掉线会尝试自动拉起（带冷却，避免反复重启）。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\watchdog.ps1                 # 前台循环，60 秒一次
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\watchdog.ps1 -Once           # 只跑一次（测试）
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\watchdog.ps1 -AutoRestart    # 自动拉起
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\watchdog.ps1 -IntervalSec 30 -CooldownSec 180
#>
param(
    [int]$IntervalSec = 60,
    [int]$CooldownSec = 300,
    [switch]$Once,
    [switch]$AutoRestart
)

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$root = $AstrBotRoot

$stateDir = Join-Path $root 'data\console'
if (-not (Test-Path -LiteralPath $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$healthFile = Join-Path $stateDir 'health.json'
$logFile    = Join-Path $stateDir 'watchdog.log'
$healthPs1  = Join-Path $PSScriptRoot 'health.ps1'
$pidFile    = Join-Path $stateDir 'watchdog.pid'

# 单实例：用命名互斥体（进程退出自动释放，不会像 pid 文件那样留残）
# 桌面壳也会拉起本脚本，这里保证同时只有一个守护在跑。-Once 不占锁。
if (-not $Once) {
    $global:WatchdogMutex = New-Object System.Threading.Mutex($false, 'Global\XiaoJingYuWatchdog')
    $acquired = $false
    try { $acquired = $global:WatchdogMutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) {
        Write-Host '守护已在运行，跳过'
        exit 0
    }
    Set-Content -LiteralPath $pidFile -Value $PID -Encoding ASCII
}

$lastVerdict = ''
$lastRestart = @{}

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    # 日志超过 2 MB 时轮转
    if ((Get-Item -LiteralPath $logFile).Length -gt 2MB) {
        Move-Item -LiteralPath $logFile -Destination "$logFile.old" -Force
    }
}

function Invoke-Tick {
    $raw = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $healthPs1 -Json 2>$null
    if (-not $raw) { Write-Log 'health.ps1 无输出'; return }
    try { $h = ($raw | Out-String).Trim() | ConvertFrom-Json }
    catch { Write-Log "健康数据解析失败: $($raw | Out-String)"; return }

    # 原子写入（先写 tmp 再替换，避免控制台读到半个文件）
    $tmp = "$healthFile.tmp"
    ($h | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $healthFile -Force

    if ($h.verdict -ne $lastVerdict) {
        Write-Log ("状态变化: {0} -> {1}  问题: {2}" -f $lastVerdict.PadRight(8), $h.verdict, $(if ($h.problems) { $h.problems -join ', ' } else { '无' }))
        $script:lastVerdict = $h.verdict
    }

    if (-not $AutoRestart) { return }

    foreach ($p in @($h.problems)) {
        $now = [DateTime]::UtcNow
        if ($lastRestart.ContainsKey($p) -and ($now - $lastRestart[$p]).TotalSeconds -lt $CooldownSec) { continue }
        switch ($p) {
            'NapCat 6099'   { Write-Log "尝试重启 NapCat"; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\start-napcat.ps1') | Out-Null; $lastRestart[$p] = $now }
            'AstrBot 6185'  { Write-Log "尝试重启 AstrBot"; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\restart-astrbot.ps1') | Out-Null; $lastRestart[$p] = $now }
            '控制台 8787'   { Write-Log "尝试重启控制台"; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\start-console.ps1') | Out-Null; $lastRestart[$p] = $now }
            default { }
        }
    }
}

if ($Once) {
    Invoke-Tick
    if (Test-Path -LiteralPath $healthFile) { Get-Content -LiteralPath $healthFile -Raw -Encoding UTF8 }
    exit 0
}

Write-Log ("守护启动 interval=${IntervalSec}s autoRestart=$AutoRestart")
while ($true) {
    try { Invoke-Tick } catch { Write-Log "tick 异常: $($_.Exception.Message)" }
    Start-Sleep -Seconds $IntervalSec
}
