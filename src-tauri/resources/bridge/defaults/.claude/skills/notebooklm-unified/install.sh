#!/bin/bash

# NotebookLM Unified Skill Installer
# Installs all dependencies and configures environment

set -e  # Exit on error

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_NAME="notebooklm-unified"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  NotebookLM Unified Skill Installer${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 1. Check Python version
echo -e "${YELLOW}[1/5] Checking Python environment...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python3 not found. Please install Python 3.9+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.9"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}Python version too low (current $PYTHON_VERSION, need 3.9+)${NC}"
    exit 1
fi

echo -e "${GREEN}Python $PYTHON_VERSION${NC}"

# 2. Check and clone wexin-read-mcp
echo ""
echo -e "${YELLOW}[2/5] Setting up MCP server...${NC}"
MCP_DIR="$SKILL_DIR/wexin-read-mcp"

if [ -d "$MCP_DIR" ]; then
    echo -e "${GREEN}MCP server already exists${NC}"
else
    echo "Cloning wexin-read-mcp..."
    git clone https://github.com/Bwkyd/wexin-read-mcp.git "$MCP_DIR"
    echo -e "${GREEN}MCP server cloned${NC}"
fi

# 3. Install Python dependencies
echo ""
echo -e "${YELLOW}[3/5] Installing Python dependencies...${NC}"

# Install MCP server dependencies
if [ -f "$MCP_DIR/requirements.txt" ]; then
    echo "Installing MCP dependencies..."
    pip3 install -r "$MCP_DIR/requirements.txt" -q
    echo -e "${GREEN}MCP dependencies installed${NC}"
fi

# Install Skill dependencies (includes markitdown)
if [ -f "$SKILL_DIR/requirements.txt" ]; then
    echo "Installing Skill dependencies (including markitdown)..."
    pip3 install -r "$SKILL_DIR/requirements.txt" -q
    echo -e "${GREEN}Skill dependencies installed${NC}"
fi

# 4. Check and install notebooklm CLI
echo ""
echo -e "${YELLOW}[4/5] Checking NotebookLM CLI...${NC}"

if command -v notebooklm &> /dev/null; then
    NOTEBOOKLM_VERSION=$(notebooklm --version 2>/dev/null || echo "unknown")
    echo -e "${GREEN}NotebookLM CLI already installed ($NOTEBOOKLM_VERSION)${NC}"
else
    echo "Installing notebooklm-py..."
    pip3 install git+https://github.com/teng-lin/notebooklm-py.git -q

    if command -v notebooklm &> /dev/null; then
        echo -e "${GREEN}NotebookLM CLI installed${NC}"
    else
        echo -e "${RED}NotebookLM CLI installation failed${NC}"
        echo "Please install manually: pip3 install git+https://github.com/teng-lin/notebooklm-py.git"
        exit 1
    fi
fi

# 5. Configuration guidance
echo ""
echo -e "${YELLOW}[5/5] Configuration guidance${NC}"
echo ""

CLAUDE_CONFIG="$HOME/.claude/config.json"
CONFIG_SNIPPET="    \"weixin-reader\": {
      \"command\": \"python\",
      \"args\": [
        \"$MCP_DIR/src/server.py\"
      ]
    }"

echo -e "${BLUE}Next step: Configure MCP server${NC}"
echo ""
echo "Edit $CLAUDE_CONFIG"
echo ""
echo "Add to \"mcpServers\":"
echo -e "${GREEN}$CONFIG_SNIPPET${NC}"
echo ""

# Check if already configured
if [ -f "$CLAUDE_CONFIG" ]; then
    if grep -q "weixin-reader" "$CLAUDE_CONFIG"; then
        echo -e "${GREEN}weixin-reader configuration detected${NC}"
    else
        echo -e "${YELLOW}weixin-reader not configured yet, please add manually${NC}"
    fi
else
    echo -e "${YELLOW}Claude config file not found, please create it${NC}"
fi

echo ""
echo -e "${BLUE}NotebookLM Authentication${NC}"
echo ""
echo "Before first use, run:"
echo -e "${GREEN}  notebooklm login${NC}"
echo -e "${GREEN}  notebooklm list  # verify auth success${NC}"
echo ""

# Final summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Installation complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Install location: $SKILL_DIR"
echo ""
echo "Important reminders:"
echo "  1. Restart Claude Code after configuring MCP server"
echo "  2. Run notebooklm login before first use"
echo ""
echo "Usage examples:"
echo "  Generate podcast: notebooklm create \"Title\" && notebooklm use <ID> && notebooklm generate audio"
echo "  Query notebook:   notebooklm ask \"Your question\""
echo ""
