; NSIS hook: silently uninstall old "Claude Code Launcher" before installing new "Mobot Launcher"
; This ensures users upgrading from the old name don't end up with two programs.

!macro NSIS_HOOK_PREINSTALL
  ; Check if old "Claude Code Launcher" is installed (current user)
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher" "UninstallString"
  StrCmp $0 "" old_not_found
    ; Read the actual install location from registry
    ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher" "InstallLocation"
    DetailPrint "Found old Claude Code Launcher at $1, removing..."
    ; Run the old uninstaller silently, pinned to install location
    ExecWait '"$0" /S _?=$1'
    ; Wait for uninstaller to release file locks
    Sleep 2000
    ; Clean up leftover files (exe may survive uninstall due to file locks)
    Delete "$1\claude-code-launcher-tauri.exe"
    Delete "$1\uninstall.exe"
    RMDir /r "$1"
    ; Remove registry entry in case uninstaller didn't clean up
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher"
  old_not_found:

  ; Clean up old desktop and start menu shortcuts
  Delete "$DESKTOP\Claude Code Launcher.lnk"
  Delete "$SMPROGRAMS\Claude Code Launcher.lnk"
!macroend
