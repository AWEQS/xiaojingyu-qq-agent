<#
启动小鲸鱼控制台（本地网页 UI，端口 8787），并自动打开浏览器。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\start-console.ps1
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$root = $AstrBotRoot
$port = 8787
$python = "$root\tools\astrbot\Scripts\python.exe"
$pythonw = "$root\tools\astrbot\Scripts\pythonw.exe"
$server = "$root\console\server.py"

if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    Write-Host "控制台已在运行：http://127.0.0.1:$port"
} else {
    $exe = if (Test-Path $pythonw) { $pythonw } else { $python }
    Start-Process -FilePath $exe -ArgumentList $server `
        -WorkingDirectory "$root\console" -WindowStyle Hidden
    Write-Host "启动控制台 ..."
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { break }
    }
    Write-Host "http://127.0.0.1:$port"
}

Start-Process "http://127.0.0.1:$port"
