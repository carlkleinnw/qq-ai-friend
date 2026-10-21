param(
    [ValidateSet('Enable', 'Disable', 'Status')][string]$Action = 'Status',
    [string]$ShortcutDir = [Environment]::GetFolderPath('Startup')
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$projectRoot = Split-Path -Parent $PSScriptRoot
$shortcutPath = Join-Path $ShortcutDir 'AI好友.lnk'
if ($Action -eq 'Enable') {
    $pythonPath = Join-Path $projectRoot 'runtime\conda\pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw '找不到本地 Conda 环境。' }
    New-Item -ItemType Directory -Path $ShortcutDir -Force | Out-Null
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonPath
    $shortcut.Arguments = '"' + (Join-Path $projectRoot 'scripts\service.py') + '" start --no-browser'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = '登录 Windows 后启动本机 AI 好友，不自动打开浏览器。'
    $shortcut.Save()
    Write-Output '已启用当前用户登录后启动。电脑关机、睡眠或未联网时不能保持 QQ 在线。'
} elseif ($Action -eq 'Disable') {
    if (Test-Path -LiteralPath $shortcutPath) { Remove-Item -LiteralPath $shortcutPath }
    Write-Output '已关闭登录后自动启动，当前运行的程序不受影响。'
} else {
    Write-Output ('登录后启动：' + (Test-Path -LiteralPath $shortcutPath))
}
