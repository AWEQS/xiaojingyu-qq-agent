<#
把 NapCat 的 OneBot 反向 WebSocket 客户端指向 AstrBot（Python 实现，兼容 PowerShell 5.1）

用法（NapCat 登录成功后运行）：
  powershell -NoProfile -ExecutionPolicy Bypass -File $AstrBotRoot\scripts\configure-napcat-onebot.ps1
#>

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Stop'
$py = (Get-AstrBotPath 'tools\astrbot\Scripts\python.exe')
$tmp = Join-Path $env:TEMP 'configure_napcat.py'

$code = @'
import json, pathlib, sys
cfg_dir = pathlib.Path(sys.argv[1])
url = sys.argv[2]

files = sorted(cfg_dir.glob("onebot11_*.json"))
target = files[0] if files else cfg_dir / "onebot11.json"

if target.exists():
    (target.parent / (target.name + ".bak")).write_text(target.read_text("utf-8"), encoding="utf-8")
    cfg = json.loads(target.read_text("utf-8-sig"))
else:
    cfg = {}

net = cfg.setdefault("network", {})
for k in ("httpServers", "httpSseServers", "httpClients", "websocketServers", "plugins"):
    net.setdefault(k, [])

clients = [c for c in (net.get("websocketClients") or []) if c.get("name") != "astrbot"]
clients.append({
    "name": "astrbot",
    "enable": True,
    "url": url,
    "token": "",
    "messagePostFormat": "array",
    "reportSelfMessage": False,
    "debug": False,
    "heartInterval": 30000,
    "reconnectInterval": 3000,
})
net["websocketClients"] = clients

cfg.setdefault("musicSignUrl", "")
cfg.setdefault("enableLocalFile2Url", False)
cfg.setdefault("parseMultMsg", False)
cfg.setdefault("imageDownloadProxy", "")
cfg.setdefault("timeout", {"baseTimeout": 10000, "uploadSpeedKBps": 256, "downloadSpeedKBps": 256, "maxTimeout": 1800000})

target.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
print("已写入:", target)
'@

[IO.File]::WriteAllText($tmp, $code, (New-Object Text.UTF8Encoding($false)))
& $py $tmp (Get-AstrBotPath 'napcat\config') 'ws://127.0.0.1:6199/ws'
Remove-Item $tmp -Force

Write-Host ""
Write-Host "配置已写入。重启 NapCat 生效（重启后可能需要重新扫码）。"
