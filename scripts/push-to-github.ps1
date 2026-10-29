<#
把小鲸鱼源码推送到 GitHub（自动建仓库、建远端、推送）。

用法（token 只在本机使用，不会写进仓库）：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\push-to-github.ps1 -Token "ghp_xxx"
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\push-to-github.ps1 -Token "ghp_xxx" -Repo "xiaojingyu-qq-agent" -Private

参数：
  -Token    GitHub Personal Access Token（需要 repo 权限；fine-grained token 需要
            Contents: Read/Write + Administration: Read/Write）
  -Repo     仓库名，默认 xiaojingyu-qq-agent
  -User     你的 GitHub 用户名；不填会从 token 自动查询
  -Private  建私有仓库（默认公开）
  -Src      要推送的目录，默认 E:\_public-src（先跑 export-source.ps1 生成）
  -DryRun   只打印将要执行的步骤
#>
param(
    [Parameter(Mandatory = $true)][string]$Token,
    [string]$User = '',
    [string]$Repo = 'xiaojingyu-qq-agent',
    [switch]$Private,
    [string]$Src = 'E:\_public-src',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$git = 'E:\_tools\PortableGit\cmd\git.exe'
if (-not (Test-Path $git)) { $git = 'git' }

if (-not (Test-Path (Join-Path $Src '.git'))) { throw "目标不是 git 仓库：$Src（先跑 export-source.ps1 -Init）" }

$headers = @{
    Authorization          = "Bearer $Token"
    'User-Agent'           = 'xiaojingyu-publish'
    Accept                 = 'application/vnd.github+json'
}

Write-Host "[1/4] 校验 token ..." -ForegroundColor Yellow
try {
    $me = Invoke-RestMethod 'https://api.github.com/user' -Headers $headers -TimeoutSec 30
} catch {
    Write-Host "      令牌校验失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "      检查：令牌是否复制完整、是否过期、网络是否能访问 api.github.com" -ForegroundColor Yellow
    throw "令牌无效"
}
if (-not $User) { $User = $me.login }
Write-Host "      已登录为: $User"

Write-Host "[2/4] 检查仓库 $User/$Repo ..." -ForegroundColor Yellow
$exists = $true
try { $null = Invoke-RestMethod "https://api.github.com/repos/$User/$Repo" -Headers $headers -TimeoutSec 30 }
catch { $exists = $false }

if (-not $exists) {
    Write-Host "      不存在，创建 ..."
    $body = @{ name = $Repo; private = [bool]$Private; description = '小鲸鱼 QQ Agent — 有活人感的 QQ 群聊机器人（AGPL-3.0）'; has_issues = $true } | ConvertTo-Json
    if (-not $DryRun) {
        try {
            $created = Invoke-RestMethod "https://api.github.com/user/repos" -Method Post -Headers $headers -Body $body -ContentType 'application/json' -TimeoutSec 60
            Write-Host "      已创建: $($created.html_url)"
        } catch {
            Write-Host "      自动建仓库失败：$($_.Exception.Message)" -ForegroundColor Red
            Write-Host "      手动补救：打开 https://github.com/new 建一个名为 $Repo 的空仓库（不要勾 README/.gitignore），" -ForegroundColor Yellow
            Write-Host "      然后再跑一次本脚本即可（会直接推送）。" -ForegroundColor Yellow
            throw "建仓库失败"
        }
    } else { Write-Host "      (DryRun) 会创建" }
} else {
    Write-Host "      已存在，直接推送"
}

Write-Host "[3/4] 配置远端 ..." -ForegroundColor Yellow
$remote = "https://github.com/$User/$Repo.git"
if ($DryRun) {
    Write-Host "      (DryRun) remote = $remote"
} else {
    # 首次没有 origin，直接 remove 会报错（且 Stop 策略会中断），先判断
    $has = @(& $git -C $Src remote 2>$null) -contains 'origin'
    if ($has) { & $git -C $Src remote remove origin 2>$null | Out-Null }
    & $git -C $Src remote add origin $remote
    & $git -C $Src branch -M main 2>$null | Out-Null
    Write-Host "      origin -> $remote"
}

Write-Host "[4/4] 推送（首次会传 34 MB）..." -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "      (DryRun) 跳过推送"
    return
}
# 用一次性 URL 推送，token 不写进 .git/config
$pushUrl = "https://$User`:$Token@github.com/$User/$Repo.git"
& $git -C $Src push $pushUrl main 2>&1 | ForEach-Object { "      $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "推送失败。常见原因：" -ForegroundColor Red
    Write-Host "  - 令牌没有 Contents: Read and write 权限"
    Write-Host "  - 令牌过期或被吊销"
    Write-Host "  - 仓库已存在但属于别人/组织"
    throw "推送失败（exit=$LASTEXITCODE）"
}

Write-Host ""
Write-Host "完成: $remote" -ForegroundColor Green
Write-Host ""
Write-Host "把这一行填进 NOTICE.txt 第 6 节：" -ForegroundColor Cyan
Write-Host "  对应源码获取方式：$remote" -ForegroundColor White
Write-Host ""
Write-Host "其它建议：" -ForegroundColor Cyan
Write-Host "  - 仓库 Topics：qq-bot, astrbot, qqbot, agpl"
Write-Host "  - 用完去 GitHub 设置里吊销这个 token"
