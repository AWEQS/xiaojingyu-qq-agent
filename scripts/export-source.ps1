<#
导出一份可以公开的源码目录（不含第三方二进制、表情图、运行时数据）。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export-source.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export-source.ps1 -Out D:\src\xiaojingyu -Init

说明：
- 只导出「能重建本项目」的源码：控制台、桌面壳、自研插件、脚本、文档
- 排除：tools\（Python 环境）、python\、napcat\、desktop\electron\、bin\ffmpeg.exe、
        data\plugin_data\、表情图片、插件运行时状态、mock\、dist\
- -Init 会在目标目录 git init 并提交（已存在 .git 则跳过）
#>
param(
    [string]$Out = 'E:\_public-src',
    [switch]$Init,
    [switch]$Force
)

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Stop'
$root = $AstrBotRoot
$Out = [System.IO.Path]::GetFullPath($Out)

if (Test-Path -LiteralPath $Out) {
    if (-not $Force) { throw "目标已存在：$Out（加 -Force 覆盖）" }
    # 保留 .git：每次更新源码不该丢掉提交历史
    Get-ChildItem -LiteralPath $Out -Force |
        Where-Object { $_.Name -ne '.git' } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}
New-Item -ItemType Directory -Path $Out -Force | Out-Null

# ---- 1. 顶层文件 ----
foreach ($f in @('README.md', 'NOTICE.txt', 'LICENSE', '.gitignore')) {
    $p = Join-Path $root $f
    if (Test-Path -LiteralPath $p) { Copy-Item $p -Destination $Out -Force }
}

# ---- 2. 源码目录 ----
$dirs = @('scripts', 'console', 'persona-pack', 'plugins-src', 'docs')
foreach ($d in $dirs) {
    $p = Join-Path $root $d
    if (Test-Path -LiteralPath $p) {
        Copy-Item $p -Destination $Out -Recurse -Force
    }
}
# 桌面壳只取 app（不要 electron 运行时）
$app = Join-Path $root 'desktop\app'
if (Test-Path -LiteralPath $app) {
    New-Item -ItemType Directory -Path (Join-Path $Out 'desktop') -Force | Out-Null
    Copy-Item $app -Destination (Join-Path $Out 'desktop') -Recurse -Force
}

# ---- 3. 插件（只取代码与静态定义）----
$plugSrc = Join-Path $root 'data\plugins'
$plugDst = Join-Path $Out 'data\plugins'
if (Test-Path -LiteralPath $plugSrc) {
    New-Item -ItemType Directory -Path $plugDst -Force | Out-Null
    $skipDirNames = @('memory', 'chat_images', 'history', 'pending', 'trash', '__pycache__', 'logs')
    Get-ChildItem -LiteralPath $plugSrc -Directory | ForEach-Object {
        $name = $_.Name
        $dest = Join-Path $plugDst $name
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
        Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force | ForEach-Object {
            $rel = $_.FullName.Substring($_.FullName.IndexOf($name) + $name.Length).TrimStart('\')
            # 排除运行时数据与第三方素材
            if ($_.Extension -in @('.jpg', '.jpeg', '.png', '.gif', '.webp') -and $rel -match '^stickers\\') { return }
            if ($rel -match '(^|\\)(memory|chat_images|logs)\\') { return }
            if ($rel -match '(^|\\)\.(history|pending|trash)\\') { return }
            if ($rel -match '(^|\\)__pycache__(\\|$)') { return }
            if ($_.Name -match '^(state|groups|chat_history|chat_images|relationship|daily_state|life_timeline|bot_history|signature_state|qzone_post_state|proactive_state|proactive_overrides|weather_state|policy)\.json$') { return }
            if ($_.Extension -in @('.db', '.log')) { return }
            $target = Join-Path $dest $rel
            $dir = Split-Path $target -Parent
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}

# ---- 3.5 剔除开发截图（可能含真实群号/QQ 号）----
# 注意：-Include 与 -LiteralPath 同用会被 PowerShell 忽略（会误删全部文件），必须用 Where-Object 过滤
$pruned = 0
Get-ChildItem -LiteralPath $Out -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\\.git\\' -and ($_.Name -like 'preview*.png' -or $_.Name -like 'preview*.jpg') } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; $pruned++ }
if ($pruned -gt 0) { Write-Host "已剔除开发截图 $pruned 张（可能含真实号码）" -ForegroundColor Yellow }

# ---- 3.6 剔除所有表情图片（任何目录下的 stickers\，含 plugins-src 的开发副本）----
$pruned2 = 0
Get-ChildItem -LiteralPath $Out -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @('.jpg', '.jpeg', '.png', '.gif', '.webp') -and $_.FullName -match '\\stickers\\' } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; $pruned2++ }
if ($pruned2 -gt 0) { Write-Host "已剔除表情图片 $pruned2 张（版权不明，不公开）" -ForegroundColor Yellow }

# ---- 4. 统计 ----
$files = Get-ChildItem -LiteralPath $Out -Recurse -Force -File | Where-Object { $_.FullName -notmatch '\\\.git\\' }
$size = ($files | Measure-Object Length -Sum).Sum
Write-Host ("导出完成: {0}" -f $Out) -ForegroundColor Green
Write-Host ("  {0} 个文件 / {1:N1} MB" -f $files.Count, ($size / 1MB))
Write-Host ""
Write-Host "按顶层目录：" -ForegroundColor Cyan
$files | Group-Object { ($_.FullName.Substring($Out.Length).TrimStart('\') -split '\\')[0] } |
    ForEach-Object {
        [pscustomobject]@{ MB = [math]::Round((($_.Group | Measure-Object Length -Sum).Sum) / 1MB, 1); 文件 = $_.Count; 目录 = $_.Name }
    } | Sort-Object MB -Descending | Format-Table -AutoSize | Out-String | Write-Host

# ---- 5. 可选：初始化 git ----
if ($Init) {
    $git = 'E:\_tools\PortableGit\cmd\git.exe'
    if (-not (Test-Path $git)) { $git = 'git' }
    if (-not (Test-Path (Join-Path $Out '.git'))) {
        & $git -C $Out init | Out-Null
        & $git -C $Out config core.autocrlf false
        & $git -C $Out add -A
        & $git -C $Out -c user.name='xiaojingyu' -c user.email='dev@localhost' commit -q -m '小鲸鱼 QQ Agent 源码（AGPL-3.0-or-later）' | Out-Null
        Write-Host "已初始化 git 仓库并提交" -ForegroundColor Green
        & $git -C $Out log --oneline
    }
}
