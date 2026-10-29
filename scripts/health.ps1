<#
健康探测：一次性检查所有关键组件，输出表格或 JSON。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\health.ps1          # 表格
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\health.ps1 -Json    # JSON（给守护/控制台用）

退出码：0 = ok，1 = degraded（部分不可用），2 = down（核心不可用）
#>
param(
    [switch]$Json
)

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'SilentlyContinue'
$root = $AstrBotRoot

function Test-Port([int]$p) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue)
}

$comps = New-Object System.Collections.ArrayList
function Add-Comp([string]$key, [string]$name, [bool]$ok, [string]$detail, [bool]$critical) {
    [void]$comps.Add([pscustomobject]@{ key = $key; name = $name; ok = $ok; detail = $detail; critical = $critical })
}

# ---- 文件完整性 ----
$python  = Join-Path $root 'tools\astrbot\Scripts\python.exe'
$astrbot = Join-Path $root 'bin\astrbot.exe'
Add-Comp 'python'  'Python 运行时'  (Test-Path $python)  $(if (Test-Path $python) { 'ok' } else { '缺失' }) $true
Add-Comp 'core'    'AstrBot 主程序' (Test-Path $astrbot) $(if (Test-Path $astrbot) { 'ok' } else { '缺失' }) $true

# ---- 控制台（端口 + HTTP 200）----
$consoleOk = $false
$consoleDetail = '未运行'
if (Test-Port 8787) {
    try {
        $r = Invoke-WebRequest 'http://127.0.0.1:8787/' -UseBasicParsing -TimeoutSec 5
        $consoleOk = ($r.StatusCode -eq 200)
        $consoleDetail = "HTTP $($r.StatusCode)"
    } catch { $consoleDetail = '端口在听但 HTTP 无响应' }
} 
Add-Comp 'console' '控制台 8787' $consoleOk $consoleDetail $false

# ---- AstrBot / OneBot / NapCat 端口 ----
$astrbotOk = Test-Port 6185
Add-Comp 'astrbot' 'AstrBot 6185' $astrbotOk $(if ($astrbotOk) { 'listening' } else { '未运行' }) $true
$onebotOk = Test-Port 6199
Add-Comp 'onebot' 'OneBot 6199' $onebotOk $(if ($onebotOk) { 'listening' } else { '未运行' }) $false
$napcatOk = Test-Port 6099
Add-Comp 'napcat' 'NapCat 6099' $napcatOk $(if ($napcatOk) { 'listening' } else { '未运行' }) $false

# ---- QQ 登录态（NapCat 本地 HTTP）----
$qq = $null
if (Test-Port 6198) {
    try {
        $resp = Invoke-RestMethod 'http://127.0.0.1:6198/get_login_info' -Method Post -Body '{}' -ContentType 'application/json' -TimeoutSec 5
        if ($resp.retcode -eq 0 -and $resp.data) {
            $qq = [pscustomobject]@{
                logged_in = $true
                nickname  = [string]$resp.data.nickname
                user_id   = [string]$resp.data.user_id
            }
        }
    } catch { }
}
if ($null -eq $qq) { $qq = [pscustomobject]@{ logged_in = $false; nickname = ''; user_id = '' } }
Add-Comp 'qq' 'QQ 登录' $qq.logged_in $(if ($qq.logged_in) { "$($qq.nickname) ($($qq.user_id))" } else { '未登录或查询失败' }) $false

# ---- 汇总 ----
$down = @($comps | Where-Object { $_.critical -and -not $_.ok })
$degraded = @($comps | Where-Object { -not $_.critical -and -not $_.ok })
$verdict = if ($down.Count -gt 0) { 'down' } elseif ($degraded.Count -gt 0) { 'degraded' } else { 'ok' }

$payload = [pscustomobject]@{
    ts         = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    verdict    = $verdict
    root       = $root
    components = @($comps)
    qq         = $qq
    problems   = @(@($down + $degraded) | ForEach-Object { $_.name })
}

if ($Json) {
    $payload | ConvertTo-Json -Depth 5 -Compress
} else {
    Write-Host ""
    Write-Host ("小鲸鱼健康检查  " + (Get-Date -Format 'HH:mm:ss') + "  结论: " + $verdict.ToUpper()) -ForegroundColor $(if ($verdict -eq 'ok') { 'Green' } elseif ($verdict -eq 'degraded') { 'Yellow' } else { 'Red' })
    $comps | Select-Object @{n='组件';e={$_.name}}, @{n='状态';e={ if ($_.ok) { 'OK' } else { 'DOWN' } }}, detail |
        Format-Table -AutoSize | Out-String | Write-Host
    if ($qq.logged_in) { Write-Host ("QQ: {0} ({1})" -f $qq.nickname, $qq.user_id) -ForegroundColor Green }
}

exit $(switch ($verdict) { 'ok' { 0 } 'degraded' { 1 } default { 2 } })
