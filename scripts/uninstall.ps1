<#
卸载小鲸鱼。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -KeepData
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -Purge -Quiet

默认：停止服务、删快捷方式、删卸载项、删程序文件，但保留 data\ 和 napcat\qq-data（聊天记录与登录态）。
-pPurge：连数据一起删。
#>
param(
    [switch]$KeepData,
    [switch]$Purge,
    [switch]$Quiet,
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
$target = Split-Path -Parent $PSScriptRoot
$APP_NAME = '小鲸鱼'

function Say([string]$m) { if (-not $Quiet) { Write-Host $m } }

if ($Purge) { $KeepData = $false }

# ---- 安全闸：只允许卸载真正的安装目录 ----
$installInfo = Join-Path $target 'install.json'
if (-not (Test-Path -LiteralPath $installInfo) -and -not $Force) {
    Write-Host "这不是一个安装目录（找不到 install.json）：$target" -ForegroundColor Red
    Write-Host "如果确认要删，加 -Force。当前目录看起来像开发目录，直接删会丢源码。" -ForegroundColor Yellow
    exit 1
}

Say "=== 卸载 $APP_NAME ==="
Say "  目录: $target"

# ---- 1. 先停守护，否则它会把服务又拉起来 ----
Say "[1/5] 停止守护..."
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'powershell.exe' -and $_.CommandLine -like "*$target\scripts\watchdog.ps1*"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Say "  - watchdog PID $($_.ProcessId)"
}
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('powershell.exe', 'pwsh.exe') -and
    $_.CommandLine -like "*$target\scripts\health.ps1*"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# ---- 2. 停服务 ----
Say "[2/5] 停止服务..."
$stopAll = Join-Path $target 'scripts\stop-all.ps1'
if (Test-Path -LiteralPath $stopAll) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stopAll 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

# ---- 3. 清理残留进程（只杀可执行文件在本目录下的）----
Say "[3/5] 结束残留进程..."
Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($target, 'OrdinalIgnoreCase')
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Say "  - $($_.Name) PID $($_.ProcessId)"
}
Start-Sleep -Seconds 1

# ---- 4. 快捷方式 + 卸载项 ----
Say "[4/5] 删除快捷方式与卸载项..."
$ws = New-Object -ComObject WScript.Shell
$lnkDirs = @(
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('Programs'),
    [Environment]::GetFolderPath('Startup')
)
foreach ($dir in $lnkDirs) {
    $lnk = Join-Path $dir "$APP_NAME.lnk"
    if (-not (Test-Path -LiteralPath $lnk)) { continue }
    # 只删指向本安装目录的，避免误删开发目录的快捷方式
    $pointsHere = $false
    try { $pointsHere = $ws.CreateShortcut($lnk).TargetPath.StartsWith($target, 'OrdinalIgnoreCase') } catch { }
    if ($pointsHere) {
        Remove-Item -LiteralPath $lnk -Force
        Say "  - $lnk"
    } else {
        Say "  ! 跳过（指向别处）: $lnk"
    }
}

$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\XiaoJingYu"
if (Test-Path $uninstallKey) {
    Remove-Item -Path $uninstallKey -Recurse -Force
    Say "  - 注册表卸载项"
}

# ---- 5. 删文件 ----
Say "[5/5] 删除程序文件..."
if ($KeepData) {
    # 保留 scripts\ 是为了「以后再跑一次 -Purge」——否则脚本自己都被删了，就再也清不掉
    $keep = @('data', 'napcat', 'install.json', 'scripts')
    Get-ChildItem -LiteralPath $target -Force | Where-Object { $_.Name -notin $keep } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    # napcat 里只留登录态 qq-data，其余是 1 GB 多的运行时
    $napcatDir = Join-Path $target 'napcat'
    if (Test-Path -LiteralPath $napcatDir) {
        Get-ChildItem -LiteralPath $napcatDir -Force | Where-Object { $_.Name -ne 'qq-data' } | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Say "  已保留: data\（聊天记录/档案）、napcat\qq-data\（QQ 登录态）、scripts\（用于再次清理）"
    Say "  彻底清理请再运行：scripts\uninstall.ps1 -Purge"
} else {
    $parent = Split-Path -Parent $target
    Set-Location $parent
    Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue
    Say "  已删除整个目录"
}

Say ""
if (Test-Path -LiteralPath $target) {
    Say "卸载完成（目录仍有残留：$target）" -ForegroundColor Yellow
} else {
    Say "卸载完成。" -ForegroundColor Green
}
