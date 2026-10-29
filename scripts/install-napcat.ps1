<#
安装 NapCat（QQ 协议端）的准备工作：下载官方 OneKey 安装器并解压。
真正的安装需要你双击 NapCatInstaller.exe（会下载匹配版本 QQ，约 1.5GB）。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\install-napcat.ps1

装完继续看 docs\real-qq-checklist.md
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$version = 'v4.18.41'
$root = (Get-AstrBotPath 'napcat-installer')
$zip = Join-Path $root 'NapCat.Shell.Windows.OneKey.zip'
$url = "https://github.com/NapNeko/NapCatQQ/releases/download/$version/NapCat.Shell.Windows.OneKey.zip"

New-Item -ItemType Directory -Force -Path $root | Out-Null

if (-not (Test-Path $zip)) {
    Write-Host "[1/2] 下载 NapCat OneKey 安装器（约 1MB）..."
    try {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 180
    } catch {
        Write-Host "直连 GitHub 失败：$($_.Exception.Message)"
        Write-Host "请挂代理后重试，或手动下载后放到 $zip"
        exit 1
    }
} else {
    Write-Host "[1/2] 安装器已存在，跳过下载"
}

Write-Host "[2/2] 解压到 $root ..."
Expand-Archive -Path $zip -DestinationPath $root -Force
Get-ChildItem $root | Select-Object Name, Length | Format-Table -AutoSize

Write-Host @"

下一步（需要手动操作）：
  1) 双击 $root\NapCatInstaller.exe
     安装目录建议填：$AstrBotRoot\napcat（会下载约 1.5GB 的匹配版 QQ）
  2) 进入 $AstrBotRoot\napcat\NapCat.*.Shell 目录，双击 napcat.bat
  3) 按提示扫码登录【小号 QQ】
  4) 打开 NapCat WebUI（默认 http://127.0.0.1:6099），新建反向 WebSocket 客户端：
     ws://127.0.0.1:6199/ws   消息格式 array，token 留空
  5) 回 AstrBot 日志确认 aiocqhttp 收到事件；详见 docs\real-qq-checklist.md
"@
