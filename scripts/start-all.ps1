<#
一键启动：AstrBot（可附带 mock LLM）

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\start-all.ps1 -WithMockLLM
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\stop-all.ps1
#>
param(
    [switch]$WithMockLLM
)
. (Join-Path $PSScriptRoot '_paths.ps1')

$ErrorActionPreference = 'Continue'
$root = $AstrBotRoot

function Wait-Port([int]$port, [int]$seconds = 90) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

if ($WithMockLLM) {
    if (Get-NetTCPConnection -State Listen -LocalPort 18080 -ErrorAction SilentlyContinue) {
        Write-Host "mock LLM 已在 18080 运行"
    } else {
        Write-Host "启动 mock LLM (18080)..."
        Start-Process -FilePath "$root\scripts\_run-mock-llm.cmd" -WindowStyle Hidden
        if (Wait-Port 18080 20) { Write-Host "  mock LLM OK" } else { Write-Host "  mock LLM 启动失败，看 mock_llm.err.log" }
    }
}

if (Get-NetTCPConnection -State Listen -LocalPort 6185 -ErrorAction SilentlyContinue) {
    Write-Host "AstrBot 已在运行（6185）"
} else {
    Write-Host "启动 AstrBot..."
    Start-Process -FilePath "$root\scripts\_run-astrbot.cmd" -WindowStyle Hidden
    if (Wait-Port 6185 90) { Write-Host "  WebUI OK: http://127.0.0.1:6185" } else { Write-Host "  启动超时，看 run-stderr.log" }
}

if (Get-NetTCPConnection -State Listen -LocalPort 6199 -ErrorAction SilentlyContinue) {
    Write-Host "  OneBot 反连入口: ws://127.0.0.1:6199/ws（等待协议端连接）"
}

Write-Host "`n自检："
& "$root\scripts\check-env.ps1"
