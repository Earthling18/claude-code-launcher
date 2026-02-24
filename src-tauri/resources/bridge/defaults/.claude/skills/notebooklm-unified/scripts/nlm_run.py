#!/usr/bin/env python3
"""
NotebookLM CLI Wrapper - solves Claude Code Git Bash + Windows compatibility issues.

Problems solved:
1. Git Bash cant run cmd.exe activate.bat / tasklist /FI (path mangling)
2. notebooklm.exe not in PATH when called from Git Bash
3. Chinese output garbled (GBK vs UTF-8 / Rich Windows console crash)
4. COLUMNS not set -> notebook IDs truncated
5. Proxy not auto-detected

Usage:
    python scripts/nlm_run.py list
    python scripts/nlm_run.py ask "question" --notebook <ID>
    python scripts/nlm_run.py create "title"
    python scripts/nlm_run.py source add "URL"
    python scripts/nlm_run.py generate audio
    python scripts/nlm_run.py artifact wait <ID>
    python scripts/nlm_run.py download audio

All arguments after nlm_run.py are passed directly to notebooklm CLI.
"""

import os
import sys
import socket
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR = SCRIPT_DIR.parent
VENV_DIR = SKILL_DIR / "venv"

IS_WIN = sys.platform == "win32"

# Locate notebooklm executable
if IS_WIN:
    NLM_EXE = VENV_DIR / "Scripts" / "notebooklm.exe"
else:
    NLM_EXE = VENV_DIR / "bin" / "notebooklm"

# Proxy detection
PROXY_PORTS = [
    (7890, "Clash"),
    (10808, "V2Ray"),
    (1087, "Surge"),
    (1080, "SS/Trojan"),
]


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def detect_proxy() -> "str | None":
    for port, name in PROXY_PORTS:
        if _port_is_open(port):
            print(f"[proxy] Detected {name} on port {port}", file=sys.stderr)
            return f"http://127.0.0.1:{port}"
    return None


def main():
    if not NLM_EXE.exists():
        print(f"ERROR: notebooklm not found at {NLM_EXE}", file=sys.stderr)
        print("Run install.py first to create venv.", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]
    if not args:
        print("Usage: python nlm_run.py <notebooklm-args...>", file=sys.stderr)
        print("Example: python nlm_run.py list", file=sys.stderr)
        sys.exit(1)

    # Build environment
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["COLUMNS"] = "200"
    env["NO_COLOR"] = "1"  # Disable Rich color codes, fixes Windows GBK crash

    # Auto-detect proxy if not already set
    if not env.get("http_proxy") and not env.get("HTTP_PROXY"):
        proxy = detect_proxy()
        if proxy:
            env["http_proxy"] = proxy
            env["https_proxy"] = proxy

    # Run notebooklm with full path, stdout/stderr pass through directly
    # (capture_output breaks Rich library Windows console detection)
    cmd = [str(NLM_EXE)] + args

    try:
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print(f"ERROR: Could not execute {NLM_EXE}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
