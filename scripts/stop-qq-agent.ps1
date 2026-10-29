<#
停止小鲸鱼 QQ Agent：
  - 停 AstrBot（6185/6199）
  - 停 NapCat 的便携 QQ（只动 qq-9.9.33 目录下的进程，不碰你日常 QQ）
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'

Write-Host "停止 AstrBot ..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\stop-all.ps1')

Write-Host "停止 NapCat 便携 QQ ..."
$procs = @(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
    Where-Object { $_.ExecutablePath -like '*qq-9.9.33*' })
if ($procs.Count -eq 0) {
    Write-Host "  没有在运行的便携 QQ"
} else {
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "  已停止 $($procs.Count) 个进程"
}

Start-Sleep -Seconds 2
$left = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 6185, 6199, 6099 }
if ($left) { Write-Host "仍有端口在听：" ; $left | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize }
else { Write-Host "已全部停止" }
