#!/bin/bash

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Claude Code Launcher 安装脚本 ===${NC}"
echo ""

# 检测架构
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    DMG_NAME="Claude.Code.Launcher_0.2.4_aarch64.dmg"
else
    echo -e "${RED}错误：此脚本仅支持 macOS ARM64 (Apple Silicon)${NC}"
    echo "如果你使用的是 Intel Mac，请手动下载安装"
    exit 1
fi

DMG_URL="https://github.com/Earthling18/claude-code-launcher/releases/latest/download/${DMG_NAME}"
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
