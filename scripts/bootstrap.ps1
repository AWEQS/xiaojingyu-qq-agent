<#
首次运行检查与引导。可在源码目录或 dist 发布目录下直接运行。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1          交互式引导
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -Check   只体检（缺失项 > 0 时退出码非 0）
#>
param(
    [switch]$Check
)

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Continue'
$root = $AstrBotRoot

function Test-Port([int]$p) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
}

$items = New-Object System.Collections.ArrayList
function Add-Item([string]$name, [bool]$ok, [string]$detail, [string]$fix) {
    [void]$items.Add([pscustomobject]@{
        项目 = $name
        状态 = $(if ($ok) { 'OK' } else { '缺失' })
        说明 = $detail
        修复 = $(if ($ok) { '' } else { $fix })
    })
}

# ---- 1. 运行时与主程序 ----
$python  = Join-Path $root 'tools\astrbot\Scripts\python.exe'
$astrbot = Join-Path $root 'bin\astrbot.exe'
$server  = Join-Path $root 'console\server.py'
Add-Item 'Python 运行时'  (Test-Path $python)  $(if (Test-Path $python) { '已就绪' } else { '未找到' }) '安装包不完整，请重新解压'
Add-Item 'AstrBot 主程序' (Test-Path $astrbot) $(if (Test-Path $astrbot) { '已就绪' } else { '未找到' }) '安装包不完整，请重新解压'
Add-Item '控制台'         (Test-Path $server)  $(if (Test-Path $server) { '已就绪' } else { '未找到' }) '安装包不完整，请重新解压'

# ---- 2. NapCat 协议端 ----
$napcat = Join-Path $root 'napcat'
$napcatOk = (Test-Path (Join-Path $napcat 'NapCatWinBootMain.exe')) -or (Test-Path (Join-Path $napcat 'napcat.mjs'))
Add-Item 'NapCat 协议端' $napcatOk $(if ($napcatOk) { '已安装' } else { '未安装' }) '运行 scripts\install-napcat.ps1 下载安装（约 1.5 GB）'

# ---- 3. OneBot 配置 ----
$onebot = @(Get-ChildItem (Join-Path $napcat 'config') -Filter 'onebot11_*.json' -ErrorAction SilentlyContinue)
Add-Item 'OneBot 连接配置' ($onebot.Count -gt 0) $(if ($onebot.Count) { $onebot[0].Name } else { '未生成' }) 'QQ 登录后运行 scripts\post-login-setup.ps1'

# ---- 4. 模型 Key ----
# 注意：AstrBot 不把 Key 明文放在 cmd_config.json 里，无法直接判定。
# 代理判断：有 provider 定义且 AstrBot 在跑，就认为已配置。
$cfgPath = Join-Path $root 'data\cmd_config.json'
$astrbotUp = [bool](Get-NetTCPConnection -State Listen -LocalPort 6185 -ErrorAction SilentlyContinue)
$hasProvider = $false
$modelText = '未配置'
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $prov = @($cfg.provider)
        $hasProvider = $prov.Count -gt 0
        if ($hasProvider) { $modelText = ($prov | ForEach-Object { "$($_.id)/$($_.model)" }) -join ', ' }
    } catch { $modelText = '配置读取失败' }
}
$keyOk = $hasProvider -and $astrbotUp
if ($keyOk) { $modelText = "$modelText（AstrBot 运行中）" }
Add-Item '模型 Key' $keyOk $modelText '控制台 -> 管理端 -> 模型管理，填入 API Key'

# ---- 5. 服务端口 ----
$svc = [ordered]@{ '控制台 8787' = 8787; 'AstrBot 6185' = 6185; 'OneBot 6199' = 6199; 'NapCat 6099' = 6099 }
foreach ($k in $svc.Keys) {
    $listening = Test-Port $svc[$k]
    Add-Item $k $listening $(if ($listening) { '正在运行' } else { '未运行' }) '启动后自动监听'
}

# ---- 输出 ----
Write-Host ""
Write-Host "================ 小鲸鱼 QQ Agent · 首次运行检查 ================" -ForegroundColor Cyan
Write-Host "安装目录: $root"
Write-Host ""
$items | Format-Table -AutoSize | Out-String | Write-Host

$blocking = @($items | Where-Object { $_.状态 -ne 'OK' -and $_.项目 -in @('Python 运行时', 'AstrBot 主程序', '控制台') })
$missing   = @($items | Where-Object { $_.状态 -ne 'OK' -and $_.项目 -notin @('Python 运行时', 'AstrBot 主程序', '控制台') -and $_.项目 -notmatch '^(控制台 8787|AstrBot 6185|OneBot 6199|NapCat 6099)$' })

if ($blocking.Count -gt 0) {
    Write-Host "安装包不完整，无法继续：" -ForegroundColor Red
    $blocking | ForEach-Object { Write-Host ("  - {0}: {1}" -f $_.项目, $_.说明) }
    exit 2
}

if ($missing.Count -eq 0) {
    Write-Host "环境完整，可以启动。" -ForegroundColor Green
} else {
    Write-Host "还需要完成：" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host ("  - {0} -> {1}" -f $_.项目, $_.修复) }
}

if ($Check) {
    exit $(if ($missing.Count -eq 0) { 0 } else { 1 })
}

# ---- 交互菜单 ----
while ($true) {
    Write-Host ""
    Write-Host "[1] 安装 NapCat 协议端   [2] 打开控制台填 Key   [3] 启动全部服务   [4] 启动守护   [0] 退出"
    $choice = Read-Host "请选择"
    switch ($choice) {
        '1' {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\install-napcat.ps1')
            break
        }
        '2' {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\start-console.ps1')
            break
        }
        '3' {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\start-all.ps1')
            break
        }
        '4' {
            $wd = Join-Path $root 'scripts\watchdog.ps1'
            Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', "`"$wd`""
            )
            Write-Host "守护已在后台启动（每 60 秒体检一次，只监控不重启）" -ForegroundColor Green
            break
        }
        '0' { return }
        default { Write-Host "无效选项" -ForegroundColor Red }
    }
}
