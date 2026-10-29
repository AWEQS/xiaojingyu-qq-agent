# 停止 NapCat 的便携 QQ（不碰日常 QQ）

. (Join-Path $PSScriptRoot '_paths.ps1')
# 停止 NapCat 的便携 QQ（不碰日常 QQ）
$ErrorActionPreference = 'Continue'
$procs = @(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" |
    Where-Object { $_.ExecutablePath -like '*qq-9.9.33*' })
foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "已停止 $($procs.Count) 个便携 QQ 进程"
