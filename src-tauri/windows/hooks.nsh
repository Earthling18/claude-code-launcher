; NSIS hook: silently uninstall older versions ("Mobot Launcher" or legacy
; "Claude Code Launcher") before installing the new "CC 启动器".
; Ensures users upgrading from any older name end up with a single clean install.

; Flag variable: set to 1 when an older version is detected and removed.
Var MigratedFromOld

!macro NSIS_HOOK_PREINSTALL
  StrCpy $MigratedFromOld "0"

  ; --- Detect "Mobot Launcher" (the previous app name) ---
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Mobot Launcher" "UninstallString"
  StrCmp $0 "" mobot_not_found
    StrCpy $MigratedFromOld "1"
    ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Mobot Launcher" "InstallLocation"
    DetailPrint "Found Mobot Launcher at $1, removing..."
    ExecWait '"$0" /S _?=$1'
    Sleep 2000
    Delete "$1\mobot-launcher-tauri.exe"
    Delete "$1\uninstall.exe"
    RMDir /r "$1"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Mobot Launcher"
  mobot_not_found:

  ; --- Detect legacy "Claude Code Launcher" ---
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher" "UninstallString"
  StrCmp $0 "" legacy_not_found
    StrCpy $MigratedFromOld "1"
    ReadRegStr $1 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher" "InstallLocation"
    DetailPrint "Found legacy Claude Code Launcher at $1, removing..."
    ExecWait '"$0" /S _?=$1'
    Sleep 2000
    Delete "$1\claude-code-launcher-tauri.exe"
    Delete "$1\uninstall.exe"
    RMDir /r "$1"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\Claude Code Launcher"
  legacy_not_found:

  ; --- Clean up old desktop and start menu shortcuts (both old names) ---
  Delete "$DESKTOP\Mobot Launcher.lnk"
  Delete "$SMPROGRAMS\Mobot Launcher.lnk"
  Delete "$DESKTOP\Claude Code Launcher.lnk"
  Delete "$SMPROGRAMS\Claude Code Launcher.lnk"
!macroend

; Post-install hook: only create new shortcuts when migrating from an older app name.
; Tauri's NSIS template skips shortcut creation in update mode ($UpdateMode=1),
; so after removing old shortcuts above there would be none left without this.
; For normal CC→CC updates, don't touch shortcuts (respect user preference).
!macro NSIS_HOOK_POSTINSTALL
  StrCmp $MigratedFromOld "1" 0 skip_shortcuts
    CreateShortCut "$DESKTOP\CC 启动器.lnk" "$INSTDIR\cc-launcher-tauri.exe"
    CreateShortCut "$SMPROGRAMS\CC 启动器.lnk" "$INSTDIR\cc-launcher-tauri.exe"
  skip_shortcuts:
!macroend
