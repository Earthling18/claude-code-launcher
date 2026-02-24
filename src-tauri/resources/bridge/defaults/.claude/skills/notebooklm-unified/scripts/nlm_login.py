#!/usr/bin/env python3
"""
NotebookLM Login Helper — opens a new terminal window for interactive login.

Claude Code's bash tool cannot handle interactive stdin (notebooklm login
requires the user to press Enter after completing Google sign-in in the browser).
This script works around that by spawning a new terminal window where the user
can interact normally.

Cross-platform: Windows (cmd) and macOS (Terminal.app).
"""

import os
import sys
import time
import platform
import subprocess
import tempfile
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR = SCRIPT_DIR.parent  # scripts/ -> notebooklm-unified/
VENV_DIR = SKILL_DIR / "venv"
STORAGE_STATE = Path.home() / ".notebooklm" / "storage_state.json"

# venv executables
if IS_WIN:
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_ACTIVATE = VENV_DIR / "Scripts" / "activate.bat"
    VENV_NLM = VENV_DIR / "Scripts" / "notebooklm.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_ACTIVATE = VENV_DIR / "bin" / "activate"
    VENV_NLM = VENV_DIR / "bin" / "notebooklm"

# Colors
if IS_WIN:
    os.system("")  # enable ANSI on Windows 10+
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def log(color: str, msg: str):
    print(f"{color}{msg}{NC}")


# ── Proxy detection ────────────────────────────────────────────────────────
PROXY_PORTS = [
    (7890, "Clash"),
    (10808, "V2Ray"),
    (1087, "Surge"),
    (1080, "SS/Trojan"),
]


def detect_proxy() -> str | None:
    """Return http://127.0.0.1:<port> if a known proxy port is listening."""
    for port, name in PROXY_PORTS:
        if _port_is_open(port):
            log(GREEN, f"Detected proxy: {name} on port {port}")
            return f"http://127.0.0.1:{port}"
    return None


