<#
启动 NapCat（便携 QQ 9.9.33 + 独立 profile 目录）并等待 OneBot 连上 AstrBot。

注意：
  - 必须用 Start-Process 直连启动；用 cmd 包装 + 重定向会让 QQ 子进程随控制台退出（已踩坑）
  - 重启 NapCat 后通常需要重新扫码登录
  - 运行前请确认日常 QQ 已退出（单实例冲突）

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\start-napcat.ps1
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$root = (Get-AstrBotPath 'napcat')
$qqExe = "$root\qq-9.9.33\Files\QQ.exe"

if (-not (Test-Path $qqExe)) {
    Write-Host "没找到便携 QQ：$qqExe"
    Write-Host "先跑 scripts\install-napcat.ps1 和 NapCatInstaller，或检查目录。"
    exit 1
}

$running = @(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
    Where-Object { $_.ExecutablePath -like '*qq-9.9.33*' })
if ($running.Count -gt 0) {
    Write-Host "NapCat 的便携 QQ 已在运行（$($running.Count) 个进程），不重复启动。"
    exit 0
}

$dailyQQ = @(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
    Where-Object { $_.ExecutablePath -notlike '*qq-9.9.33*' })
if ($dailyQQ.Count -gt 0) {
    Write-Host "检测到你日常的 QQ 正在运行，可能导致单实例冲突。建议先完全退出日常 QQ。"
}

$env:NAPCAT_PATCH_PACKAGE = "$root\qqnt.json"
$env:NAPCAT_LOAD_PATH = "$root\loadNapCat.js"
$env:NAPCAT_INJECT_PATH = "$root\NapCatWinBootHook.dll"
$env:NAPCAT_MAIN_PATH = "$root\napcat.mjs"

$log = "$root\napcat-live-$(Get-Date -Format 'HHmmss').log"
Start-Process -FilePath "$root\NapCatWinBootMain.exe" `
    -ArgumentList "`"$qqExe`"", "`"$root\NapCatWinBootHook.dll`"", "`"--user-data-dir=$root\qq-data`"" `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"

Write-Host "已启动 NapCat，日志：$log"
Write-Host "等待 6099 WebUI ..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (Get-NetTCPConnection -State Listen -LocalPort 6099 -ErrorAction SilentlyContinue) {
        Write-Host "  WebUI: http://127.0.0.1:6099/webui"
        break
    }
}

$conn = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $conn = Get-NetTCPConnection -State Established -RemotePort 6199 -ErrorAction SilentlyContinue
    if ($conn) { break }
}
if ($conn) {
    Write-Host "已连接 AstrBot 6199，真 QQ 通道就绪。"
} else {
    Write-Host "尚未连上 6199：可能停在扫码登录。打开 WebUI 扫码，登录后会自动连。"
}
