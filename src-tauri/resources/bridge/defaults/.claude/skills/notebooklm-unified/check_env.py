#!/usr/bin/env python3
"""
Environment check script - Verify all dependencies for notebooklm-unified skill
"""

import sys
import os
import json
from pathlib import Path

# Color output
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

def print_status(status, message):
    """Print status message"""
    if status == "ok":
        print(f"{GREEN}  OK: {message}{NC}")
    elif status == "warning":
        print(f"{YELLOW}  WARN: {message}{NC}")
    elif status == "error":
        print(f"{RED}  FAIL: {message}{NC}")
    else:
        print(f"{BLUE}  INFO: {message}{NC}")

def check_python_version():
    """Check Python version"""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major >= 3 and version.minor >= 9:
        print_status("ok", f"Python {version_str}")
        return True
    else:
        print_status("error", f"Python {version_str} (need 3.9+)")
        return False

def check_module(module_name, import_name=None):
    """Check if Python module is installed"""
    if import_name is None:
        import_name = module_name

    try:
        __import__(import_name)
        print_status("ok", f"{module_name} installed")
        return True
    except ImportError:
        print_status("error", f"{module_name} not installed")
        return False

def check_command(cmd):
    """Check if command is available"""
    import shutil

    if shutil.which(cmd):
        import subprocess
        try:
            result = subprocess.run([cmd, "--version"],
                                  capture_output=True,
                                  text=True,
                                  timeout=5)
            version = result.stdout.split('\n')[0] if result.stdout else "unknown"
            print_status("ok", f"{cmd} installed ({version})")
        except Exception:
            print_status("ok", f"{cmd} installed")
        return True
    else:
        print_status("error", f"{cmd} not found")
        return False

def check_mcp_config():
    """Check MCP configuration"""
    config_path = Path.home() / ".claude" / "config.json"

    if not config_path.exists():
        print_status("error", f"Claude config not found: {config_path}")
        return False

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)

        if "mcpServers" in config and "weixin-reader" in config["mcpServers"]:
            print_status("ok", "MCP server configured")
            return True
        else:
            print_status("warning", "MCP server not configured (manual setup needed)")
            return False
    except Exception as e:
        print_status("error", f"Cannot read config: {e}")
        return False

def check_mcp_server():
    """Check MCP server file"""
    skill_dir = Path(__file__).parent
    mcp_server = skill_dir / "wexin-read-mcp" / "src" / "server.py"

    if mcp_server.exists():
        print_status("ok", "MCP server file exists")
        return True
    else:
        print_status("error", f"MCP server file missing: {mcp_server}")
        return False

def check_notebook_library():
    """Check notebook library script"""
    skill_dir = Path(__file__).parent
    library_script = skill_dir / "scripts" / "notebook_library.py"

    if library_script.exists():
        print_status("ok", "notebook_library.py exists")
        return True
    else:
        print_status("error", f"notebook_library.py missing: {library_script}")
        return False

def check_notebooklm_auth():
    """Check NotebookLM authentication status"""
    import subprocess

    try:
        result = subprocess.run(["notebooklm", "list"],
                              capture_output=True,
                              text=True,
                              timeout=10)

        if result.returncode == 0:
            print_status("ok", "NotebookLM authenticated")
            return True
        else:
            print_status("warning", "NotebookLM not authenticated (run notebooklm login)")
            return False
    except subprocess.TimeoutExpired:
        print_status("warning", "NotebookLM auth check timed out")
        return False
    except Exception as e:
        print_status("error", f"NotebookLM auth check failed: {e}")
        return False

def main():
    print(f"\n{BLUE}========================================{NC}")
    print(f"{BLUE}  Environment Check - notebooklm-unified{NC}")
    print(f"{BLUE}========================================{NC}\n")

    results = []

    # 1. Python version
    print(f"{YELLOW}[1/8] Python version{NC}")
    results.append(check_python_version())
    print()

    # 2. Core dependencies
    print(f"{YELLOW}[2/8] Core Python dependencies{NC}")
    results.append(check_module("fastmcp"))
    results.append(check_module("beautifulsoup4", "bs4"))
    results.append(check_module("lxml"))
    results.append(check_module("markitdown"))
    print()

    # 3. NotebookLM CLI
    print(f"{YELLOW}[3/8] NotebookLM CLI{NC}")
    results.append(check_command("notebooklm"))
    print()

    # 4. markitdown CLI
    print(f"{YELLOW}[4/8] markitdown CLI{NC}")
    results.append(check_command("markitdown"))
    print()

    # 5. Git
    print(f"{YELLOW}[5/8] Git{NC}")
    results.append(check_command("git"))
    print()

    # 6. MCP server file
    print(f"{YELLOW}[6/8] MCP server file{NC}")
    results.append(check_mcp_server())
    print()

    # 7. Notebook library script
    print(f"{YELLOW}[7/8] Notebook library script{NC}")
    results.append(check_notebook_library())
    print()

    # 8. MCP config
    print(f"{YELLOW}[8/8] MCP configuration{NC}")
    results.append(check_mcp_config())
    print()

    # Summary
    print(f"{BLUE}========================================{NC}")
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"{GREEN}All checks passed ({passed}/{total}). Environment ready.{NC}")
    elif passed >= total * 0.8:
        print(f"{YELLOW}Most checks passed ({passed}/{total}), some issues to fix.{NC}")
    else:
        print(f"{RED}Checks failed ({passed}/{total}). Run install.sh to fix.{NC}")

    print(f"{BLUE}========================================{NC}\n")

    if passed < total:
        print("Fix suggestions:")
        print("  1. Run install script: python3 install.py (macOS) / python install.py (Windows)")
        print("  2. Configure MCP: edit ~/.claude/config.json")
        print("  3. Authenticate: notebooklm login")
        print()

    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
