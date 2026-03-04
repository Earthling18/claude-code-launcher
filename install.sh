#!/bin/bash

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Claude Code Launcher 安装脚本 ===${NC}"
echo ""

# 检测系统
if [ "$(uname -s)" != "Darwin" ]; then
    echo -e "${RED}错误：此脚本仅支持 macOS${NC}"
    exit 1
fi

# 检测架构
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    echo "检测到 Apple Silicon (arm64)"
elif [ "$ARCH" = "x86_64" ]; then
    echo "检测到 Intel (x86_64)"
else
    echo -e "${RED}错误：不支持的架构 $ARCH${NC}"
    exit 1
fi

# 获取最新版本号
echo -e "${YELLOW}获取最新版本...${NC}"
LATEST_VERSION=$(curl -sL https://api.github.com/repos/Earthling18/claude-code-launcher/releases/latest | grep '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')
if [ -z "$LATEST_VERSION" ]; then
    echo -e "${RED}错误：无法获取最新版本${NC}"
    exit 1
fi
echo "最新版本: v${LATEST_VERSION}"

# 优先使用 universal binary，否则按架构选择
DMG_NAME_UNIVERSAL="Claude.Code.Launcher_${LATEST_VERSION}_universal.dmg"
DMG_URL_UNIVERSAL="https://github.com/Earthling18/claude-code-launcher/releases/download/v${LATEST_VERSION}/${DMG_NAME_UNIVERSAL}"

if curl -sI -o /dev/null -w "%{http_code}" -L "$DMG_URL_UNIVERSAL" | grep -q "200"; then
    DMG_NAME="$DMG_NAME_UNIVERSAL"
else
    # 回退到架构特定版本
    if [ "$ARCH" = "arm64" ]; then
        DMG_NAME="Claude.Code.Launcher_${LATEST_VERSION}_aarch64.dmg"
    else
        DMG_NAME="Claude.Code.Launcher_${LATEST_VERSION}_x64.dmg"
    fi
fi
DMG_URL="https://github.com/Earthling18/claude-code-launcher/releases/download/v${LATEST_VERSION}/${DMG_NAME}"
DMG_PATH="/tmp/claude-code-launcher.dmg"
VOLUME_NAME="Claude Code Launcher"
APP_NAME="Claude Code Launcher.app"

# 清理函数
cleanup() {
    echo "清理临时文件..."
    hdiutil detach "/Volumes/${VOLUME_NAME}" -quiet 2>/dev/null || true
    rm -f "$DMG_PATH" 2>/dev/null || true
}
trap cleanup EXIT

# 下载
echo -e "${YELLOW}[1/4] 下载中...${NC}"
curl -L --progress-bar -o "$DMG_PATH" "$DMG_URL"

# 挂载
echo -e "${YELLOW}[2/4] 挂载 DMG...${NC}"
hdiutil attach "$DMG_PATH" -quiet -nobrowse

# 安装
echo -e "${YELLOW}[3/4] 安装应用到 /Applications...${NC}"
if [ -d "/Applications/${APP_NAME}" ]; then
    echo "检测到旧版本，正在移除..."
    rm -rf "/Applications/${APP_NAME}"
fi
cp -R "/Volumes/${VOLUME_NAME}/${APP_NAME}" /Applications/

# 移除隔离属性
echo -e "${YELLOW}[4/4] 配置应用权限...${NC}"
xattr -cr "/Applications/${APP_NAME}"

echo ""
echo -e "${GREEN}✓ 安装完成！${NC}"
echo ""
echo "你可以通过以下方式启动应用："
echo "  1. 在 Launchpad 中找到 Claude Code Launcher"
echo "  2. 或运行: open '/Applications/${APP_NAME}'"
echo ""

# 询问是否立即打开
read -p "是否现在打开应用？[Y/n] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    open "/Applications/${APP_NAME}"
fi
