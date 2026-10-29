# 重启 AstrBot（控制台调用）

. (Join-Path $PSScriptRoot '_paths.ps1')
# 重启 AstrBot（控制台调用）
$ErrorActionPreference = 'Continue'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\stop-all.ps1')
Start-Sleep -Seconds 2
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\start-all.ps1')
