"""
安全钩子 — PreToolUse Hook 实现（黑名单模式）

利用 Claude Agent SDK 的 PreToolUse Hook，在工具执行前拦截敏感操作。
默认放行，仅阻止已知敏感路径和危险命令。

用法：
    from app.core.security_hooks import build_security_hooks
    options.hooks = build_security_hooks()
"""
import logging
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, Optional, cast

from claude_agent_sdk import HookMatcher
from claude_agent_sdk.types import (
    HookCallback,
    HookContext,
    HookInput,
    PreToolUseHookInput,
    SyncHookJSONOutput,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 黑名单定义
# ──────────────────────────────────────────────

# .claude/ 下允许访问的子路径（技能脚本和参考文件）
_ALLOWED_CLAUDE_SUBPATHS: list[str] = [
    ".claude/skills/",
]

# app/ 路径片段需要排除 workspace 下的 app 目录（用户文件不受影响）
_APP_SAFE_PREFIXES: list[str] = [
    "workspace/",
    "workspace\\",
]

# 文件名/路径片段黑名单（大小写不敏感匹配）
_BLOCKED_FILE_PATTERNS: list[str] = [
    # 系统提示 & 项目配置
    "system_prompt.md",
    ".env",
    "claude.md",  # 匹配 CLAUDE.md

    # SDK 指令目录
    ".claude/",
    ".claude\\",

    # 应用代码目录（含安全规则、SDK配置、API结构、推送鉴权）
    "app/",
    "app\\",

    # 浏览器凭证
    "login data",
    "cookies",
    "web data",
    "chrome/",
    "chrome\\",
    "chromium/",
    "chromium\\",
    "microsoft/edge/",
    "microsoft\\edge\\",
    "google/chrome/",
    "google\\chrome\\",

    # 系统密钥 & 证书
    "keychain",
    ".ssh/",
    ".ssh\\",

    # Windows 系统
    "c:\\windows\\",
    "c:/windows/",
    "\\windows\\system32",
    "/windows/system32",
    "\\windows\\syswow64",
    "/windows/syswow64",

    # Git 凭证
    ".git/config",
    ".git\\config",
    ".gitconfig",
]

# 文件扩展名黑名单
_BLOCKED_FILE_EXTENSIONS: list[str] = [
    ".pem",
    ".key",
    ".p12",
    ".pfx",
]

# 精确文件名黑名单（仅匹配文件名部分，大小写不敏感）
_BLOCKED_EXACT_FILENAMES: list[str] = [
    "sam",
    "system",
    "security",
    "ntds.dit",
]

# Bash 命令黑名单（正则，大小写不敏感）
_BLOCKED_BASH_PATTERNS: list[re.Pattern] = [
    # 批量删除（cmd + bash + PowerShell）
    re.compile(r"rm\s+(-\w*r\w*f|--recursive).*(/|\\)", re.IGNORECASE),
    re.compile(r"del\s+/s\s+/q\s+[a-z]:\\", re.IGNORECASE),
    re.compile(r"rmdir\s+/s", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r"remove-item\s.*-recurse", re.IGNORECASE),  # PowerShell rm -rf

    # 磁盘与启动
    re.compile(r"\bdiskpart\b", re.IGNORECASE),   # 磁盘分区管理
    re.compile(r"\bbcdedit\b", re.IGNORECASE),     # 启动配置

    # 系统操作
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\brestart\b.*\bcomputer\b", re.IGNORECASE),

    # Windows 服务管理
    re.compile(r"\bsc\s+(delete|stop|config)\b", re.IGNORECASE),

    # 用户与权限
    re.compile(r"\bnet\s+(user|localgroup)\b", re.IGNORECASE),

    # 系统文件与镜像
    re.compile(r"\bsfc\b", re.IGNORECASE),
    re.compile(r"\bdism\b", re.IGNORECASE),
    re.compile(r"\bwmic\b", re.IGNORECASE),

    # 环境变量修改
    re.compile(r"\bsetx\b", re.IGNORECASE),                                    # cmd setx
    re.compile(r"\[environment\]::setenvironmentvariable", re.IGNORECASE),      # PowerShell

    # 凭证窃取
    re.compile(r"sqlite3.*login\s*data", re.IGNORECASE),
    re.compile(r"security\s+find.*password", re.IGNORECASE),
    re.compile(r"\bcmdkey\b.*\/list", re.IGNORECASE),
    re.compile(r"credential\s*manager", re.IGNORECASE),

    # 注册表破坏（cmd + PowerShell）
    re.compile(r"reg\s+delete\s+.*hklm", re.IGNORECASE),
    re.compile(r"reg\s+add\s+.*hklm", re.IGNORECASE),                          # 扩大到所有 HKLM 写入
    re.compile(r"set-itemproperty\s.*registry", re.IGNORECASE),                 # PowerShell 注册表
    re.compile(r"set-itemproperty\s.*hklm:", re.IGNORECASE),                    # PowerShell HKLM:

    # 网络下载 → 执行
    re.compile(r"curl\s.*\|\s*(sh|bash|python|powershell)", re.IGNORECASE),
    re.compile(r"wget\s.*\|\s*(sh|bash|python|powershell)", re.IGNORECASE),
    re.compile(r"invoke-webrequest.*\|\s*invoke-expression", re.IGNORECASE),
    re.compile(r"iex\s*\(.*downloadstring", re.IGNORECASE),

    # 读取敏感文件（通过 Bash 绕过文件钩子）
    re.compile(r"(cat|type|more|less|head|tail|get-content).*\.env\b", re.IGNORECASE),
    re.compile(r"(cat|type|more|less|head|tail|get-content).*system_prompt\.md", re.IGNORECASE),
    re.compile(r"(cat|type|more|less|head|tail|get-content).*claude\.md", re.IGNORECASE),
    re.compile(r"(cat|type|more|less|head|tail|get-content).*config\.py", re.IGNORECASE),
    re.compile(r"(cat|type|more|less|head|tail|get-content).*\.ssh[\\/]", re.IGNORECASE),
    re.compile(r"(cat|type|more|less|head|tail|get-content).*\.pem\b", re.IGNORECASE),
    re.compile(r"(cat|type|more|less|head|tail|get-content).*\.key\b", re.IGNORECASE),
]


# ──────────────────────────────────────────────
# 路径检查逻辑
# ──────────────────────────────────────────────

def _normalize_path(raw: str) -> str:
    """标准化路径用于匹配（小写、统一分隔符）"""
    return raw.replace("\\", "/").lower()


def _is_blocked_file_path(raw_path: str) -> Optional[str]:
    """
    检查文件路径是否在黑名单中。

    Returns:
        阻止原因（str）或 None（放行）
    """
    normalized = _normalize_path(raw_path)

    # 1. 路径片段匹配
    for pattern in _BLOCKED_FILE_PATTERNS:
        pat_lower = pattern.replace("\\", "/").lower()
        if pat_lower in normalized:
            # 特例：.env 需要精确匹配文件名部分，避免误拦 .environment 等
            if pat_lower == ".env":
                # 提取文件名
                filename = normalized.split("/")[-1]
                if filename == ".env" or filename.startswith(".env."):
                    return f"Blocked: sensitive file (.env)"
                continue
            # 特例：.claude/ 目录需要放行允许的子路径（如 skills/）
            if pat_lower in (".claude/", ".claude\\"):
                if any(sub.replace("\\", "/").lower() in normalized
                       for sub in _ALLOWED_CLAUDE_SUBPATHS):
                    continue  # 放行 skill 目录
            # 特例：app/ 目录需要精确路径分段匹配
            # 只匹配独立的 app/ 段（如 app/xxx, /app/xxx, C:/mobot/app/xxx）
            # 不匹配 webapp/xxx, myapp/xxx, some_app/xxx 等
            if pat_lower in ("app/", "app\\"):
                if not re.search(r"(^|/)app/", normalized):
                    continue  # webapp/ myapp/ 等不匹配，跳过
                if any(prefix.replace("\\", "/").lower() in normalized
                       for prefix in _APP_SAFE_PREFIXES):
                    continue  # 放行 workspace 下的 app 目录
            return f"Blocked: matches pattern '{pattern}'"

    # 2. 扩展名检查
    try:
        suffix = Path(raw_path).suffix.lower()
        if suffix in _BLOCKED_FILE_EXTENSIONS:
            return f"Blocked: sensitive file extension ({suffix})"
    except Exception:
        pass

    # 3. Windows 系统文件精确名匹配（仅在系统目录下）
    if "windows" in normalized or "system32" in normalized:
        filename = normalized.split("/")[-1]
        for blocked_name in _BLOCKED_EXACT_FILENAMES:
            if filename == blocked_name.lower():
                return f"Blocked: Windows system file ({blocked_name})"

    return None  # 放行


def _is_blocked_bash_command(command: str) -> Optional[str]:
    """
    检查 Bash 命令是否在黑名单中。

    Returns:
        阻止原因（str）或 None（放行）
    """
    for pattern in _BLOCKED_BASH_PATTERNS:
        if pattern.search(command):
            return f"Blocked: dangerous command pattern ({pattern.pattern[:50]})"
    return None


# ──────────────────────────────────────────────
# 工具输入提取
# ──────────────────────────────────────────────

# 不同工具的路径参数名
_FILE_PATH_KEYS = {
    "Read": ["file_path"],
    "Write": ["file_path"],
    "Edit": ["file_path"],
    "Glob": ["pattern", "path"],
    "Grep": ["path", "glob"],
}


def _extract_file_paths(tool_name: str, tool_input: Dict[str, Any]) -> list[str]:
    """从工具输入中提取文件路径"""
    paths = []
    keys = _FILE_PATH_KEYS.get(tool_name, [])
    for key in keys:
        val = tool_input.get(key)
        if val and isinstance(val, str):
            paths.append(val)
    return paths


# ──────────────────────────────────────────────
# Hook 回调
# ──────────────────────────────────────────────

async def _pre_tool_use_hook(
    hook_input: HookInput,
    tool_use_id: Optional[str],
    context: HookContext,
) -> SyncHookJSONOutput:
    """
    PreToolUse Hook：黑名单模式拦截。

    对 Read/Write/Edit/Glob/Grep 检查路径黑名单。
    对 Bash 检查命令黑名单。
    其余工具直接放行。
    """
    if hook_input["hook_event_name"] != "PreToolUse":
        return {}

    pre = cast(PreToolUseHookInput, hook_input)
    tool_name = pre["tool_name"]
    tool_input = pre["tool_input"]

    # ── 文件类工具：路径黑名单检查 ──
    if tool_name in _FILE_PATH_KEYS:
        paths = _extract_file_paths(tool_name, tool_input)
        for path in paths:
            reason = _is_blocked_file_path(path)
            if reason:
                logger.warning(f"[SECURITY] BLOCKED {tool_name}({path}): {reason}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    },
                }

    # ── Bash：命令黑名单检查 ──
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        reason = _is_blocked_bash_command(command)
        if reason:
            logger.warning(f"[SECURITY] BLOCKED Bash({command[:80]}): {reason}")
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            }

    # ── 默认放行 ──
    return {}


# ──────────────────────────────────────────────
# 公开 API
# ──────────────────────────────────────────────

def build_security_hooks() -> Dict[str, list[HookMatcher]]:
    """
    构建安全钩子配置，注入到 ClaudeAgentOptions.hooks。

    用法：
        options = ClaudeAgentOptions(...)
        options.hooks = build_security_hooks()
    """
    return {
        "PreToolUse": [
            HookMatcher(
                matcher=None,  # 匹配所有工具
                hooks=[_pre_tool_use_hook],
                timeout=10.0,  # 10 秒超时
            ),
        ],
    }
