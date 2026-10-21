param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$Payload,
    [Parameter(Mandatory=$true)][string]$ExpectedSha,
    [Parameter(Mandatory=$true)][string]$CondaExe
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$runtimePath = Join-Path $InstallRoot 'runtime'
$setupLock = $null
$transcriptStarted = $false
function Get-InstallerSha([string]$FilePath) {
    $algorithm=[Security.Cryptography.SHA256]::Create()
    $stream=[IO.File]::OpenRead($FilePath)
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLower() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Invoke-SetupCommand([string]$Executable,[string[]]$NativeArguments) {
    if (-not [IO.File]::Exists($Executable)) { throw '安装工具缺失，请重新运行安装程序。' }
    $savedPreference=$ErrorActionPreference
    try {
        # Windows PowerShell 5.1 represents native stderr as error records,
        # including successful progress messages. Judge native exit codes instead.
        $ErrorActionPreference='Continue'
        $global:LASTEXITCODE=$null
        & $Executable @NativeArguments 2>&1 | ForEach-Object { Write-Output $_.ToString() }
        $nativeExit=$global:LASTEXITCODE
    } finally { $ErrorActionPreference=$savedPreference }
    if ($null -eq $nativeExit) { throw '安装子步骤未能启动，请查看上方日志。' }
    if ($nativeExit -ne 0) { throw ('安装子步骤返回错误 '+$nativeExit+'，请查看上方日志。') }
}
try {
    if ($InstallRoot -eq [IO.Path]::GetPathRoot($InstallRoot).TrimEnd('\')) { throw '请选择独立的安装文件夹。' }
    $driveInfo = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($InstallRoot))
    if ($driveInfo.AvailableFreeSpace -lt 4GB) { throw '安装磁盘至少需要 4 GB 可用空间。' }
    if ((Test-Path (Join-Path $runtimePath 'app\data')) -and
        -not (Test-Path (Join-Path $runtimePath 'deployment-state.local.json')) -and
        -not (Test-Path (Join-Path $runtimePath 'installation-in-progress.local.json'))) {
        throw '该目录已有开发版数据，请选择新的安装文件夹。'
    }
    New-Item -ItemType Directory -Force -Path $runtimePath | Out-Null
    $setupLock = [IO.File]::Open((Join-Path $runtimePath 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Start-Transcript -LiteralPath (Join-Path $runtimePath 'installer.log') -Append | Out-Null
    $transcriptStarted = $true
    if ((Get-InstallerSha $Payload) -ne $ExpectedSha.ToLower()) { throw '安装内容校验失败。' }
    $stage = Join-Path $runtimePath ('staging\' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($Payload)
    try {
        foreach ($entry in $zip.Entries) {
            $resolved = [IO.Path]::GetFullPath((Join-Path $stage $entry.FullName))
            if (-not $resolved.StartsWith($stage + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '安装包路径越界。' }
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Payload, $stage)
    $lock = Get-Content -LiteralPath (Join-Path $stage 'installer\installer-lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ((Get-InstallerSha $CondaExe) -ne $lock.conda_standalone.executable_sha256) { throw '运行环境工具校验失败。' }
    $lockBytes = [IO.File]::ReadAllBytes((Join-Path $stage 'requirements.lock.txt')) + [IO.File]::ReadAllBytes((Join-Path $stage 'installer\conda-win64.lock'))
    foreach ($repair in @('repair_tts_timeout.py','repair_cron_failure.py','repair_backup_coverage.py')) {
        $lockBytes += [IO.File]::ReadAllBytes((Join-Path $stage ('scripts\'+$repair)))
    }
    $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
    try { $environmentId = ([BitConverter]::ToString($hashAlgorithm.ComputeHash($lockBytes))).Replace('-','').ToLower().Substring(0,16) }
    finally { $hashAlgorithm.Dispose() }
    $prefix = Join-Path $runtimePath ('envs\' + $environmentId)
    $python = Join-Path $prefix 'python.exe'
    $cachePath = Join-Path $runtimePath 'cache'
    $tempPath = Join-Path $runtimePath 'temp'
    New-Item -ItemType Directory -Force -Path $cachePath,$tempPath | Out-Null
    $env:TEMP=$tempPath; $env:TMP=$tempPath
    $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
    $env:CONDA_PKGS_DIRS=Join-Path $cachePath 'conda'
    $env:CONDA_ENVS_PATH=Join-Path $runtimePath 'envs'
    $env:CONDA_REGISTER_ENVS='false'
    $env:CONDA_NUMBER_CHANNEL_NOTICES='0'
    $env:CONDA_NO_PLUGINS='true'
    $env:CONDARC=Join-Path $cachePath 'installer-condarc'
    [IO.File]::WriteAllText($env:CONDARC, "channels: []`ndefault_channels: []`nregister_envs: false`nnumber_channel_notices: 0`nremote_connect_timeout_secs: 15`nremote_read_timeout_secs: 60`nremote_max_retries: 2`n", [Text.UTF8Encoding]::new($false))
    $ready = Join-Path $prefix 'ai-friend-dependencies-ready.json'
    if (-not (Test-Path -LiteralPath $ready)) {
        Write-Output '正在准备独立 Python 环境，首次安装需要联网下载…'
        if (-not (Test-Path -LiteralPath $python)) {
            Invoke-SetupCommand $CondaExe @('create','--prefix',$prefix,'--file',(Join-Path $stage 'installer\conda-win64.lock'),'--no-default-packages','--no-shortcuts','-y')
        }
        $env:PATH=$prefix + ';' + (Join-Path $prefix 'Library\bin') + ';' + $env:PATH
        Write-Output '正在安装固定版本依赖…'
        Invoke-SetupCommand $python @('-m','pip','--isolated','install','--index-url','https://pypi.org/simple','--disable-pip-version-check','--no-input','--no-warn-script-location','--cache-dir',(Join-Path $cachePath 'pip'),'-r',(Join-Path $stage 'requirements.lock.txt'))
        Invoke-SetupCommand $python @('-m','pip','check')
        [IO.File]::WriteAllText($ready, ('{"environment_id":"' + $environmentId + '"}'), [Text.UTF8Encoding]::new($false))
    }
    Write-Output '正在安装程序、应用兼容修复并检查本机服务…'
    Invoke-SetupCommand $python @((Join-Path $stage 'installer\deploy.py'),'--root',$InstallRoot,'--payload',$Payload,'--prefix',$prefix)
    exit 0
} catch {
    Write-Output ('安装未完成：' + $_.Exception.Message)
    exit 1
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($setupLock) { $setupLock.Dispose() }
}
