# 重启 NapCat（会登出，需要重新扫码）

. (Join-Path $PSScriptRoot '_paths.ps1')
# 重启 NapCat（会登出，需要重新扫码）
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\stop-napcat.ps1')
Start-Sleep -Seconds 3
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\start-napcat.ps1')
