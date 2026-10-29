<#
一键切换 AstrBot 的模型 provider（OpenAI 兼容）。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\switch-model.ps1 `
    -BaseUrl "https://api.deepseek.com/v1" -Model "deepseek-chat" -ApiKey "sk-xxx"

说明：
  - 会写入 provider_sources / provider，并把默认 provider 指向新模型
  - 然后重启 AstrBot 生效（NapCat 会自动重连，不影响 QQ 登录）
#>
param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$Model,
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [string]$ProviderId = 'real',
    [switch]$NoRestart
)
. (Join-Path $PSScriptRoot '_paths.ps1')

$ErrorActionPreference = 'Stop'
$py = (Get-AstrBotPath 'tools\astrbot\Scripts\python.exe')
$cfgPath = (Get-AstrBotPath 'data\cmd_config.json')

$pyScript = @'
import json, pathlib, sys
cfg_path = pathlib.Path(sys.argv[1])
base_url, model, api_key, provider_id = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
cfg = json.loads(cfg_path.read_text("utf-8-sig"))

source_id = provider_id + "_source"
sources = [s for s in (cfg.get("provider_sources") or []) if s.get("id") != source_id]
sources.append({
    "id": source_id,
    "provider": "openai",
    "type": "openai_chat_completion",
    "provider_type": "chat_completion",
    "enable": True,
    "key": [api_key],
    "api_base": base_url,
    "timeout": 120,
    "proxy": "",
    "custom_headers": {},
})
cfg["provider_sources"] = sources

providers = [p for p in (cfg.get("provider") or []) if p.get("id") != provider_id]
providers.append({
    "id": provider_id,
    "provider_source_id": source_id,
    "model": model,
    "modalities": [],
    "custom_extra_body": {},
    "enable": True,
})
cfg["provider"] = providers
cfg.setdefault("provider_settings", {})["default_provider_id"] = provider_id

cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8-sig")
print("已写入 provider:", provider_id, "model:", model)
'@

$tmp = Join-Path $env:TEMP 'switch_model.py'
[IO.File]::WriteAllText($tmp, $pyScript, (New-Object Text.UTF8Encoding($false)))
& $py $tmp $cfgPath $BaseUrl $Model $ApiKey $ProviderId
Remove-Item $tmp -Force

if ($NoRestart) {
    Write-Host "已写入配置（-NoRestart，未重启）"
    exit 0
}

Write-Host "重启 AstrBot 生效 ..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\stop-all.ps1')
Start-Sleep -Seconds 2
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Get-AstrBotPath 'scripts\start-all.ps1')
Start-Sleep -Seconds 8
$conn = Get-NetTCPConnection -State Established -RemotePort 6199 -ErrorAction SilentlyContinue
if ($conn) { Write-Host "NapCat 已重连，真实模型生效。" } else { Write-Host "警告：没看到 NapCat 重连，检查 6099/6199。" }
