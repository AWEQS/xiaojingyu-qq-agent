# AstrBot path resolution (single source of truth).
# Root priority: $env:ASTRBOT_ROOT -> parent of this scripts/ folder.
if ($env:ASTRBOT_ROOT -and (Test-Path -LiteralPath $env:ASTRBOT_ROOT)) {
    $AstrBotRoot = (Resolve-Path -LiteralPath $env:ASTRBOT_ROOT).Path
} elseif ($PSScriptRoot) {
    $AstrBotRoot = Split-Path -Parent $PSScriptRoot
} else {
    $AstrBotRoot = (Get-Location).Path
}
$AstrBotScripts = Join-Path $AstrBotRoot 'scripts'
$AstrBotData    = Join-Path $AstrBotRoot 'data'
$AstrBotBin     = Join-Path $AstrBotRoot 'bin'
$AstrBotTools   = Join-Path $AstrBotRoot 'tools'
$AstrBotNapCat  = Join-Path $AstrBotRoot 'napcat'
$AstrBotDesktop = Join-Path $AstrBotRoot 'desktop'
function Get-AstrBotPath([string]$rel) {
    if ([string]::IsNullOrEmpty($rel)) { return $AstrBotRoot }
    return (Join-Path $AstrBotRoot $rel)
}