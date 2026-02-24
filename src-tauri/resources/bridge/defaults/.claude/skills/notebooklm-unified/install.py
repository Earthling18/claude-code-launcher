#!/usr/bin/env python3
"""
NotebookLM Unified Skill Installer (cross-platform: macOS / Windows)
Creates venv, installs dependencies, checks configuration.
"""

import sys
import os
import subprocess
import shutil
import json
from pathlib import Path

SKILL_DIR = Path(__file__).parent.resolve()
VENV_DIR = SKILL_DIR / "venv"
MCP_DIR = SKILL_DIR / "wexin-read-mcp"
IS_WIN = sys.platform == "win32"

# venv paths differ per platform
VENV_PYTHON = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
VENV_PIP = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("pip.exe" if IS_WIN else "pip")

# Colors (disabled on Windows cmd without VT support)
if IS_WIN:
    os.system("")  # enable ANSI on Windows 10+
RED, GREEN, YELLOW, BLUE, NC = "\033[0;31m", "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0m"


def log(color, msg):
    print(f"{color}{msg}{NC}")


def run(cmd, **kwargs):
    """Run a command, raise on failure."""
    return subprocess.run(cmd, check=True, **kwargs)


def step(num, total, title):
    print()
    log(YELLOW, f"[{num}/{total}] {title}")


def main():
    total_steps = 5
    log(BLUE, "=" * 44)
    log(BLUE, "  NotebookLM Unified Skill Installer")
    log(BLUE, "=" * 44)

    # ── 1. Check Python version ──
    step(1, total_steps, "Checking Python version...")
    v = sys.version_info
    if v < (3, 9):
        log(RED, f"Python {v.major}.{v.minor} too low, need 3.9+")
        sys.exit(1)
    log(GREEN, f"Python {v.major}.{v.minor}.{v.micro}")

    # ── 2. Create venv & install dependencies ──
    step(2, total_steps, "Setting up virtual environment...")
    if not VENV_PYTHON.exists():
        print("Creating venv...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        log(GREEN, f"venv created at {VENV_DIR}")
    else:
        log(GREEN, "venv already exists")

    # Upgrade pip silently
    run([str(VENV_PIP), "install", "--upgrade", "pip", "-q"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Install skill requirements
    req_file = SKILL_DIR / "requirements.txt"
    if req_file.exists():
        print("Installing skill dependencies...")
        run([str(VENV_PIP), "install", "-r", str(req_file), "-q"])
        log(GREEN, "Skill dependencies installed")

    # Install notebooklm CLI
    print("Installing notebooklm-py CLI...")
    run([str(VENV_PIP), "install",
         "git+https://github.com/teng-lin/notebooklm-py.git", "-q"])
    log(GREEN, "notebooklm CLI installed")

    # ── 3. Clone MCP server ──
    step(3, total_steps, "Setting up MCP server...")
    if MCP_DIR.is_dir():
        log(GREEN, "MCP server already exists")
    else:
        if not shutil.which("git"):
            log(RED, "git not found. Please install git first.")
            sys.exit(1)
        print("Cloning wexin-read-mcp...")
        run(["git", "clone", "https://github.com/Bwkyd/wexin-read-mcp.git", str(MCP_DIR)])
        log(GREEN, "MCP server cloned")

    # Install MCP dependencies into venv
    mcp_req = MCP_DIR / "requirements.txt"
    if mcp_req.exists():
        print("Installing MCP dependencies...")
        run([str(VENV_PIP), "install", "-r", str(mcp_req), "-q"])
        log(GREEN, "MCP dependencies installed")

    # ── 4. Check MCP configuration ──
    step(4, total_steps, "Checking MCP configuration...")
    claude_config = Path.home() / ".claude" / "config.json"
    mcp_server_py = MCP_DIR / "src" / "server.py"

    if claude_config.exists():
        try:
            config = json.loads(claude_config.read_text(encoding="utf-8"))
            if "mcpServers" in config and "weixin-reader" in config["mcpServers"]:
                log(GREEN, "weixin-reader already configured")
            else:
                log(YELLOW, "weixin-reader not configured yet")
                print(f"  Edit {claude_config}")
                print(f'  Add to "mcpServers":')
                print(f'    "weixin-reader": {{"command": "python", "args": ["{mcp_server_py}"]}}')
        except Exception as e:
            log(YELLOW, f"Cannot read config: {e}")
    else:
        log(YELLOW, f"Config not found: {claude_config}")

    # ── 5. Summary ──
    step(5, total_steps, "Installation complete!")
    print()
    log(BLUE, "=" * 44)
    log(GREEN, "All dependencies installed into venv/")
    log(BLUE, "=" * 44)
    print()
    print(f"Install location : {SKILL_DIR}")
    print(f"Virtual env      : {VENV_DIR}")
    print()

    # Platform-specific activation hint
    if IS_WIN:
        activate_cmd = f"{VENV_DIR}\\Scripts\\activate"
    else:
        activate_cmd = f"source {VENV_DIR}/bin/activate"

    print("Next steps:")
    print(f"  1. Activate venv : {activate_cmd}")
    print("  2. Set proxy     : export http_proxy=... https_proxy=...")
    print("  3. Login         : notebooklm login")
    print("  4. Verify        : notebooklm list")
    print()


if __name__ == "__main__":
    main()
