<#
把源码推送到 Gitee（自动建仓库、建远端、推送）。

用法：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\push-to-gitee.ps1 -Token "你的私人令牌"
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\push-to-gitee.ps1 -Token "xxx" -Repo "xiaojingyu-qq-agent" -Private

私人令牌获取：Gitee → 设置 → 私人令牌 → 生成新令牌（勾选 projects 权限）

参数：
  -Token     Gitee 私人令牌（只在本机使用，不会写进仓库）
  -User      Gitee 用户名；不填自动查询
  -Repo      仓库名，默认 xiaojingyu-qq-agent
  -Private   建私有仓库（默认公开）
  -Src       要推送的目录，默认 E:\_public-src
  -DryRun    只打印步骤
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

Write-Host "[1/4] 校验令牌 ..." -ForegroundColor Yellow
$me = Invoke-RestMethod "https://gitee.com/api/v5/user?access_token=$Token" -TimeoutSec 30
if (-not $User) { $User = $me.login }
Write-Host "      已登录为: $User"

Write-Host "[2/4] 检查仓库 $User/$Repo ..." -ForegroundColor Yellow
$exists = $true
try { $null = Invoke-RestMethod "https://gitee.com/api/v5/repos/$User/$Repo" -TimeoutSec 30 }
catch { $exists = $false }

if (-not $exists) {
    Write-Host "      不存在，创建 ..."
    $body = @{
        access_token = $Token
        name         = $Repo
        private      = [bool]$Private
        description  = '小鲸鱼 QQ Agent — 有活人感的 QQ 群聊机器人（AGPL-3.0-or-later）'
        auto_init    = $false
    } | ConvertTo-Json
    if ($DryRun) { Write-Host "      (DryRun) 会创建" }
    else {
        $created = Invoke-RestMethod 'https://gitee.com/api/v5/user/repos' -Method Post -Body $body -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 60
        Write-Host "      已创建: $($created.html_url)"
    }
} else {
    Write-Host "      已存在，直接推送"
}

Write-Host "[3/4] 配置远端 ..." -ForegroundColor Yellow
$remote = "https://gitee.com/$User/$Repo.git"
if ($DryRun) { Write-Host "      (DryRun) remote = $remote" }
else {
    & $git -C $Src remote remove origin 2>$null | Out-Null
    & $git -C $Src remote add origin $remote
    & $git -C $Src branch -M main 2>$null | Out-Null
    Write-Host "      origin -> $remote"
}

Write-Host "[4/4] 推送（首次约 34 MB）..." -ForegroundColor Yellow
if ($DryRun) { Write-Host "      (DryRun) 跳过推送"; return }
$pushUrl = "https://$User`:$Token@gitee.com/$User/$Repo.git"
& $git -C $Src push $pushUrl main 2>&1 | ForEach-Object { "      $_" }
if ($LASTEXITCODE -ne 0) { throw "推送失败（exit=$LASTEXITCODE）" }

Write-Host ""
Write-Host "完成: $remote" -ForegroundColor Green
Write-Host "接下来：" -ForegroundColor Cyan
Write-Host "  1) 把 NOTICE.txt 第 6 节的【待填】改成 $remote"
Write-Host "  2) 建议同时把仓库镜像到 GitHub（有代理时跑 push-to-github.ps1）"
Write-Host "  3) 用完可以吊销这个令牌"
