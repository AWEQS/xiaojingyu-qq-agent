#requires -Version 5.1
<#
.SYNOPSIS
    生成「可发布」的干净副本，并报告真实体积。

.DESCRIPTION
    从项目根（scripts 的上一级）复制到 dist，跳过运行数据、登录态、日志、缓存。
    默认只分析不复制（-List）。加 -Build 才真正写盘。

    注意：脚本不会替你判定"是否合规"。NapCat/QQ 客户端默认被排除（不可再分发），
    如确实需要随包，显式加 -IncludeNapCat 并自行承担风险。

.PARAMETER List
    只分析：打印每个大项的体积与排除原因，不写任何文件。

.PARAMETER Build
    真正复制到 -Out 目录（会先清空该目录）。

.PARAMETER Out
    输出目录，默认 <项目根>\dist。

.PARAMETER IncludeNapCat
    连同 NapCat 运行时一起复制（不含 QQ 客户端 qq-9.9.33，那个始终排除）。

.EXAMPLE
    .\build-package.ps1 -List

.EXAMPLE
    .\build-package.ps1 -Build -Out D:\tmp\xiaojingyu-dist
#>
param(
    [switch]$List,
    [switch]$Build,
    [string]$Out,
    [switch]$IncludeNapCat
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_paths.ps1')

$Root = $AstrBotRoot
if (-not $Out) { $Out = Join-Path $Root 'dist' }
if (-not $List -and -not $Build) { $List = $true }

# ---- 排除规则（相对项目根，前缀匹配，不区分大小写）----
$ExcludeDirs = @(
    'dist',
    '.git',
    'cache',                       # uv 构建缓存
    'napcat\qq-data',              # QQ 登录态
    'napcat\cache',
    'napcat\logs',
    'napcat\qq-9.9.33',            # 腾讯 QQ 客户端：不可再分发
    'napcat-installer',            # NapCat 安装器：让用户自行下载
    'mock\edge-profile-dbl',       # 联调时留下的浏览器配置
    'mock\edge-profile-final',
    'data\backups',
    'data\attachments',
    'data\plugin_data',
    'data\console',
    'data\config',
    'data\knowledge_base',
    'mock',                        # 联调测试工具，不随发布包分发
    'llama'                        # 早期本地模型实验遗留
)
if (-not $IncludeNapCat) {
    $ExcludeDirs += 'napcat'
}
$ExcludeFiles = @(
    'data\cmd_config.json',        # 含模型 API Key
    'data\data_v4.db',             # AstrBot 主库：含对话/会话记录
    'desktop\settings.json',
    'desktop\shell.log',
    'desktop\shell-script.out.log',
    'desktop\launch.out.log',
    'desktop\launch.err.log'
)
$ExcludeExtensions = @('.log', '.pyc')

# 插件目录里的「运行时状态」——含聊天记录、群号、档案，绝不能进发布包
$ExcludePatterns = @(
    '^data\\plugins\\[^\\]+\\memory\\',
    '^data\\plugins\\[^\\]+\\chat_images\\',
    '^data\\plugins\\[^\\]+\\personas\\\.(history|pending)\\',
    '^data\\plugins\\[^\\]+\\(state|groups|chat_history|relationship|daily_state|life_timeline|bot_history|signature_state|qzone_post_state|proactive_overrides|proactive_state)\.json$',
    '^data\\plugins\\[^\\]+\\stickers\\\.trash\\',
    '^data\\plugins\\astrbot_plugin_sticker_pack\\stickers\\',   # 第三方梗图版权不明，不随包分发（出厂留空，用户自己导入）
    '^data\\plugins\\[^\\]+\\(weather_state|policy)\.json$',
    '^data\\plugins\\[^\\]+\\[^\\]*_state\.json$'
)

function Test-Excluded([string]$rel) {
    foreach ($p in $ExcludeFiles) { if ($rel -eq $p) { return "文件排除: $p" } }
    foreach ($d in $ExcludeDirs) {
        if ($rel -eq $d -or $rel.StartsWith($d + '\')) { return "目录排除: $d" }
    }
    foreach ($pat in $ExcludePatterns) {
        if ($rel -match $pat) { return "运行时数据: " + ($rel -split '\\')[-1] }
    }
    foreach ($e in $ExcludeExtensions) { if ($rel.EndsWith($e)) { return "类型排除: $e" } }
    if ($rel -match '(^|\\)__pycache__(\\|$)') { return "缓存: __pycache__" }
    if ($rel -match '\\run-\w+\.log$') { return "日志" }
    return $null
}

Write-Host "项目根: $Root"
Write-Host "模式  : $(if ($Build) { 'BUILD -> ' + $Out } else { 'LIST（只分析）' })"
Write-Host ""

$all = Get-ChildItem -LiteralPath $Root -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "$Out\*" }

$keep = New-Object System.Collections.ArrayList
$skip = @{}
$skipBytes = 0L

foreach ($f in $all) {
    $rel = $f.FullName.Substring($Root.Length).TrimStart('\')
    $reason = Test-Excluded $rel
    if ($reason) {
        $skipBytes += $f.Length
        $key = ($reason -split ': ')[1]
        if (-not $skip.ContainsKey($key)) { $skip[$key] = @{ Bytes = 0L; Count = 0 } }
        $skip[$key].Bytes += $f.Length
        $skip[$key].Count++
    } else {
        [void]$keep.Add($f)
    }
}

$keepBytes = ($keep | Measure-Object Length -Sum).Sum
if (-not $keepBytes) { $keepBytes = 0 }

Write-Host "=== 保留 ==="
Write-Host ("  {0,8:N2} GB / {1,7} 文件" -f ($keepBytes / 1GB), $keep.Count)
Write-Host ""
Write-Host "=== 排除 ==="
$skip.GetEnumerator() | Sort-Object { $_.Value.Bytes } -Descending | ForEach-Object {
    Write-Host ("  {0,8:N1} MB / {1,6} 文件  {2}" -f ($_.Value.Bytes / 1MB), $_.Value.Count, $_.Name)
}
Write-Host ("  {0,8:N2} GB 合计排除" -f ($skipBytes / 1GB))

# ---- 按顶层目录汇总保留内容 ----
Write-Host ""
Write-Host "=== 保留内容分布 ==="
$keep | Group-Object { ($_.FullName.Substring($Root.Length).TrimStart('\') -split '\\')[0] } |
    ForEach-Object {
        $b = ($_.Group | Measure-Object Length -Sum).Sum
        [pscustomobject]@{ MB = [math]::Round($b / 1MB, 1); Files = $_.Count; Dir = $_.Name }
    } | Sort-Object MB -Descending | Format-Table -AutoSize | Out-String | Write-Host

# ---- 敏感残留扫描 ----
Write-Host "=== 敏感残留扫描（发布前必须人工确认）==="
$risky = $keep | Where-Object {
    $_.Name -in @('cmd_config.json', 'state.json', 'groups.json', 'chat_history.json',
                  'relationship.json', 'daily_state.json', 'life_timeline.json',
                  'bot_history.json', 'signature_state.json', 'qzone_post_state.json') -or
    $_.Extension -in @('.db', '.sqlite', '.jsonl')
}
if ($risky) {
    $risky | Group-Object { $_.DirectoryName.Substring($Root.Length).TrimStart('\') } |
        ForEach-Object { "  {0} 个文件  {1}" -f $_.Count, $_.Name } | Write-Host
    Write-Host "  ^ 这些含聊天记录/QQ 号/Key，发布前请逐个确认或手工删除" -ForegroundColor Yellow
} else {
    Write-Host "  未发现" -ForegroundColor Green
}

if (-not $Build) {
    Write-Host ""
    Write-Host "（LIST 模式未写盘。确认后运行： .\build-package.ps1 -Build）" -ForegroundColor Cyan
    return
}

# ---- 真正复制 ----
if (Test-Path -LiteralPath $Out) {
    Write-Host "清空旧输出: $Out" -ForegroundColor Yellow
    Remove-Item -LiteralPath $Out -Recurse -Force
}
New-Item -ItemType Directory -Path $Out -Force | Out-Null

$copied = 0
foreach ($f in $keep) {
    $rel = $f.FullName.Substring($Root.Length).TrimStart('\')
    $dst = Join-Path $Out $rel
    $dstDir = Split-Path $dst -Parent
    if (-not (Test-Path -LiteralPath $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
    Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
    $copied++
}

# ---- 出厂 data 骨架 ----
foreach ($d in @('data', 'data\config', 'data\plugin_data', 'data\console', 'data\backups')) {
    $p = Join-Path $Out $d
    if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
$note = @'
# 出厂数据目录（首次运行自动填充）

本目录下的运行时数据在发布包中是空的，程序首次启动会自行创建：

- `config/`        AstrBot 配置（含模型 Key，用户自己填）
- `plugin_data/`   各插件记忆、日记、星图数据库
- `console/`       控制台状态
- `backups/`       自动备份

如果要打包给你自己备份，请不要把这些目录放进公开分发包。
'@
[System.IO.File]::WriteAllText((Join-Path $Out 'data\README.txt'), $note, (New-Object System.Text.UTF8Encoding($false)))

# ---- 出厂表情库留空（版权原因）----
$stickerDir = Join-Path $Out 'data\plugins\astrbot_plugin_sticker_pack\stickers'
New-Item -ItemType Directory -Path $stickerDir -Force | Out-Null
[System.IO.File]::WriteAllText((Join-Path $stickerDir 'index.json'), '[]', (New-Object System.Text.UTF8Encoding($false)))
$stickerNote = @'
# 表情库（出厂为空）

这里没有预置任何图片，是因为表情包多为网络/群内流传的梗图，版权归属不明，
随安装包分发属于再发行，有法律风险。所以留空，由使用者自己导入。

## 怎么加

1. 打开控制台 → 表情包 → 「+ 上传表情」（支持多选、拖拽、导入文件夹）
2. 可以勾选 AI 自动识别标签，上传前也能改描述
3. 每张图会写进 index.json，插件热重载，不用重启

## 想搬自己的旧表情库

把旧机器上的 `stickers\*.jpg|png|gif|webp` 连同 `index.json` 一起拷进本目录即可。
注意：只搬你自己有权利的图。
'@
[System.IO.File]::WriteAllText((Join-Path $stickerDir 'README.txt'), $stickerNote, (New-Object System.Text.UTF8Encoding($false)))

# ---- 生成启动器（ASCII 内容，避免 bat 编码问题）----
$launchers = [ordered]@{
    '首次运行.bat'   = 'bootstrap.ps1'
    '启动控制台.bat' = 'start-console.ps1'
    '停止服务.bat'   = 'stop-all.ps1'
    '守护服务.bat'   = 'watchdog.ps1'
    '安装.bat'       = 'install.ps1'
    '卸载.bat'       = 'uninstall.ps1'
}
foreach ($name in $launchers.Keys) {
    $body = "@echo off`r`nchcp 65001 >nul`r`ncd /d `"%~dp0`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0scripts\$($launchers[$name])`"`r`necho.`r`npause`r`n"
    [System.IO.File]::WriteAllText((Join-Path $Out $name), $body, (New-Object System.Text.UTF8Encoding($false)))
}
Write-Host "已生成启动器: $($launchers.Keys -join ', ')"

$outStat = Get-ChildItem -LiteralPath $Out -Recurse -Force -File | Measure-Object Length -Sum
Write-Host ""
Write-Host ("完成: {0}" -f $Out) -ForegroundColor Green
Write-Host ("  {0,8:N2} GB / {1} 文件（源 {2} 文件）" -f ($outStat.Sum / 1GB), $outStat.Count, $copied)
