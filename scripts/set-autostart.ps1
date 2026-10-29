param(
    [int]$Enable = 0
)

. (Join-Path $PSScriptRoot '_paths.ps1')

# 开机自启动开关：在用户 Startup 目录创建/删除「小鲸鱼」快捷方式
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup '小鲸鱼.lnk'

if ($Enable -eq 1) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = (Get-AstrBotPath 'desktop\electron\electron.exe')
    $sc.Arguments = '"' + (Get-AstrBotPath 'desktop\app') + '"'
    $sc.WorkingDirectory = (Get-AstrBotPath 'desktop\app')
    $sc.IconLocation = (Get-AstrBotPath 'desktop\app\icon.ico')
    $sc.Description = '小鲸鱼 QQ Agent 控制台'
    $sc.Save()
    Write-Host "已启用开机自启: $lnk"
} else {
    if (Test-Path $lnk) {
        Remove-Item $lnk -Force
        Write-Host "已关闭开机自启"
    } else {
        Write-Host "本来就未启用"
    }
}
