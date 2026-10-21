param([ValidateSet('Start','Stop','Maintain','Backup','Verify','Setup','PrepareUninstall','Persona','Status','LoginInfo','EnableAutostart','DisableAutostart','Background')][string]$Action='Maintain')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if ($Action -eq 'PrepareUninstall') {
    [Console]::OutputEncoding=[Text.Encoding]::Unicode
    [Console]::WriteLine(([char]0xFEFF).ToString() + 'AI好友卸载日志')
}
$root=Split-Path -Parent $PSScriptRoot
$launchScript=$PSCommandPath
$settings=Get-Content -LiteralPath (Join-Path $root 'runtime\installation.local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$python=Join-Path $root ('runtime\' + $settings.environment + '\python.exe')
$url='http://127.0.0.1:' + $settings.port
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$script:busy=$false

function Run-Task([string]$relative,[string[]]$TaskArguments=@(),[string]$InputText='') {
    $start=[Diagnostics.ProcessStartInfo]::new()
    $start.FileName=$python
    $quoted=@('"'+(Join-Path $root $relative)+'"') + @($TaskArguments | ForEach-Object {'"'+$_+'"'})
    $start.Arguments=$quoted -join ' '
    $start.WorkingDirectory=$root
    $start.UseShellExecute=$false; $start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    $start.RedirectStandardInput=($InputText -ne '')
    $start.EnvironmentVariables['PYTHONUTF8']='1'
    $start.EnvironmentVariables['PYTHONIOENCODING']='utf-8'
    $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
    $process=[Diagnostics.Process]::Start($start)
    if ($InputText -ne '') {
        $inputBytes=[Text.Encoding]::UTF8.GetBytes($InputText)
        $process.StandardInput.BaseStream.Write($inputBytes,0,$inputBytes.Length)
        $process.StandardInput.Close()
    }
    $out=$process.StandardOutput.ReadToEndAsync()
    $err=$process.StandardError.ReadToEndAsync()
    while (-not $process.HasExited) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 120 }
    $text=$out.Result + $err.Result
    if ($process.ExitCode -ne 0) { throw ('操作未完成。' + "`r`n" + $text) }
    return $text
}

function Show-Message([string]$text) { [Windows.Forms.MessageBox]::Show($text,'AI好友') | Out-Null }
function Remove-OwnedAutostart {
    $link=Join-Path ([Environment]::GetFolderPath('Startup')) ('AI好友-'+$settings.port+'.lnk')
    if (Test-Path -LiteralPath $link) {
        $saved=(New-Object -ComObject WScript.Shell).CreateShortcut($link)
        if ($saved.TargetPath -eq (Join-Path $root 'AI好友.exe')) { Remove-Item -LiteralPath $link }
    }
}