def _port_is_open(port: int) -> bool:
    if IS_WIN:
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"], stderr=subprocess.DEVNULL, text=True
            )
            # Look for LISTENING on the target port
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    return True
        except Exception:
            pass
    else:
        try:
            subprocess.check_call(
                ["lsof", "-i", f"TCP:{port}", "-sTCP:LISTEN"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass
    return False


# ── Ensure venv exists ─────────────────────────────────────────────────────
def ensure_venv():
    if VENV_PYTHON.exists():
        log(GREEN, f"venv found: {VENV_DIR}")
        return
    log(YELLOW, "venv not found, running install.py ...")
    install_script = SKILL_DIR / "install.py"
    if not install_script.exists():
        log(RED, f"install.py not found at {install_script}")
        sys.exit(1)
    python_cmd = "python" if IS_WIN else "python3"
    subprocess.check_call([python_cmd, str(install_script)])
    if not VENV_PYTHON.exists():
        log(RED, "install.py finished but venv still not found")
        sys.exit(1)
    log(GREEN, "venv created successfully")


# ── Build terminal script ──────────────────────────────────────────────────
def build_script_content(proxy: str | None) -> str:
    """Return the content of the temporary script that runs inside the new terminal."""
    if IS_WIN:
        lines = ["@echo off", "chcp 65001 >nul 2>&1", ""]
        lines.append("echo ============================================")
        lines.append("echo   NotebookLM Login Helper")
        lines.append("echo ============================================")
        lines.append("")
        if proxy:
            lines.append(f'set "http_proxy={proxy}"')
            lines.append(f'set "https_proxy={proxy}"')
            lines.append(f"echo Proxy set to {proxy}")
        else:
            lines.append("echo WARNING: No proxy detected. If login fails, set proxy manually.")
        lines.append("")
        lines.append(f'call "{VENV_ACTIVATE}"')
        lines.append("")
        lines.append("echo.")
        lines.append("echo Running: notebooklm login")
        lines.append("echo Please complete Google sign-in in the browser,")
        lines.append("echo then come back here and press Enter.")
        lines.append("echo.")
        lines.append("notebooklm login")
        lines.append("")
        lines.append("echo.")
        lines.append("echo Verifying login with: notebooklm list")
        lines.append("set COLUMNS=200")
        lines.append("notebooklm list")
        lines.append("")
        lines.append("echo.")
        lines.append("echo Done. You can close this window.")
        lines.append("pause")
        return "\r\n".join(lines)
    else:
        lines = ["#!/bin/bash", ""]
        lines.append('echo "============================================"')
        lines.append('echo "  NotebookLM Login Helper"')
        lines.append('echo "============================================"')
        lines.append("")
        if proxy:
            lines.append(f'export http_proxy="{proxy}"')
            lines.append(f'export https_proxy="{proxy}"')
            lines.append(f'echo "Proxy set to {proxy}"')
        else:
            lines.append('echo "WARNING: No proxy detected. If login fails, set proxy manually."')
        lines.append("")
        lines.append(f'source "{VENV_ACTIVATE}"')
        lines.append("")
        lines.append('echo ""')
        lines.append('echo "Running: notebooklm login"')
        lines.append('echo "Please complete Google sign-in in the browser,"')
        lines.append('echo "then come back here and press Enter."')
        lines.append('echo ""')
        lines.append("notebooklm login")
        lines.append("")
        lines.append('echo ""')
        lines.append('echo "Verifying login with: notebooklm list"')
        lines.append("COLUMNS=200 notebooklm list")
        lines.append("")
        lines.append('echo ""')
        lines.append('echo "Done. You can close this window."')
        lines.append('read -p "Press Enter to exit..."')
        return "\n".join(lines)


# ── Open new terminal ──────────────────────────────────────────────────────
def open_new_terminal(proxy: str | None):
    content = build_script_content(proxy)

    if IS_WIN:
        # Write a .bat file and open it with os.startfile (opens cmd window)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        log(BLUE, f"Opening cmd window: {tmp.name}")
        os.startfile(tmp.name)
    elif IS_MAC:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        os.chmod(tmp.name, 0o755)
        log(BLUE, f"Opening Terminal window: {tmp.name}")
        subprocess.Popen(["open", "-a", "Terminal", tmp.name])
    else:
        # Linux fallback: try common terminal emulators
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        os.chmod(tmp.name, 0o755)
        for term_cmd in ["gnome-terminal --", "xterm -e", "konsole -e"]:
            parts = term_cmd.split()
            try:
                subprocess.Popen([*parts, tmp.name])
                log(BLUE, f"Opened terminal: {parts[0]}")
                return
            except FileNotFoundError:
                continue
        log(RED, "No terminal emulator found. Please run manually:")
        log(YELLOW, f"  bash {tmp.name}")


# ── Poll for login completion ──────────────────────────────────────────────
def poll_login(timeout: int = 300, interval: int = 3) -> bool:
    """Poll storage_state.json for creation/update. Returns True on success."""
    mtime_before = STORAGE_STATE.stat().st_mtime if STORAGE_STATE.exists() else 0
    log(BLUE, f"Waiting for login (polling {STORAGE_STATE}) ...")
    elapsed = 0
    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval
        if STORAGE_STATE.exists():
            mtime_now = STORAGE_STATE.stat().st_mtime
            if mtime_now > mtime_before:
                log(GREEN, f"Login detected! (storage_state.json updated after {elapsed}s)")
                return True
        # Print a dot every 15 seconds so the caller knows we're alive
        if elapsed % 15 == 0:
            print(f"  ... still waiting ({elapsed}s)")
    log(RED, f"Timed out after {timeout}s. Login may not have completed.")
    return False


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    log(BLUE, "=" * 44)
    log(BLUE, "  NotebookLM Login Helper")
    log(BLUE, "=" * 44)
    print()

    # 1. Ensure venv
    log(YELLOW, "[1/3] Checking venv ...")
    ensure_venv()

    # 2. Detect proxy
    log(YELLOW, "[2/3] Detecting proxy ...")
    proxy = detect_proxy()
    if not proxy:
        log(YELLOW, "No proxy detected on common ports.")

    # 3. Open new terminal
    log(YELLOW, "[3/3] Opening new terminal window for login ...")
    open_new_terminal(proxy)
    print()
    log(BLUE, "A new terminal window should have opened.")
    log(BLUE, "Complete the Google login there, then come back.")
    print()

    # 4. Poll for completion
    success = poll_login()
    if success:
        log(GREEN, "Login successful!")
    else:
        log(YELLOW, "Could not confirm login automatically.")
        log(YELLOW, "Please verify manually: notebooklm list")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
