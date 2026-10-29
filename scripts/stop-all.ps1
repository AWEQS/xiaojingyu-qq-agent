<#
一键停止：按端口停掉 AstrBot / mock LLM（只动 6185/6199/18080，不碰 QQ Agent 的 3000/3001）
#>
. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'

Write-Host "停止 AstrBot / mock LLM ..."
foreach ($port in 6185, 6199, 18080) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        Write-Host ("  端口 {0} -> {1} (PID {2})" -f $port, $proc.ProcessName, $conn.OwningProcess)
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 2
$left = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 6185, 6199, 18080 }
if ($left) { Write-Host "仍有残留：" ; $left | Select-Object LocalPort, OwningProcess | Format-Table -AutoSize }
else { Write-Host "已全部停止（QQ Agent 的 3000/3001 未受影响）" }
