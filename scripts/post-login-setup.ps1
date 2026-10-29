<#
登录后自动接管：等 NapCat 登录成功（config 里出现 onebot11_<QQ号>.json），
自动配置 OneBot 反连到 AstrBot（ws://127.0.0.1:6199/ws），重启 NapCat 并验证连接。

用法（登录前挂上，登录后自动完成）：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\post-login-setup.ps1
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$root = (Get-AstrBotPath 'napcat')
$cfgDir = Join-Path $root 'config'
$statusFile = Join-Path $root 'post-login-status.txt'

function Log([string]$msg) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $statusFile -Value $line -Encoding UTF8
}

Log "等待 NapCat 登录（最多 2 小时）..."
$deadline = (Get-Date).AddHours(2)
$found = $null
while ((Get-Date) -lt $deadline) {
    $files = @(Get-ChildItem $cfgDir -Filter 'onebot11_*.json' -ErrorAction SilentlyContinue)
    if ($files.Count -gt 0) { $found = $files[0]; break }
    Start-Sleep -Seconds 5
}

if (-not $found) {
    Log "超时：没检测到登录后的配置文件，退出。"
    exit 1
}

Log "检测到登录配置：$($found.Name)"

# 1) 写入反向 WS
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\configure-napcat-onebot.ps1')
Log "已配置 OneBot 反连（ws://127.0.0.1:6199/ws）"

# 2) 重启 NapCat 让配置生效
Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
    Where-Object { $_.ExecutablePath -like '*qq-9.9.33*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

$env:NAPCAT_PATCH_PACKAGE = "$root\qqnt.json"
$env:NAPCAT_LOAD_PATH = "$root\loadNapCat.js"
$env:NAPCAT_INJECT_PATH = "$root\NapCatWinBootHook.dll"
$env:NAPCAT_MAIN_PATH = "$root\napcat.mjs"
$log = Join-Path $root "napcat-live-$(Get-Date -Format 'HHmmss').log"
$err = "$log.err"
Start-Process -FilePath "$root\NapCatWinBootMain.exe" `
    -ArgumentList "`"$root\qq-9.9.33\Files\QQ.exe`"", "`"$root\NapCatWinBootHook.dll`"", "`"--user-data-dir=$root\qq-data`"" `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError $err
Log "已重启 NapCat，等待连接..."

# 3) 验证连接
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $c = Get-NetTCPConnection -State Established -RemotePort 6199 -ErrorAction SilentlyContinue
    if ($c) { $ok = $true; break }
}
if ($ok) {
    Log "成功：NapCat 已连接到 AstrBot 6199。真 QQ 通道已就绪。"
} else {
    Log "警告：没看到到 6199 的连接。请检查 $log 里是否是「二维码登录」状态。"
}
