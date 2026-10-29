<#
环境自检：一键看当前「QQ 通道 / AstrBot / 模型」接在哪、有没有端口冲突。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\check-env.ps1
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'

Write-Host "================ AstrBot 小鲸鱼 环境自检 ================"

Write-Host "`n[1] 端口"
foreach ($p in 6185, 6199, 6099, 3000, 3001, 18080) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    $who = if ($conn) { (Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue).ProcessName } else { '-' }
    $state = if ($conn) { 'LISTEN' } else { '' }
    Write-Host ("  {0,-6} {1,-8} {2}" -f $p, $state, $who)
}

Write-Host "`n[2] AstrBot 配置"
$cfgPath = (Get-AstrBotPath 'data\cmd_config.json')
if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $cfg.platform) {
        Write-Host ("  platform: {0} enable={1} ws={2}:{3}" -f $p.type, $p.enable, $p.ws_reverse_host, $p.ws_reverse_port)
    }
    $provIds = @($cfg.provider | ForEach-Object { $_.id }) -join ", "
    Write-Host ("  已配置模型 provider = {0}" -f $provIds)
    $dft = $cfg.provider_settings.default_provider_id
    if ($dft) { Write-Host ("  default_provider_id = {0}" -f $dft) }
} else {
    Write-Host "  未初始化（data\cmd_config.json 不存在）"
}

Write-Host "`n[3] 组件"
$checks = @{
    'AstrBot 可执行'   = (Get-AstrBotPath 'bin\astrbot.exe')
    'persona-pack'     = (Get-AstrBotPath 'data\plugins\astrbot_plugin_persona_pack\main.py')
    'whale-behavior'   = (Get-AstrBotPath 'data\plugins\astrbot_plugin_whale_behavior\main.py')
    'member-memory'    = (Get-AstrBotPath 'data\plugins\astrbot_plugin_member_memory\main.py')
    'sticker-pack'     = (Get-AstrBotPath 'data\plugins\astrbot_plugin_sticker_pack\main.py')
    'mock LLM'         = (Get-AstrBotPath 'mock\mock_llm.py')
    'NapCat 安装器'    = (Get-AstrBotPath 'napcat-installer\NapCatInstaller.exe')
    'NapCat 已安装'    = (Get-AstrBotPath 'napcat')
}
foreach ($k in $checks.Keys) {
    $ok = Test-Path $checks[$k]
    Write-Host ("  {0,-16} {1}" -f $k, $(if ($ok) { 'OK' } else { '缺失' }))
}

Write-Host "`n[4] 当前链路判断"
$mockUp = [bool](Get-NetTCPConnection -State Listen -LocalPort 18080 -ErrorAction SilentlyContinue)
$oneBotUp = [bool](Get-NetTCPConnection -State Listen -LocalPort 6199 -ErrorAction SilentlyContinue)
if ($oneBotUp -and $mockUp) {
    Write-Host "  QQ: mock 客户端（OneBot 6199 在听） | 模型: mock LLM（18080）"
} elseif ($oneBotUp) {
    Write-Host "  QQ: OneBot 6199 在听（真协议端可能已连上） | 模型: 看 provider 配置"
} else {
    Write-Host "  AstrBot 没在跑？先执行 astrbot run"
}
Write-Host "`n========================================================"
