<#
把 dist 打成可分发压缩包（优先用 WinRAR，没有则退回 7-Zip）。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-installer.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -Level 5
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -Sfx
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -Sfx -SfxTarget "E:\_sfx-test"

说明：
- 默认先跑 build-package.ps1 重新生成 dist（-SkipBuild 跳过）
- RAR 的 -m0..-m5：存储 / 最快 / 较快 / 标准 / 较好 / 最好
- -Sfx 额外产出单文件自解压安装 EXE，双击即装
#>
param(
    [string]$Out = '',
    [int]$Level = 3,
    [switch]$SkipBuild,
    [switch]$Sfx,
    [string]$SfxTarget = '',
    [string]$Tool = 'auto'
)

. (Join-Path $PSScriptRoot '_paths.ps1')
$ErrorActionPreference = 'Stop'
$root = $AstrBotRoot
$dist = Join-Path $root 'dist'
$version = '1.0.0'
$stamp = Get-Date -Format 'yyyyMMdd'

# ---------- 选压缩工具 ----------
function Find-Rar {
    $cands = @(
        (Get-ItemProperty 'HKLM:\SOFTWARE\WinRAR' -ErrorAction SilentlyContinue).exe64,
        (Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\WinRAR' -ErrorAction SilentlyContinue).exe32,
        'D:\WinRAR\WinRAR.exe',
        "$env:ProgramFiles\WinRAR\WinRAR.exe",
        "${env:ProgramFiles(x86)}\WinRAR\WinRAR.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    foreach ($w in $cands) {
        $rar = Join-Path (Split-Path $w -Parent) 'Rar.exe'
        if (Test-Path -LiteralPath $rar) { return $rar }
    }
    return $null
}
function Find-7z {
    @(
        "$env:ProgramFiles\7-Zip\7z.exe",
        "${env:ProgramFiles(x86)}\7-Zip\7z.exe",
        'E:\点7z文件解压工具\7z.exe'
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}

$rarExe = $null; $sevenZip = $null
if ($Tool -in @('auto', 'rar')) { $rarExe = Find-Rar }
if (-not $rarExe -and $Tool -in @('auto', '7z')) { $sevenZip = Find-7z }
if (-not $rarExe -and -not $sevenZip) { throw "既没找到 Rar.exe 也没找到 7z.exe" }

if ($rarExe) {
    Write-Host "压缩工具: RAR ($rarExe)" -ForegroundColor Cyan
    if (-not $Out) { $Out = Join-Path (Split-Path $root -Parent) "小鲸鱼-$version-$stamp.rar" }
} else {
    Write-Host "压缩工具: 7-Zip ($sevenZip)" -ForegroundColor Cyan
    if (-not $Out) { $Out = Join-Path (Split-Path $root -Parent) "小鲸鱼-$version-$stamp.7z" }
}
$Out = [System.IO.Path]::GetFullPath($Out)

# ---------- 生成 dist ----------
if (-not $SkipBuild) {
    Write-Host "[1/3] 重新生成 dist ..." -ForegroundColor Yellow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'scripts\build-package.ps1') -Build | Out-Null
}
if (-not (Test-Path -LiteralPath $dist)) { throw "dist 不存在" }
if (Test-Path -LiteralPath $Out) { Remove-Item -LiteralPath $Out -Force }

# ---------- 压缩 ----------
Write-Host "[2/3] 压缩（约 1.5 GB，几分钟）..." -ForegroundColor Yellow
$sw = [Diagnostics.Stopwatch]::StartNew()
$log = New-Object System.Collections.ArrayList

if ($rarExe) {
    Push-Location $dist
    try {
        & $rarExe a -r ("-m" + $Level) -idq -y $Out '*' 2>&1 | ForEach-Object { [void]$log.Add($_) }
        $code = $LASTEXITCODE
    } finally { Pop-Location }
} else {
    & $sevenZip a -t7z -mx=$Level -mmt=on $Out (Join-Path $dist '*') 2>&1 |
        ForEach-Object { [void]$log.Add($_) }
    $code = $LASTEXITCODE
}
$sw.Stop()

if (-not (Test-Path -LiteralPath $Out)) {
    Write-Host "    压缩失败（exit=$code）：" -ForegroundColor DarkGray
    $log | Select-Object -Last 15 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    throw "压缩失败 exit=$code"
}
Write-Host ("     -> {0}" -f $Out) -ForegroundColor Green
Write-Host ("        {0:N0} MB（{1:N0}s）" -f ((Get-Item $Out).Length/1MB), $sw.Elapsed.TotalSeconds) -ForegroundColor Green

# ---------- 单文件自解压安装 EXE ----------
Write-Host "[3/3] 自解压安装 EXE ..." -ForegroundColor Yellow
if (-not $Sfx) { Write-Host "     跳过（加 -Sfx 生成）" -ForegroundColor DarkGray; return }
if (-not $rarExe) { Write-Host "     需要 WinRAR 才能做 SFX" -ForegroundColor Red; return }

$exeOut = [System.IO.Path]::ChangeExtension($Out, '.exe')
$installArgs = 'scripts\install.ps1'
if ($SfxTarget) { $installArgs += " -Target `"$SfxTarget`"" }
$sfxScript = @"
;小鲸鱼 安装程序
Setup=powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installArgs
TempMode
Silent=1
Overwrite=1
"@
$sfxCfg = Join-Path $env:TEMP 'xiaojingyu-sfx.txt'
[System.IO.File]::WriteAllText($sfxCfg, $sfxScript, (New-Object System.Text.UTF8Encoding($false)))

$sw2 = [Diagnostics.Stopwatch]::StartNew()
Push-Location $dist
try {
    & $rarExe a -sfx -r ("-m" + $Level) -idq -y -z"$sfxCfg" $exeOut '*' 2>&1 | ForEach-Object { [void]$log.Add($_) }
    $code2 = $LASTEXITCODE
} finally { Pop-Location }
$sw2.Stop()
if (-not (Test-Path -LiteralPath $exeOut)) {
    $log | Select-Object -Last 15 | ForEach-Object { Write-Host "      $_" -ForegroundColor DarkGray }
    throw "SFX 生成失败 exit=$code2"
}
Write-Host ("     -> {0}" -f $exeOut) -ForegroundColor Green
Write-Host ("        {0:N0} MB（{1:N0}s）" -f ((Get-Item $exeOut).Length/1MB), $sw2.Elapsed.TotalSeconds) -ForegroundColor Green
Write-Host ""
Write-Host "双击该 EXE 即安装（默认 %LOCALAPPDATA%\Programs\XiaoJingYu）" -ForegroundColor Cyan
