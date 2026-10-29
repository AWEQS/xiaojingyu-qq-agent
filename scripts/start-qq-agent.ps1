<#
一键启动小鲸鱼 QQ Agent：
  1) AstrBot（WebUI 6185 + OneBot 6199）
  2) NapCat（便携 QQ + 独立 profile，WebUI 6099）
  3) 自检

用法（右键“使用 PowerShell 运行”也可以）：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\start-qq-agent.ps1
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$root = $AstrBotRoot

Write-Host "================ 启动小鲸鱼 QQ Agent ================"

Write-Host "`n[1/3] 启动 AstrBot ..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\start-all.ps1"

Write-Host "`n[2/3] 启动 NapCat（便携 QQ） ..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\start-napcat.ps1"

Write-Host "`n[3/3] 环境自检 ..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\scripts\check-env.ps1"

Write-Host @"

如果你看到「到 6199 连接 = 0」，说明 NapCat 还没登录：
  1) 浏览器打开 NapCat WebUI：看 logs 里的 token，或直接开 http://127.0.0.1:6099/webui
  2) 用手机 QQ（机器人小号）扫页面上的二维码 + 手机上点确认
  3) 登录成功后会自动连上 AstrBot

AstrBot WebUI：http://127.0.0.1:6185
项目目录：$AstrBotRoot
"@