try {
    if ($Action -eq 'PrepareUninstall') {
        Remove-OwnedAutostart
        Run-Task 'installer\deploy.py' @('--root',$root,'--uninstall-program') | Write-Output
        exit 0
    }
    if ($Action -eq 'Start' -or $Action -eq 'Persona' -or $Action -eq 'Background') {
        Run-Task 'scripts\service.py' @('start','--no-browser') | Out-Null
        if ($Action -eq 'Persona') { Start-Process ($url+'/#/plugin-view/astrbot_plugin_persona_studio/editor') }
        elseif ($Action -eq 'Start') { Start-Process $url }
        exit 0
    }
    if ($Action -eq 'Stop') { Run-Task 'scripts\service.py' @('stop') | Write-Output; exit 0 }
    if ($Action -eq 'Backup') { Run-Task 'scripts\native_backup.py' @('create') | Write-Output; exit 0 }
    if ($Action -eq 'Verify') { Run-Task 'scripts\native_backup.py' @('verify') | Write-Output; exit 0 }
    if ($Action -eq 'Setup') { Run-Task 'scripts\finish_setup.py' | Write-Output; exit 0 }
    if ($Action -eq 'Status') { Run-Task 'scripts\daily_check.py' | Write-Output; exit 0 }
    if ($Action -eq 'LoginInfo') { Start-Process notepad.exe -ArgumentList ('"'+(Join-Path $root 'runtime\本机登录说明.txt')+'"'); exit 0 }
    if ($Action -eq 'EnableAutostart' -or $Action -eq 'DisableAutostart') {
        $startup=[Environment]::GetFolderPath('Startup')
        $link=Join-Path $startup ('AI好友-'+$settings.port+'.lnk')
        if ($Action -eq 'EnableAutostart') {
            $shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut($link)
            $shortcut.TargetPath=Join-Path $root 'AI好友.exe'
            $shortcut.Arguments='--background'
            $shortcut.WorkingDirectory=$root
            $shortcut.Save()
        } else { Remove-OwnedAutostart }
        exit 0
    }

    $form=[Windows.Forms.Form]::new()
    $form.Text='AI好友 · 本机维护'
    $form.Size=[Drawing.Size]::new(840,680)
    $form.MinimumSize=[Drawing.Size]::new(760,600)
    $form.StartPosition='CenterScreen'
    $form.Font=[Drawing.Font]::new('Microsoft YaHei UI',10)
    $form.AutoScaleMode='Dpi'
    $layout=[Windows.Forms.TableLayoutPanel]::new()
    $layout.Dock='Fill'; $layout.Padding=[Windows.Forms.Padding]::new(22); $layout.ColumnCount=1; $layout.RowCount=5
    $layout.RowStyles.Add([Windows.Forms.RowStyle]::new('Absolute',42))
    $layout.RowStyles.Add([Windows.Forms.RowStyle]::new('Absolute',85))
    $layout.RowStyles.Add([Windows.Forms.RowStyle]::new('Absolute',180))
    $layout.RowStyles.Add([Windows.Forms.RowStyle]::new('Percent',100))
    $layout.RowStyles.Add([Windows.Forms.RowStyle]::new('Absolute',32))
    $title=[Windows.Forms.Label]::new(); $title.Text='AI好友 '+$settings.version; $title.Font=[Drawing.Font]::new('Microsoft YaHei UI',17,[Drawing.FontStyle]::Bold); $title.AutoSize=$true
    $intro=[Windows.Forms.Label]::new(); $intro.Dock='Fill'; $intro.Text="首次使用：查看登录信息 → 在面板填写自己的 Key、扫码保存 QQ → 同步 QQ 机器人。`r`nQQ 人设授权：在 QQ 发 /sid，复制完整 UMO 后点击「授权 QQ 私聊」。`r`n更新时选择新版安装 EXE，升级前自动备份；数据和日志保存在本机。"
    $buttons=[Windows.Forms.FlowLayoutPanel]::new(); $buttons.Dock='Fill'; $buttons.WrapContents=$true
    $output=[Windows.Forms.TextBox]::new(); $output.Dock='Fill'; $output.Multiline=$true; $output.ReadOnly=$true; $output.ScrollBars='Vertical'; $output.Text='程序位置：'+$root+"`r`n"+'面板地址：'+$url+"`r`n"+'就绪。'
    $status=[Windows.Forms.Label]::new(); $status.Dock='Fill'; $status.Text='操作只影响此安装目录。卸载默认保留 runtime 数据。'
    $layout.Controls.Add($title,0,0); $layout.Controls.Add($intro,0,1); $layout.Controls.Add($buttons,0,2); $layout.Controls.Add($output,0,3); $layout.Controls.Add($status,0,4)
    $form.Controls.Add($layout)

    function Add-Action([string]$label,[scriptblock]$work) {
        $button=[Windows.Forms.Button]::new(); $button.Text=$label; $button.AutoSize=$true; $button.MinimumSize=[Drawing.Size]::new(125,39); $button.Margin=[Windows.Forms.Padding]::new(0,0,10,10)
        $button.Tag=$work
        $button.Add_Click({
            if ($script:busy) { return }
            $script:busy=$true; $buttons.Enabled=$false; $status.Text='正在执行，请等待完成…'; $form.Refresh()
            try {
                $result=& $this.Tag
                if ($result) { $output.Text=($result -join "`r`n") }
                $status.Text='操作完成。'
            } catch { $output.Text=$_.Exception.Message; $status.Text='操作未完成，详情见上方；已有数据保留。' }
            finally { $script:busy=$false; $buttons.Enabled=$true }
        })
        $buttons.Controls.Add($button)
    }
    Add-Action '启动 / 打开面板' { Run-Task 'scripts\service.py' @('start','--no-browser'); Start-Process $url }
    Add-Action '停止运行' { Run-Task 'scripts\service.py' @('stop') }
    Add-Action '检查运行状态' { Run-Task 'scripts\daily_check.py' }
    Add-Action '查看登录信息' { Start-Process notepad.exe -ArgumentList ('"'+(Join-Path $root 'runtime\本机登录说明.txt')+'"'); '登录信息已在本机打开，请勿公开分享。' }
    Add-Action '更新本机登录记录' {
        $login=[Windows.Forms.Form]::new(); $login.Text='填写当前面板登录信息'; $login.Size=[Drawing.Size]::new(420,250); $login.StartPosition='CenterParent'
        $userLabel=[Windows.Forms.Label]::new(); $userLabel.Text='账号'; $userLabel.Location=[Drawing.Point]::new(24,25)
        $user=[Windows.Forms.TextBox]::new(); $user.Location=[Drawing.Point]::new(110,22); $user.Width=245
        $passLabel=[Windows.Forms.Label]::new(); $passLabel.Text='密码'; $passLabel.Location=[Drawing.Point]::new(24,80)
        $pass=[Windows.Forms.TextBox]::new(); $pass.Location=[Drawing.Point]::new(110,77); $pass.Width=245; $pass.UseSystemPasswordChar=$true
        $save=[Windows.Forms.Button]::new(); $save.Text='验证并保存'; $save.Location=[Drawing.Point]::new(235,140); $save.Width=120; $save.DialogResult='OK'; $login.AcceptButton=$save
        $login.Controls.AddRange(@($userLabel,$user,$passLabel,$pass,$save))
        try {
            if ($login.ShowDialog($form) -eq 'OK') { Run-Task 'scripts\update_local_login.py' @() (@{username=$user.Text;password=$pass.Text} | ConvertTo-Json -Compress) }
        } finally { $pass.Text=''; $login.Dispose() }
    }
    Add-Action '同步 QQ 机器人' { Run-Task 'scripts\finish_setup.py' }
    Add-Action '授权 QQ 私聊' {
        Add-Type -AssemblyName Microsoft.VisualBasic
        $umo=[Microsoft.VisualBasic.Interaction]::InputBox('在 QQ 发 /sid，将返回的完整 UMO 粘贴到这里（不要包含外侧括号）。','授权人设编辑','')
        if ($umo) { Run-Task 'scripts\finish_setup.py' @('--authorize-umo',$umo.Trim()) }
    }
    Add-Action '备份用户数据' { Run-Task 'scripts\native_backup.py' @('create') }
    Add-Action '检查备份恢复' { Run-Task 'scripts\native_backup.py' @('verify') }
    Add-Action '打开日志目录' { Start-Process explorer.exe -ArgumentList ('"'+(Join-Path $root 'runtime')+'"') }
    Add-Action '打开人设设置' { Start-Process ($url+'/#/plugin-view/astrbot_plugin_persona_studio/editor') }
    Add-Action '开启登录后启动' { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launchScript -Action EnableAutostart; if ($LASTEXITCODE -ne 0) { throw '设置未完成' }; '已启用当前用户登录后后台运行。' }
    Add-Action '关闭登录后启动' { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $launchScript -Action DisableAutostart; if ($LASTEXITCODE -ne 0) { throw '设置未完成' }; '已关闭当前安装的登录后启动。' }
    Add-Action '选择新版安装包' {
        $dialog=[Windows.Forms.OpenFileDialog]::new(); $dialog.Filter='AI好友安装程序 (*.exe)|*.exe'; $dialog.Title='选择可信来源的新版 AI好友安装包'
        if ($dialog.ShowDialog() -eq 'OK') {
            $info=[Diagnostics.FileVersionInfo]::GetVersionInfo($dialog.FileName)
            if ($info.ProductName -ne 'AI好友' -or $info.FileDescription -notlike '*安装*') { throw '这不是标记为 AI好友的安装程序，请核对文件来源。' }
            if ([Windows.Forms.MessageBox]::Show(('将运行安装包 '+$info.FileVersion+'。请确认来自可信发布渠道。'),'更新 AI好友','OKCancel') -eq 'OK') {
                Start-Process -FilePath $dialog.FileName -ArgumentList ('/D='+$root)
                $script:busy=$false
                $form.Close()
            }
        }
    }
    Add-Action '恢复上一程序版本' {
        if ([Windows.Forms.MessageBox]::Show('恢复上一程序和环境版本，保留当前用户数据。是否继续？','版本恢复','OKCancel') -eq 'OK') {
            Run-Task 'installer\deploy.py' @('--root',$root,'--rollback')
        }
    }
    $form.Add_FormClosing({ if ($script:busy) { $_.Cancel=$true } })
    [void]$form.ShowDialog()
} catch {
    if ($Action -eq 'Maintain' -or $Action -eq 'Start') { Show-Message $_.Exception.Message }
    Write-Error $_.Exception.Message
    exit 1
}
