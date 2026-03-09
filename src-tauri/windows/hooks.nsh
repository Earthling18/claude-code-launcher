; NSIS hook: silently uninstall old "Claude Code Launcher" before installing new "Mobot Launcher"
; This ensures users upgrading from the old name don't end up with two programs.

!macro NSIS_HOOK_PREINSTALL
  ; Check if old "Claude Code Launcher" is installed (current user)
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher" "UninstallString"
  ${If} $0 != ""
    DetailPrint "Found old Claude Code Launcher installation, removing..."
    ; Run the old uninstaller silently
    ExecWait '"$0" /S _?=$LOCALAPPDATA\Claude Code Launcher'
    ; Clean up leftover directory
    RMDir /r "$LOCALAPPDATA\Claude Code Launcher"
    ; Remove registry entry in case uninstaller didn't clean up
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher"
  ${EndIf}
!macroend
