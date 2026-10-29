<#
安装小鲸鱼到本机。

用法（在当前解压出来的目录里）：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1 -Target "D:\Apps\XiaoJingYu"
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1 -NoAutostart -NoDesktopShortcut

默认安装到 %LOCALAPPDATA%\Programs\XiaoJingYu（不需要管理员）。
#>
param(
    [string]$Source = '',
    [string]$Target = '',
    [switch]$NoAutostart,
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut,
    [switch]$Force
)

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Stop'

if (-not $Source) { $Source = $AstrBotRoot }
$Source = (Resolve-Path -LiteralPath $Source).Path
if (-not $Target) { $Target = Join-Path $env:LOCALAPPDATA 'Programs\XiaoJingYu' }
$Target = [System.IO.Path]::GetFullPath($Target)

$APP_NAME = '小鲸鱼'
$VERSION = '1.0.0'

function Fail([string]$msg) { Write-Host "安装失败：$msg" -ForegroundColor Red; exit 1 }

Write-Host "=== 小鲸鱼 安装程序 ===" -ForegroundColor Cyan
Write-Host "  来源: $Source"
Write-Host "  目标: $Target"

# ---- 校验来源是一个完整的包 ----
foreach ($need in @('bin\astrbot.exe', 'console\server.py', 'scripts\bootstrap.ps1')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Source $need))) {
        Fail "来源目录缺少 $need（请在完整解压后的目录里运行）"
    }
}

# ---- 防止把包装进自己里面 ----
if ($Target.TrimEnd('\').StartsWith($Source.TrimEnd('\') + '\', 'OrdinalIgnoreCase')) {
    Fail "目标目录不能位于来源目录内部"
}
if ($Target.TrimEnd('\') -eq $Source.TrimEnd('\')) {
    Fail "目标目录和来源相同，直接在这里用就行，不需要安装"
}

# ---- 已存在则要求 -Force ----
$existing = Join-Path $Target 'install.json'
if ((Test-Path -LiteralPath $Target) -and -not $Force) {
    if (Test-Path -LiteralPath $existing) {
        Fail "目标目录已安装过（$Target）。先运行 uninstall.ps1，或加 -Force 覆盖"
    }
    Fail "目标目录已存在且非空：$Target。请换目录，或先清理"
}

New-Item -ItemType Directory -Path $Target -Force | Out-Null

# ---- 复制 ----
Write-Host "`n[1/4] 复制文件（约 1.5 GB，需要几十秒）..." -ForegroundColor Yellow
$rc = Start-Process -FilePath 'robocopy.exe' -Wait -PassThru -NoNewWindow -ArgumentList @(
    "`"$Source`"", "`"$Target`"", '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1',
    '/XD', "`"$Source\dist`""
)
if ($rc.ExitCode -ge 8) { Fail "复制文件出错（robocopy exit=$($rc.ExitCode)）" }

# ---- 快捷方式 ----
Write-Host "[2/4] 创建快捷方式..." -ForegroundColor Yellow
$ws = New-Object -ComObject WScript.Shell
$exe = Join-Path $Target 'desktop\electron\electron.exe'
$appDir = Join-Path $Target 'desktop\app'
$icon = Join-Path $Target 'desktop\app\icon.ico'

function New-Lnk([string]$path) {
    $lnk = $ws.CreateShortcut($path)
    $lnk.TargetPath = $exe
    $lnk.Arguments = '"' + $appDir + '"'
    $lnk.WorkingDirectory = $appDir
    $lnk.IconLocation = $icon
    $lnk.Description = '小鲸鱼 QQ Agent 控制台'
    $lnk.Save()
}

$made = @()
if (-not $NoDesktopShortcut) {
    $p = Join-Path ([Environment]::GetFolderPath('Desktop')) "$APP_NAME.lnk"
    New-Lnk $p; $made += $p
}
if (-not $NoStartMenuShortcut) {
    $p = Join-Path ([Environment]::GetFolderPath('Programs')) "$APP_NAME.lnk"
    New-Lnk $p; $made += $p
}
if (-not $NoAutostart) {
    $p = Join-Path ([Environment]::GetFolderPath('Startup')) "$APP_NAME.lnk"
    New-Lnk $p; $made += $p
}
$made | ForEach-Object { Write-Host "  + $_" }

# ---- 注册卸载信息 ----
Write-Host "[3/4] 注册卸载项..." -ForegroundColor Yellow
$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\XiaoJingYu"
New-Item -Path $uninstallKey -Force | Out-Null
$sizeKb = [int]((Get-ChildItem -LiteralPath $Target -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
$uninstallCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Target\scripts\uninstall.ps1`""
Set-ItemProperty -Path $uninstallKey -Name DisplayName -Value "$APP_NAME QQ Agent"
Set-ItemProperty -Path $uninstallKey -Name DisplayVersion -Value $VERSION
Set-ItemProperty -Path $uninstallKey -Name Publisher -Value 'xiaojingyu'
Set-ItemProperty -Path $uninstallKey -Name InstallLocation -Value $Target
Set-ItemProperty -Path $uninstallKey -Name DisplayIcon -Value $icon
Set-ItemProperty -Path $uninstallKey -Name UninstallString -Value $uninstallCmd
Set-ItemProperty -Path $uninstallKey -Name QuietUninstallString -Value ($uninstallCmd + ' -Quiet')
Set-ItemProperty -Path $uninstallKey -Name EstimatedSize -Value $sizeKb -Type DWord
Set-ItemProperty -Path $uninstallKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $uninstallKey -Name NoRepair -Value 1 -Type DWord

# ---- 安装记录 ----
Write-Host "[4/4] 写安装记录..." -ForegroundColor Yellow
$info = [pscustomobject]@{
    app         = 'XiaoJingYu'
    name        = $APP_NAME
    version     = $VERSION
    installedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    source      = $Source
    target      = $Target
    autostart   = (-not $NoAutostart)
    shortcuts   = $made
}
$info | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $Target 'install.json') -Encoding UTF8

Write-Host ""
Write-Host "安装完成。" -ForegroundColor Green
Write-Host "  位置: $Target"
Write-Host "  启动: 桌面/开始菜单的「$APP_NAME」，或双击 $Target\首次运行.bat"
Write-Host "  卸载: 设置 → 应用 → $APP_NAME QQ Agent（或运行 $Target\scripts\uninstall.ps1）"
Write-Host ""
Write-Host "第一次启动会自动拉起控制台和守护；NapCat 需要单独装（首次运行.bat 里有入口）。" -ForegroundColor Cyan
