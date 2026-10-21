Unicode true
RequestExecutionLevel user
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
Name "AI好友 ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\AI-Friend"
InstallDirRegKey HKCU "Software\LocalAIFriend" "InstallLocation"
SetCompressor /SOLID lzma
ShowInstDetails hide
ShowUninstDetails hide
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "AI好友"
VIAddVersionKey /LANG=2052 "FileDescription" "AI好友本地安装与更新程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Local AI Friend Project; third-party components retain their licenses"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "安装 AI好友"
!define MUI_WELCOMEPAGE_TEXT "将聊天、记忆和人设保存在自己的电脑上。$\r$\n$\r$\n请选择安装位置；程序将自动准备独立环境。首次安装需要联网，建议预留至少 4 GB 空间。$\r$\n$\r$\n已有安装可使用新版安装包升级，用户数据会保留。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${SOURCE}\installer\install-notice.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "打开维护与首次使用向导"
!define MUI_FINISHPAGE_RUN_FUNCTION OpenMaintenance
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "此安装包需要 64 位 Windows。" /SD IDOK
    Abort
  ${EndIf}
  ${DisableX64FSRedirection}
  SetShellVarContext current
  SetRegView 64
  ReadRegStr $0 HKCU "Software\LocalAIFriend" "InstallLocation"
  ${If} $0 == ""
  ${AndIf} $INSTDIR == "$LOCALAPPDATA\AI-Friend"
    ${If} ${FileExists} "E:\*.*"
      StrCpy $INSTDIR "E:\Apps\AI-Friend"
    ${ElseIf} ${FileExists} "D:\*.*"
      StrCpy $INSTDIR "D:\Apps\AI-Friend"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function un.onInit
  ${DisableX64FSRedirection}
FunctionEnd

Function OpenMaintenance
  Exec '"$INSTDIR\AI好友.exe" --maintenance'
FunctionEnd

Section "安装程序"
  AddSize 4194304
  SetShellVarContext current
  SetRegView 64
  SetOutPath "$INSTDIR\setup-cache"
  File /oname=payload-${VERSION}.zip "${PAYLOAD}"
  File /oname=conda.exe "${CONDAEXE}"
  File /oname=bootstrap.ps1 "${SOURCE}\installer\bootstrap.ps1"
  DetailPrint "正在部署运行环境与程序，请保持网络连接…"
  nsExec::ExecToLog /TIMEOUT=3600000 '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\setup-cache\bootstrap.ps1" -InstallRoot "$INSTDIR" -Payload "$INSTDIR\setup-cache\payload-${VERSION}.zip" -ExpectedSha "${PAYLOADSHA}" -CondaExe "$INSTDIR\setup-cache\conda.exe"'
  Pop $0
  ${If} $0 != 0
    SetErrorLevel 1
    MessageBox MB_OK|MB_ICONSTOP "安装未完成。已有数据会保留。$\r$\n请检查网络后重试，详情见：$\r$\n$INSTDIR\runtime\installer.log" /SD IDOK
    Abort
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\AI好友（本地版）"
  CreateShortcut "$SMPROGRAMS\AI好友（本地版）\启动AI好友.lnk" "$INSTDIR\AI好友.exe"
  CreateShortcut "$SMPROGRAMS\AI好友（本地版）\维护与更新.lnk" "$INSTDIR\AI好友.exe" '--maintenance'
  ${GetParameters} $1
  ClearErrors
  ${GetOptions} $1 "/NODESKTOP" $2
  ${If} ${Errors}
    CreateShortcut "$DESKTOP\AI好友（本地版）.lnk" "$INSTDIR\AI好友.exe"
  ${EndIf}
  WriteUninstaller "$INSTDIR\卸载AI好友.exe"
  WriteRegStr HKCU "Software\LocalAIFriend" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend" "DisplayName" "AI好友（本地版）"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend" "UninstallString" '$\"$INSTDIR\卸载AI好友.exe$\"'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  SetRegView 64
  IfFileExists "$INSTDIR\runtime\deployment-state.local.json" +3
    MessageBox MB_OK|MB_ICONSTOP "安装登记不存在，请勿在其他目录运行卸载程序。" /SD IDOK
    Abort
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\installer\launch.ps1" -Action PrepareUninstall'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "程序尚未确认停止，已暂停卸载。请从维护窗口停止后重试。" /SD IDOK
    Abort
  ${EndIf}
  !include "${DELETEINCLUDE}"
  Delete "$INSTDIR\setup-cache\payload-${VERSION}.zip"
  Delete "$INSTDIR\setup-cache\bootstrap.ps1"
  Delete "$INSTDIR\setup-cache\conda.exe"
  RMDir "$INSTDIR\setup-cache"
  Delete "$INSTDIR\卸载AI好友.exe"
  ReadRegStr $1 HKCU "Software\LocalAIFriend" "InstallLocation"
  ${If} $1 == "$INSTDIR"
  Delete "$SMPROGRAMS\AI好友（本地版）\启动AI好友.lnk"
  Delete "$SMPROGRAMS\AI好友（本地版）\维护与更新.lnk"
  RMDir "$SMPROGRAMS\AI好友（本地版）"
  Delete "$DESKTOP\AI好友（本地版）.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalAIFriend"
  DeleteRegKey HKCU "Software\LocalAIFriend"
  ${EndIf}
  MessageBox MB_OK "程序已卸载。用户数据与运行环境保留在：$\r$\n$INSTDIR\runtime$\r$\n重新安装到同一位置可继续使用。" /SD IDOK
SectionEnd
