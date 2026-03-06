"""
Claude Agent 服务
封装 Claude Agent SDK，提供对话功能
"""
import asyncio
import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
import logging

from claude_agent_sdk import query, ClaudeAgentOptions
import claude_agent_sdk

import app.config as config
from app.config import settings
from app.core.session_manager import Session, session_manager
from app.core.sse_handler import SSEHandler, format_blocking_response
from app.core.query_parser import parse_query_info, build_file_context, ParsedQuery
from app.core.file_processor import ProcessedFile, FileCategory
from app.core.message_builder import MessageBuilder
from app.core.security_hooks import build_security_hooks
from app.services.cos_client import cos_client
from app.mcp_tools.file_output_tool import create_file_output_server

logger = logging.getLogger(__name__)

# Module build stamp — helps diagnose whether update actually replaced this file
_MODULE_BUILD = "2026-03-04"


def _log_stderr(line: str) -> None:
    """
    记录 CLI 的 stderr 输出（包括红色警告）

    当 Claude CLI 遇到 "Prompt is too long" 等错误时，
    会在 stderr 输出红色警告。通过捕获这些输出，
    可以帮助诊断问题，同时 SDK 会将错误传递给 Claude 让其重试。
    """
    # 过滤空行和纯空白
    if not line or not line.strip():
        return

    # 检测常见的错误模式
    line_lower = line.lower()
    if "prompt is too long" in line_lower or "context" in line_lower:
        logger.warning(f"[CLI STDERR] Context limit warning: {line}")
    elif "error" in line_lower or "failed" in line_lower:
        logger.warning(f"[CLI STDERR] Error: {line}")
    else:
        logger.info(f"[CLI STDERR] {line}")


def load_soul() -> tuple[str, bool]:
    """加载身份人格文件，返回 (内容, 是否已配置)"""
    soul_file = settings.resolved_soul_file
    if soul_file.exists():
        content = soul_file.read_text(encoding="utf-8-sig").strip()
        if content:
            logger.info(f"Loading soul from: {soul_file}")
            return content, True
        logger.info("Soul file exists but is empty, will inject setup guide")
    else:
        logger.info("Soul file not found, will inject setup guide")
    return "你是一个智能工作助手，运行在企业微信环境中。", False


def load_prompt_part(filename: str) -> str:
    """从 prompt_data 或 app/prompts/ 加载 prompt 模块"""
    # 优先从编译的 prompt_data 模块加载（分发环境）
    try:
        from app.core.prompt_data import get_prompt_part
        content = get_prompt_part(filename)
        if content:
            return content
    except ImportError:
        pass
    # Fallback: 文件系统（开发环境）
    path = Path(__file__).parent.parent / "prompts" / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logger.warning(f"Prompt part not found: {path}")
    return ""


def load_system_prompt() -> str:
    """
    加载系统提示，自动注入 soul.md 到 {soul} 占位符

    加载优先级：
    1. prompt_data.py 中的 SYSTEM_PROMPT 常量（编译分发环境）
    2. system_prompt.md 文件（开发环境）
    3. 内置默认值

    当 soul.md 不存在时，在末尾追加首次设置引导指令。
    """
    soul_content, soul_configured = load_soul()

    # 优先从编译的 prompt_data 模块加载
    try:
        from app.core.prompt_data import SYSTEM_PROMPT
        logger.info("Loading system prompt from prompt_data module")
        content = SYSTEM_PROMPT
        if "{soul}" in content:
            content = content.replace("{soul}", soul_content)
    except ImportError:
        content = None

    if content is None:
        # Fallback: 从 app/prompts/ 模块化组合
        logger.info("Loading system prompt from modular prompts/")
        parts = [
            f"# 身份\n\n{soul_content}",
            load_prompt_part("style.md"),
            load_prompt_part("main_work.md"),
            load_prompt_part("skill_protocol.md"),
            load_prompt_part("security.md"),
        ]
        content = "\n\n".join(p for p in parts if p)

    # 未配置 soul 时追加首次引导
    if not soul_configured:
        soul_path = str(settings.resolved_soul_file)
        # 优先从 prompt_data 加载 guide
        guide_text = None
        try:
            from app.core.prompt_data import SOUL_SETUP_GUIDE
            if SOUL_SETUP_GUIDE:
                guide_text = SOUL_SETUP_GUIDE
        except ImportError:
            pass
        if guide_text is None:
            guide_file = settings.resolved_soul_file.parent / "soul_setup_guide.md"
            if guide_file.exists():
                guide_text = guide_file.read_text(encoding="utf-8")
            else:
                guide_text = "请问你希望我叫什么名字、有什么性格特点？"
        content += f"""

# 首次身份设置

用户的身份人格尚未配置。请参考以下引导模板，用自然对话的方式逐项询问用户：

{guide_text}

收集完毕后，整合为一段连贯的身份人格描述（100-200字），用 Write 工具写入 {soul_path}，告知用户已生效。
如果用户表示跳过或不想设置，将默认内容「你是一个智能工作助手，运行在企业微信环境中。」写入 {soul_path}，然后正常响应用户的问题。
注意：如果当前是群聊，不要引导设置，直接将默认内容写入 {soul_path} 后正常响应。
"""

    return content


def load_collab_system_prompt() -> str:
    """
    加载协作模式系统提示，自动注入 soul.md 到 {soul} 占位符

    与 load_system_prompt() 逻辑类似，但加载 system_prompt_collab.md。
    当 soul.md 不存在时，在末尾追加首次设置引导指令。
    """
    soul_content, soul_configured = load_soul()

    # 优先从编译的 prompt_data 模块加载
    try:
        from app.core.prompt_data import COLLAB_SYSTEM_PROMPT
        logger.info("Loading collab system prompt from prompt_data module")
        content = COLLAB_SYSTEM_PROMPT
        if "{soul}" in content:
            content = content.replace("{soul}", soul_content)
    except (ImportError, AttributeError):
        content = None

    if content is None:
        # Fallback: 从 app/prompts/ 模块化组合
        logger.info("Loading collab system prompt from modular prompts/")
        parts = [
            f"# 身份\n\n{soul_content}",
            load_prompt_part("style.md"),
            load_prompt_part("collab_work.md"),
            load_prompt_part("skill_protocol.md"),
            load_prompt_part("security.md"),
        ]
        content = "\n\n".join(p for p in parts if p)

    # 未配置 soul 时追加首次引导
    if not soul_configured:
        soul_path = str(settings.resolved_soul_file)
        # 优先从 prompt_data 加载 guide
        guide_text = None
        try:
            from app.core.prompt_data import SOUL_SETUP_GUIDE
            if SOUL_SETUP_GUIDE:
                guide_text = SOUL_SETUP_GUIDE
        except ImportError:
            pass
        if guide_text is None:
            guide_file = settings.resolved_soul_file.parent / "soul_setup_guide.md"
            if guide_file.exists():
                guide_text = guide_file.read_text(encoding="utf-8")
            else:
                guide_text = "请问你希望我叫什么名字、有什么性格特点？"
        content += f"""

# 首次身份设置

用户的身份人格尚未配置。请参考以下引导模板，用自然对话的方式逐项询问用户：

{guide_text}

收集完毕后，整合为一段连贯的身份人格描述（100-200字），用 Write 工具写入 {soul_path}，告知用户已生效。
如果用户表示跳过或不想设置，将默认内容「你是一个智能工作助手，运行在企业微信环境中。」写入 {soul_path}，然后正常响应用户的问题。
注意：如果当前是群聊，不要引导设置，直接将默认内容写入 {soul_path} 后正常响应。
"""

    return content


def load_worker_system_prompt() -> str:
    """
    加载 Worker 系统提示（精简版，不继承主 prompt）

    优先从 prompt_data.WORKER_BODY 加载，fallback 到文件系统，最后内置默认值。
    """
    # 优先从编译的 prompt_data 模块加载（分发环境）
    try:
        from app.core.prompt_data import WORKER_BODY
        logger.info("Loading worker system prompt from prompt_data module")
        return WORKER_BODY
    except ImportError:
        pass

    # Fallback: 文件系统（开发环境）
    prompts_dir = Path(__file__).parent.parent / "prompts"
    worker_file = prompts_dir / "worker_body.md"

    if worker_file.exists():
        logger.info("Loading worker system prompt from prompts/worker_body.md")
        content = worker_file.read_text(encoding="utf-8").strip()
        # 追加共享的 Skill 执行规则
        skill_protocol = load_prompt_part("skill_protocol.md")
        if skill_protocol:
            content = content + "\n\n" + skill_protocol
        return content

    # Fallback: 内置默认值
    logger.warning("Worker prompt file not found, using built-in default")
    return (
        "# 独立任务执行\n\n"
        "你正在独立执行一个委派任务。工作目录：{workspace}，任务类型：{task_type}。\n"
        "专注执行任务，完成后提供完整结果。"
    )


def load_mcp_config() -> Optional[Dict]:
    """
    加载 MCP 配置
    从 .mcp.json 文件加载 MCP servers 配置
    """
    mcp_file = Path(settings.resolved_mcp_config_file)
    if mcp_file.exists():
        try:
            content = mcp_file.read_text(encoding="utf-8")
            config = json.loads(content)
            logger.info(f"Loaded MCP config: {list(config.get('mcpServers', {}).keys())}")
            return config
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
    return None


class ClaudeAgentService:
    """
    Claude Agent 服务
    - 封装 SDK 调用
    - 支持技能指令注入
    - 支持 MCP 工具配置
    - 支持多轮对话（通过 session_id resume）
    - 转换消息流为 SSE 事件
    """

    def __init__(self):
        # 调试：打印配置加载情况
        logger.info(f"[CONFIG] claude_auth_mode: {settings.claude_auth_mode}")
        logger.info(f"[CONFIG] claude_api_key: {settings.claude_api_key[:15] if settings.claude_api_key else 'EMPTY'}...")
        logger.info(f"[CONFIG] claude_api_base: {settings.claude_api_base}")
        logger.info(f"[CONFIG] claude_model: {settings.claude_model}")
        logger.info(f"[CONFIG] claude_cli_path: {settings.claude_cli_path or 'DEFAULT'}")

        # 根据认证模式设置环境变量
        if settings.claude_auth_mode == "key":
            # Key 模式：设置 ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL
            logger.info("[AUTH] Using API Key mode")
            if settings.claude_api_key:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = settings.claude_api_key
                os.environ["ANTHROPIC_API_KEY"] = settings.claude_api_key
            if settings.claude_api_base:
                os.environ["ANTHROPIC_BASE_URL"] = settings.claude_api_base
        else:
            # OAuth 模式（默认）：使用 Claude Code 登录凭证
            logger.info("[AUTH] Using OAuth mode (Claude Code credentials)")
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANTHROPIC_BASE_URL", None)
            # 校验 OAuth 凭证
            valid, error, _ = settings.check_oauth_status()
            if not valid:
                logger.error(f"[AUTH] {error}")
            else:
                logger.info("[AUTH] OAuth credentials valid")

        # Pre-flight check 模型覆盖（解决 Haiku 经 dashscope 代理超时问题）
        if settings.claude_small_fast_model:
            os.environ["ANTHROPIC_SMALL_FAST_MODEL"] = settings.claude_small_fast_model
            logger.info(f"[PREFLIGHT] ANTHROPIC_SMALL_FAST_MODEL = {settings.claude_small_fast_model}")

        self.model = settings.claude_model
        self.base_system_prompt = load_system_prompt()
        self.collab_system_prompt = load_collab_system_prompt()
        self.worker_system_prompt = load_worker_system_prompt()
        self.mcp_config = load_mcp_config()

        # 渠道表情 prompt（按渠道注入对应表情集）
        self.emoticon_prompts: Dict[str, str] = {}
        for ch in ("wecom", "feishu"):
            content = load_prompt_part(f"emoticons_{ch}.md")
            if content:
                self.emoticon_prompts[ch] = content

        # 自动检测 git-bash（bundled MinGit 或系统安装）
        self._setup_git_bash()

        # 网络代理配置
        self._setup_proxy()

        # ANTHROPIC_* 环境变量防护（防止用户 settings.json env 块注入干扰）
        self._setup_anthropic_env()

        # 写入 settings.local.json 覆盖，防止用户 ~/.claude/settings.json 干扰 Agent 配置
        self._write_settings_overrides()

        # 配了代理时，内网地址不走代理（bridge server、localhost）
        if settings.claude_http_proxy or settings.claude_https_proxy:
            no_proxy = os.environ.get("NO_PROXY", "")
            internal_hosts = "172.21.11.82,localhost,127.0.0.1"
            if no_proxy:
                # 合并已有的 NO_PROXY
                existing = set(h.strip() for h in no_proxy.split(",") if h.strip())
                for h in internal_hosts.split(","):
                    existing.add(h)
                internal_hosts = ",".join(sorted(existing))
            os.environ["NO_PROXY"] = internal_hosts
            os.environ["no_proxy"] = internal_hosts
            logger.info(f"[PROXY] NO_PROXY = {internal_hosts}")

        # 模块版本水印（区分"文件被替换但版本错误"和"文件未被替换"）
        logger.info(f"[AGENT] Module build: {_MODULE_BUILD}, file: {__file__}")

        # 启动诊断
        self._log_diagnostics()

        # 隔离诊断
        self.diagnose_isolation()

        # 基础工具列表（用户可通过配置扩展）
        self.allowed_tools = self._load_allowed_tools()

    def _setup_git_bash(self):
        """
        自动检测 git-bash 并设置 CLAUDE_CODE_GIT_BASH_PATH

        Claude Code CLI 在 Windows 上依赖 git-bash。
        检测顺序：
        1. 环境变量已设置且文件存在 → 跳过
        2. bash 已在 PATH 中 → 跳过
        3. bundled MinGit（lib/mingit/bin/bash.exe）
        4. 常见系统安装路径
        """
        if platform.system() != "Windows":
            return

        # 已设置且有效
        existing = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
        if existing and Path(existing).is_file():
            logger.info(f"[GIT_BASH] Already set: {existing}")
            return

        # bash 已在 PATH 中（用户已装 Git for Windows）
        if shutil.which("bash"):
            logger.info("[GIT_BASH] bash found in PATH, no override needed")
            return

        # 检查 bundled MinGit（相对于 claude_agent_sdk 包所在的 lib/ 目录）
        try:
            sdk_dir = Path(claude_agent_sdk.__file__).parent
            lib_dir = sdk_dir.parent  # lib/
            bundled_bash = lib_dir / "mingit" / "usr" / "bin" / "bash.exe"
            if bundled_bash.is_file():
                os.environ["CLAUDE_CODE_GIT_BASH_PATH"] = str(bundled_bash)
                logger.info(f"[GIT_BASH] Using bundled MinGit: {bundled_bash}")
                return
        except Exception:
            pass

        # 常见系统安装路径
        system_paths = [
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
            Path(os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "bin", "bash.exe"),
        ]
        for p in system_paths:
            if p.is_file():
                os.environ["CLAUDE_CODE_GIT_BASH_PATH"] = str(p)
                logger.info(f"[GIT_BASH] Using system Git: {p}")
                return

        logger.warning(
            "[GIT_BASH] bash.exe not found! Claude Code CLI may fail to start. "
            "Install Git for Windows: https://git-scm.com/download/win"
        )

    def _setup_proxy(self):
        """
        配置网络代理环境变量

        策略：配了就用，没配就彻底清空。
        当 .env 未配置代理时，主动清空 os.environ 中所有代理变量
        （包括终端继承的、Clash 等代理软件设的），确保 CLI 子进程不走代理。
        """
        # 需要管理的代理环境变量（大小写均需处理）
        proxy_vars = [
            "HTTP_PROXY", "http_proxy",
            "HTTPS_PROXY", "https_proxy",
            "ALL_PROXY", "all_proxy",
        ]

        has_any_proxy = settings.claude_http_proxy or settings.claude_https_proxy

        if has_any_proxy:
            # .env 配了代理 → 正常设置
            if settings.claude_http_proxy:
                os.environ["HTTP_PROXY"] = settings.claude_http_proxy
                os.environ["http_proxy"] = settings.claude_http_proxy
                logger.info(f"[PROXY] HTTP_PROXY = {settings.claude_http_proxy}")
            if settings.claude_https_proxy:
                os.environ["HTTPS_PROXY"] = settings.claude_https_proxy
                os.environ["https_proxy"] = settings.claude_https_proxy
                logger.info(f"[PROXY] HTTPS_PROXY = {settings.claude_https_proxy}")
            if settings.claude_no_proxy:
                os.environ["NO_PROXY"] = settings.claude_no_proxy
                os.environ["no_proxy"] = settings.claude_no_proxy
                logger.info(f"[PROXY] NO_PROXY = {settings.claude_no_proxy}")
        else:
            # .env 没配代理 → 彻底清空，防止终端/Clash 继承的代理干扰 CLI 子进程
            cleared = []
            for var in proxy_vars:
                if var in os.environ:
                    del os.environ[var]
                    cleared.append(var)
            # NO_PROXY 也一并清理
            for var in ("NO_PROXY", "no_proxy"):
                if var in os.environ:
                    del os.environ[var]
                    cleared.append(var)
            if cleared:
                logger.info(f"[PROXY] Cleared inherited proxy vars: {cleared}")
            else:
                logger.info("[PROXY] No proxy configured, environment clean")

    def _setup_anthropic_env(self):
        """设置/清除 ANTHROPIC_* 环境变量，防止用户 settings.json env 块注入干扰

        - key 模式：显式设置为 .env 中配置的值
        - oauth 模式：清除这些变量（避免干扰 CLI 默认 OAuth 认证流程）
        """
        if settings.claude_auth_mode == "key":
            if settings.claude_api_key:
                os.environ["ANTHROPIC_API_KEY"] = settings.claude_api_key
                logger.info("[AUTH] Set ANTHROPIC_API_KEY from .env (key mode)")
            if settings.claude_api_base:
                os.environ["ANTHROPIC_BASE_URL"] = settings.claude_api_base
                logger.info(f"[AUTH] Set ANTHROPIC_BASE_URL = {settings.claude_api_base} (key mode)")
        else:
            # OAuth 模式：清除这些变量
            cleared = []
            for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
                if var in os.environ:
                    del os.environ[var]
                    cleared.append(var)
            if cleared:
                logger.info(f"[AUTH] Cleared ANTHROPIC env vars (oauth mode): {cleared}")

    def _write_settings_overrides(self):
        """写入部署级设置覆盖到 settings.local.json

        配合 setting_sources=["project","local"]，确保 Agent 使用 .env 中的配置，
        而非用户 ~/.claude/settings.json 中的个人偏好。

        - model: 所有模式都写入（覆盖用户可能配置的不同模型）
        - apiUrl: 仅 key 模式写入（oauth 模式用 CLI 默认 endpoint）
        """
        if not config.resolved_agent_root:
            logger.info("[AUTH] Skipping settings overrides (agent_root not initialized)")
            return
        local_settings = Path(config.resolved_agent_root) / ".claude" / "settings.local.json"
        try:
            if not local_settings.parent.exists():
                local_settings.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if local_settings.exists():
                existing = json.loads(local_settings.read_text(encoding="utf-8"))

            changed = False

            # key 模式：写入 apiUrl
            if settings.claude_auth_mode == "key" and settings.claude_api_base:
                if existing.get("apiUrl") != settings.claude_api_base:
                    existing["apiUrl"] = settings.claude_api_base
                    changed = True
            elif settings.claude_auth_mode != "key" and "apiUrl" in existing:
                # oauth 模式：清除之前 key 模式残留的 apiUrl
                del existing["apiUrl"]
                changed = True

            # 所有模式：写入 model
            if existing.get("model") != settings.claude_model:
                existing["model"] = settings.claude_model
                changed = True

            if changed:
                local_settings.write_text(
                    json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                logger.info(f"[AUTH] Wrote settings overrides to {local_settings}: model={settings.claude_model}"
                            + (f", apiUrl={settings.claude_api_base}" if settings.claude_auth_mode == "key" else ""))
            else:
                logger.info(f"[AUTH] Settings overrides up to date: {local_settings}")
        except Exception as e:
            logger.warning(f"[AUTH] Failed to write settings overrides: {e}")

    def _build_settings_override(self) -> Optional[str]:
        """构建 --settings 内联 JSON，防止用户 ~/.claude/settings.json 干扰 apiUrl/model

        通过 ClaudeAgentOptions.settings 传递为 CLI --settings flag，
        具有最高优先级，可覆盖用户 settings.json 中的 apiUrl/model。

        所有模式都生成 model 覆盖；key 模式额外包含 apiUrl。
        这是抵御 settings.json 污染的最后防线。
        """
        override = {"model": settings.claude_model}
        if settings.claude_auth_mode == "key" and settings.claude_api_base:
            override["apiUrl"] = settings.claude_api_base
        return json.dumps(override)

    def _build_sdk_env(self) -> dict:
        """构建传递给 ClaudeAgentOptions.env 的环境变量

        key 模式：显式注入 ANTHROPIC_BASE_URL 和 ANTHROPIC_API_KEY，
        防止用户 ~/.claude/settings.json 的 env 块覆盖。
        """
        env = {}
        if settings.claude_auth_mode == "key":
            if settings.claude_api_key:
                env["ANTHROPIC_API_KEY"] = settings.claude_api_key
                env["ANTHROPIC_AUTH_TOKEN"] = settings.claude_api_key
            if settings.claude_api_base:
                env["ANTHROPIC_BASE_URL"] = settings.claude_api_base
        return env

    def _log_diagnostics(self):
        """启动诊断：输出运行环境关键信息，用于排查部署兼容问题"""
        try:
            # SDK 版本
            sdk_ver = getattr(claude_agent_sdk, "__version__", "unknown")
            logger.info(f"[DIAG] claude_agent_sdk version: {sdk_ver}")

            # 捆绑 CLI 路径和大小
            sdk_dir = Path(claude_agent_sdk.__file__).parent
            for name in ("claude.exe", "claude"):
                bundled = sdk_dir / "_bundled" / name
                if bundled.exists():
                    size_mb = bundled.stat().st_size / 1024 / 1024
                    logger.info(f"[DIAG] Bundled CLI: {bundled} ({size_mb:.1f} MB)")
                    break
            else:
                logger.info(f"[DIAG] Bundled CLI: not found in {sdk_dir / '_bundled'}")

            # Git-bash 路径
            git_bash = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
            if git_bash:
                logger.info(f"[DIAG] CLAUDE_CODE_GIT_BASH_PATH = {git_bash}")

            # ANTHROPIC_* 环境变量（脱敏）
            for key in sorted(os.environ):
                if key.startswith("ANTHROPIC"):
                    val = os.environ[key]
                    if "KEY" in key or "TOKEN" in key:
                        val = val[:8] + "..." if len(val) > 8 else "***"
                    logger.info(f"[DIAG] ENV {key} = {val}")

            # 代理环境变量
            for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                        "NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
                val = os.environ.get(key)
                if val:
                    logger.info(f"[DIAG] ENV {key} = {val}")

            # Windows 系统代理（注册表）
            if platform.system() == "Windows":
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                       r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                        enabled = winreg.QueryValueEx(k, "ProxyEnable")[0]
                        server = winreg.QueryValueEx(k, "ProxyServer")[0] if enabled else ""
                        logger.info(f"[DIAG] Windows proxy: enabled={enabled}, server='{server}'")
                except Exception:
                    logger.info("[DIAG] Windows proxy: unable to read registry")

            # 检测用户 settings.json 中可能干扰 Agent 的配置
            user_settings = Path.home() / ".claude" / "settings.json"
            if user_settings.exists():
                try:
                    data = json.loads(user_settings.read_text(encoding="utf-8"))
                    for key in ("apiUrl", "model", "apiKey"):
                        val = data.get(key)
                        if val:
                            if key == "apiKey":
                                val = val[:8] + "..." if len(val) > 8 else "***"
                            logger.warning(
                                f"[DIAG] User ~/.claude/settings.json has '{key}': {val} "
                                f"-- isolated by setting_sources=['project','local']"
                            )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[DIAG] Diagnostics failed: {e}")

    def diagnose_isolation(self) -> List[Dict]:
        """诊断 Agent 设置隔离状态，返回检查项列表

        每项包含: check(检查项), status(OK/WARN/ERROR), detail(详情), fix(修复方法)
        同时输出到日志。可通过 /api/v1/config/reload 触发。
        """
        results = []
        project_root = Path(__file__).parent.parent.parent.resolve()

        def _add(check: str, status: str, detail: str, fix: str = ""):
            results.append({"check": check, "status": status, "detail": detail, "fix": fix})

        try:
            logger.info("[ISOLATION] ====== Settings Isolation Diagnosis ======")

            # 1. Agent Root 存在性
            agent_root = Path(config.resolved_agent_root) if config.resolved_agent_root else None
            if agent_root and agent_root.exists() and agent_root.resolve() != project_root:
                _add("Agent root", "OK", f"{agent_root} (isolated from project root)")
                logger.info(f"[ISOLATION] [OK] Agent root: {agent_root} (isolated from project root)")
            elif agent_root and agent_root.resolve() == project_root:
                _add("Agent root", "WARN",
                     f"{agent_root} == project root (not isolated)",
                     "检查 WECOM_AGENT_ROOT 配置，或确认 ~/.mobot-bridge-agent/ 目录可创建")
                logger.warning(f"[ISOLATION] [WARN] Agent root: {agent_root} == project root (not isolated)")
                logger.warning("[ISOLATION]   FIX: 检查 WECOM_AGENT_ROOT 配置，或确认 ~/.mobot-bridge-agent/ 目录可创建")
            else:
                _add("Agent root", "ERROR",
                     f"Agent root not found: {agent_root}",
                     "检查 WECOM_AGENT_ROOT 配置，或确认 ~/.mobot-bridge-agent/ 目录可创建")
                logger.error(f"[ISOLATION] [ERROR] Agent root not found: {agent_root}")
                logger.error("[ISOLATION]   FIX: 检查 WECOM_AGENT_ROOT 配置，或确认 ~/.mobot-bridge-agent/ 目录可创建")

            # 2. .claude/ 应该是真实目录（非 Junction）
            if agent_root and agent_root.exists():
                claude_dir = agent_root / ".claude"
                if claude_dir.exists():
                    # 检测是否为 Junction/symlink（旧架构残留）
                    is_link = False
                    try:
                        os.readlink(str(claude_dir))
                        is_link = True
                    except (OSError, ValueError):
                        is_link = claude_dir.is_symlink()

                    if is_link:
                        _add(".claude directory", "ERROR",
                             f"{claude_dir} is a junction/symlink (old architecture, should be real directory)",
                             "重启服务自动迁移，或手动删除 agent_root/.claude junction 后重启")
                        logger.error(f"[ISOLATION] [ERROR] .claude directory: is junction/symlink (old architecture)")
                        logger.error("[ISOLATION]   FIX: 重启服务自动迁移，或手动删除 agent_root/.claude junction 后重启")
                    else:
                        _add(".claude directory", "OK", f"{claude_dir} (real directory)")
                        logger.info(f"[ISOLATION] [OK] .claude directory: {claude_dir} (real directory)")
                else:
                    _add(".claude directory", "ERROR", "Not found",
                         "重启服务自动创建")
                    logger.error("[ISOLATION] [ERROR] .claude directory: Not found")

            # 2b. .claude/skills/ 应该是 Junction → project/.claude/skills/
            if agent_root and agent_root.exists():
                link_skills = agent_root / ".claude" / "skills"
                source_skills = project_root / ".claude" / "skills"
                if link_skills.exists():
                    is_link = False
                    try:
                        os.readlink(str(link_skills))
                        is_link = True
                    except (OSError, ValueError):
                        is_link = link_skills.is_symlink()

                    if is_link:
                        try:
                            target = link_skills.resolve()
                            if target == source_skills.resolve():
                                _add("skills junction", "OK", f"-> {source_skills} (target correct)")
                                logger.info(f"[ISOLATION] [OK] skills junction: -> {source_skills} (target correct)")
                            else:
                                _add("skills junction", "ERROR",
                                     f"-> {target} (expected {source_skills})",
                                     "重启服务自动修复 skills junction")
                                logger.error(f"[ISOLATION] [ERROR] skills junction: -> {target} (expected {source_skills})")
                        except OSError as e:
                            _add("skills junction", "ERROR", f"Broken link: {e}",
                                 "重启服务自动修复 skills junction")
                            logger.error(f"[ISOLATION] [ERROR] skills junction: Broken link: {e}")
                    else:
                        _add("skills junction", "WARN",
                             "skills/ is a real directory (not junction, skills may be out of sync)",
                             "删除 agent_root/.claude/skills/ 后重启服务，自动创建 junction")
                        logger.warning("[ISOLATION] [WARN] skills junction: skills/ is a real directory (not junction)")
                else:
                    if source_skills.exists():
                        _add("skills junction", "ERROR", "Not found",
                             "重启服务自动创建 skills junction")
                        logger.error("[ISOLATION] [ERROR] skills junction: Not found")
                    else:
                        _add("skills junction", "WARN", "Source skills/ not found in project")
                        logger.warning("[ISOLATION] [WARN] skills junction: Source skills/ not found in project")

            # 2c. 项目 .claude/settings.local.json 污染检测
            project_local_settings = project_root / ".claude" / "settings.local.json"
            if project_local_settings.exists():
                try:
                    data = json.loads(project_local_settings.read_text(encoding="utf-8"))
                    if "model" in data or "apiUrl" in data:
                        _add("Project contamination", "ERROR",
                             f"Project .claude/settings.local.json contains agent config: "
                             f"{', '.join(k for k in ('model', 'apiUrl') if k in data)}",
                             "重启服务自动清理，或手动删除 project/.claude/settings.local.json")
                        logger.error("[ISOLATION] [ERROR] Project .claude/settings.local.json contains agent config (contamination)")
                    else:
                        _add("Project contamination", "OK", "settings.local.json exists but no agent config")
                        logger.info("[ISOLATION] [OK] Project .claude/settings.local.json: no agent config")
                except Exception:
                    _add("Project contamination", "WARN", "Unable to read project settings.local.json")
                    logger.warning("[ISOLATION] [WARN] Unable to read project .claude/settings.local.json")
            else:
                _add("Project contamination", "OK", "No settings.local.json in project (clean)")
                logger.info("[ISOLATION] [OK] Project contamination: No settings.local.json in project (clean)")

            # 3. settings.local.json 一致性
            if agent_root:
                local_settings_path = agent_root / ".claude" / "settings.local.json"
                if local_settings_path.exists():
                    try:
                        data = json.loads(local_settings_path.read_text(encoding="utf-8"))
                        issues = []
                        if data.get("model") != settings.claude_model:
                            issues.append(f"model={data.get('model')} (expected {settings.claude_model})")
                        if settings.claude_auth_mode == "key":
                            if data.get("apiUrl") != settings.claude_api_base:
                                issues.append(f"apiUrl={data.get('apiUrl')} (expected {settings.claude_api_base})")
                        if issues:
                            _add("settings.local.json", "WARN",
                                 f"Mismatch: {'; '.join(issues)}",
                                 "调用 /api/v1/config/reload 或重启服务，自动重新写入 settings.local.json")
                            logger.warning(f"[ISOLATION] [WARN] settings.local.json: Mismatch: {'; '.join(issues)}")
                            logger.warning("[ISOLATION]   FIX: 调用 /api/v1/config/reload 或重启服务，自动重新写入 settings.local.json")
                        else:
                            detail = f"model={settings.claude_model}"
                            if settings.claude_auth_mode == "key":
                                detail += f", apiUrl={settings.claude_api_base}"
                            detail += " (matches .env)"
                            _add("settings.local.json", "OK", detail)
                            logger.info(f"[ISOLATION] [OK] settings.local.json: {detail}")
                    except Exception as e:
                        _add("settings.local.json", "ERROR", f"Read failed: {e}",
                             "调用 /api/v1/config/reload 或重启服务，自动重新写入 settings.local.json")
                        logger.error(f"[ISOLATION] [ERROR] settings.local.json: Read failed: {e}")
                else:
                    _add("settings.local.json", "WARN", "Not found",
                         "调用 /api/v1/config/reload 或重启服务，自动重新写入 settings.local.json")
                    logger.warning("[ISOLATION] [WARN] settings.local.json: Not found")
                    logger.warning("[ISOLATION]   FIX: 调用 /api/v1/config/reload 或重启服务，自动重新写入 settings.local.json")

            # 4. 用户 ~/.claude/settings.json 冲突检测
            user_settings = Path.home() / ".claude" / "settings.json"
            has_settings_override = self._build_settings_override() is not None
            if user_settings.exists():
                try:
                    raw = user_settings.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    all_keys = list(data.keys())
                    logger.info(f"[ISOLATION] User settings.json: {len(raw)} bytes, keys={all_keys}")

                    conflicts = []
                    # 扩展检查范围：apiUrl + 可能的变体 key 名
                    for key in ("model", "apiUrl", "apiBaseUrl", "baseUrl", "apiKey"):
                        val = data.get(key)
                        if val:
                            display_val = val[:8] + "..." if key == "apiKey" and len(val) > 8 else val
                            conflicts.append(f"{key}={display_val}")
                    # 检查 env 块中的 ANTHROPIC_* 变量（CLI 会应用这些覆盖 API 地址）
                    env_block = data.get("env", {})
                    for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
                        val = env_block.get(key)
                        if val:
                            display_val = val[:20] + "..." if len(val) > 20 else val
                            conflicts.append(f"env.{key}={display_val}")
                    has_sdk_env = bool(self._build_sdk_env())
                    if conflicts:
                        overrides = []
                        if has_settings_override:
                            overrides.append("--settings inline JSON")
                        if has_sdk_env:
                            overrides.append("ClaudeAgentOptions.env")
                        if overrides:
                            detail = f"Has: {', '.join(conflicts)} -- overridden by {' + '.join(overrides)}"
                            fix = f"已通过 {' + '.join(overrides)} 覆盖，不影响 Agent"
                        else:
                            detail = f"Has: {', '.join(conflicts)} -- isolated by setting_sources"
                            fix = "已被 setting_sources 隔离，不影响 Agent。如仍怀疑干扰，临时重命名 ~/.claude/settings.json 验证"
                        _add("User settings.json", "WARN", detail, fix)
                        logger.warning(f"[ISOLATION] [WARN] User ~/.claude/settings.json has: {', '.join(conflicts)}")
                        if overrides:
                            logger.info(f"[ISOLATION]   INFO: 已通过 {' + '.join(overrides)} 覆盖，不影响 Agent")
                        else:
                            logger.warning("[ISOLATION]   FIX: 已被 setting_sources 隔离。如仍怀疑干扰，临时重命名 ~/.claude/settings.json 验证")
                    else:
                        _add("User settings.json", "OK", "No conflicting keys")
                        logger.info("[ISOLATION] [OK] User ~/.claude/settings.json: No conflicting keys")
                except Exception as e:
                    _add("User settings.json", "WARN", f"Read failed: {e}",
                         "无法读取用户 settings.json，可能不影响 Agent。如怀疑干扰，临时重命名 ~/.claude/settings.json 验证")
                    logger.warning(f"[ISOLATION] [WARN] User ~/.claude/settings.json: Read failed: {e}")
            else:
                _add("User settings.json", "OK", "Not found (no conflict)")
                logger.info("[ISOLATION] [OK] User ~/.claude/settings.json: Not found (no conflict)")

            # 5. 环境变量一致性
            env_issues = []
            env_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            env_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
            if settings.claude_auth_mode == "key":
                if env_api_key and settings.claude_api_key and env_api_key != settings.claude_api_key:
                    env_issues.append("ANTHROPIC_API_KEY differs from .env")
                if env_base_url and settings.claude_api_base and env_base_url != settings.claude_api_base:
                    env_issues.append(f"ANTHROPIC_BASE_URL={env_base_url} differs from .env ({settings.claude_api_base})")
            else:
                # OAuth 模式下不应存在这些变量
                if env_api_key:
                    env_issues.append("ANTHROPIC_API_KEY set in OAuth mode (should be empty)")
                if env_base_url:
                    env_issues.append(f"ANTHROPIC_BASE_URL={env_base_url} set in OAuth mode (should be empty)")
            if env_issues:
                _add("Environment variables", "WARN",
                     "; ".join(env_issues),
                     "检查是否有全局环境变量覆盖，清除系统级 ANTHROPIC_* 变量")
                logger.warning(f"[ISOLATION] [WARN] Environment variables: {'; '.join(env_issues)}")
                logger.warning("[ISOLATION]   FIX: 检查是否有全局环境变量覆盖，清除系统级 ANTHROPIC_* 变量")
            else:
                _add("Environment variables", "OK", f"Consistent with .env ({settings.claude_auth_mode} mode)")
                logger.info(f"[ISOLATION] [OK] Environment variables: Consistent with .env ({settings.claude_auth_mode} mode)")

            # 6. permissions deny 检查
            proj_settings_path = project_root / ".claude" / "settings.json"
            if proj_settings_path.exists():
                try:
                    data = json.loads(proj_settings_path.read_text(encoding="utf-8"))
                    deny_list = data.get("permissions", {}).get("deny", [])
                    if deny_list:
                        _add("Permissions deny", "OK", f"{len(deny_list)} deny rules configured")
                        logger.info(f"[ISOLATION] [OK] Permissions deny: {len(deny_list)} deny rules configured")
                    else:
                        _add("Permissions deny", "WARN", "deny list is empty",
                             "参照 .claude/settings.json.example 添加 deny 规则以屏蔽 .env/源码读取（开发阶段可忽略）")
                        logger.warning("[ISOLATION] [WARN] Project .claude/settings.json deny list is empty")
                        logger.warning("[ISOLATION]   FIX: 参照 .claude/settings.json.example 添加 deny 规则以屏蔽 .env/源码读取（开发阶段可忽略）")
                except Exception:
                    _add("Permissions deny", "WARN", "Unable to read settings.json")
                    logger.warning("[ISOLATION] [WARN] Unable to read project .claude/settings.json")
            else:
                _add("Permissions deny", "WARN", "Project .claude/settings.json not found",
                     "创建 .claude/settings.json 并配置 permissions")
                logger.warning("[ISOLATION] [WARN] Project .claude/settings.json not found")

            # 汇总
            errors = sum(1 for r in results if r["status"] == "ERROR")
            warnings = sum(1 for r in results if r["status"] == "WARN")
            logger.info(f"[ISOLATION] ====== Diagnosis Complete: {len(results)} checks, {errors} errors, {warnings} warnings ======")

        except Exception as e:
            logger.warning(f"[ISOLATION] Diagnosis failed: {e}")
            _add("Diagnosis", "ERROR", f"Failed: {e}")

        return results

    def _load_allowed_tools(self) -> List[str]:
        """加载允许的工具列表"""
        tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "WebSearch", "WebFetch"]

        # 文件输出 MCP 工具（始终注册，供 Agent 发送文件给用户）
        tools.append("mcp__file-output__return_file_to_user")

        # 任务委托工具（始终可用，由 Agent 自行判断何时使用）
        tools.append("mcp__task-mgr__delegate_task")
        tools.append("mcp__task-mgr__cancel_task")
        tools.append("mcp__task-mgr__query_task_status")

        # 定时任务管理工具
        tools.append("mcp__cron-mgr__cron_get_time")
        tools.append("mcp__cron-mgr__cron_create")
        tools.append("mcp__cron-mgr__cron_list")
        tools.append("mcp__cron-mgr__cron_delete")

        # 从配置文件加载额外工具
        tools_file = Path(settings.allowed_tools_file)
        if tools_file.exists():
            try:
                content = tools_file.read_text(encoding="utf-8")
                extra_tools = [t.strip() for t in content.split("\n") if t.strip()]
                tools.extend(extra_tools)
                logger.info(f"Loaded extra tools: {extra_tools}")
            except Exception as e:
                logger.error(f"Failed to load tools config: {e}")

        return tools

    def _build_mcp_servers(self, workspace: Path, delegation_context_getter=None) -> Dict:
        """
        构建 MCP 服务器配置

        Args:
            workspace: 会话工作目录
            delegation_context_getter: 可选，返回委托上下文的 callable（传入时注册 task-mgr 服务器）

        Returns:
            MCP servers 配置字典
        """
        # 从配置文件加载基础 MCP 配置
        mcp_servers = dict(self.mcp_config.get("mcpServers", {})) if self.mcp_config else {}

        # 添加文件输出 SDK MCP 服务器（进程内运行，始终注册）
        mcp_servers["file-output"] = create_file_output_server(workspace)
        logger.info(f"[MCP] Added SDK file-output server (workspace={workspace})")

        # 添加任务委托 SDK MCP 服务器（仅主会话使用，Worker 不需要）
        if delegation_context_getter:
            from app.mcp_tools.task_delegation_tool import create_task_delegation_server
            mcp_servers["task-mgr"] = create_task_delegation_server(delegation_context_getter)
            logger.info(f"[MCP] Added SDK task-mgr server (workspace={workspace})")

            # 添加定时任务管理 SDK MCP 服务器
            from app.mcp_tools.cron_tool import create_cron_server
            mcp_servers["cron-mgr"] = create_cron_server(delegation_context_getter)
            logger.info(f"[MCP] Added SDK cron-mgr server (workspace={workspace})")

        return mcp_servers

    def _resolve_skill_paths(self) -> str:
        """已废弃：SDK 的 Skill tool_result 已提供 Base directory，无需手动注入路径表"""
        return ""

    def _build_system_prompt(
        self,
        workspace_path: Optional[str] = None,
        conversation_id: Optional[str] = None,
        is_group: bool = False,
        user_id: Optional[str] = None,
        channel: str = "wecom",
    ) -> str:
        """
        构建系统提示（依赖 SDK 动态加载技能）

        Args:
            workspace_path: 用户工作目录路径（可选）
            conversation_id: 企微对话 ID（用于并发安全注入到 prompt）
            is_group: 是否群聊

        Returns:
            完整的系统提示
        """
        # 自动检测：soul 文件已创建但 prompt 仍含引导指令 → reload
        if "# 首次身份设置" in self.base_system_prompt and settings.resolved_soul_file.exists():
            logger.info("Soul file detected, reloading system prompt")
            self.base_system_prompt = load_system_prompt()
            self.collab_system_prompt = load_collab_system_prompt()

        # 根据运行模式选择基础 prompt
        is_collab = False
        if user_id:
            from app.core.avatar_mode import avatar_mode_manager
            is_collab = avatar_mode_manager.is_semi_auto(user_id)

        if is_collab:
            # 协作模式：使用独立的 collab prompt（完整文件，不追加模式标识）
            prompt = self.collab_system_prompt
        else:
            prompt = self.base_system_prompt

        # 如果提供了工作目录，添加到系统提示中
        if workspace_path:
            # 使用 os.path.join 构造示例路径，避免转义问题
            example_path = os.path.join(workspace_path, "report.xlsx")
            workspace_info = f"\n\n# 当前用户工作目录\n\n你的工作目录是：{workspace_path}\n\n所有生成的文件、下载的文件、中间产物都应该保存到这个目录下。使用 Write 工具创建文件时，请使用完整的绝对路径（例如：{example_path}）。"
            prompt = prompt + workspace_info

        # 新增：注入当前请求上下文（并发安全）
        # 每次 SDK 调用都有独立的 system_prompt，conversation_id 直接嵌入到字符串中
        # 不依赖共享的文件或环境变量，解决并发覆盖问题
        if conversation_id:
            context_type = "群聊" if is_group else "私聊"
            context_section = f"""

# 当前请求上下文

- 对话 ID: {conversation_id}
- 对话类型: {context_type}
"""
            prompt = prompt + context_section

        # 运行模式标识（仅托管模式追加，协作模式已内含在独立 prompt 中）
        if not is_collab:
            prompt += """

# 运行模式

当前模式：托管模式。你负责回复用户的所有消息。
"""

        # 渠道表情注入（按渠道注入对应表情集）
        emoticon_section = self.emoticon_prompts.get(channel, "")
        if emoticon_section:
            prompt += f"\n\n{emoticon_section}"

        # Windows 平台需要转义换行符
        # Claude CLI 在 Windows 上无法正确处理命令行参数中的实际换行符
        # 但会正确解释 \\n 为换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")

        return prompt

    async def download_files_to_workspace(
        self,
        parsed: ParsedQuery,
        workspace: Path,
        user_token: Optional[str] = None,
    ) -> List[Path]:
        """
        下载 COS 文件到工作目录

        Args:
            parsed: 解析后的查询（包含文件列表）
            workspace: 工作目录
            user_token: 用户鉴权 Token（COS 操作需要）

        Returns:
            下载成功的本地文件路径列表
        """
        if not user_token:
            logger.warning("No user_token provided, COS download may fail")

        downloaded = []
        for file_item in parsed.files:
            # 提取文件名
            cos_path = file_item.content
            filename = cos_path.split("/")[-1] if "/" in cos_path else cos_path
            local_path = workspace / filename

            # 下载（传入 user_token）
            success = await cos_client.download_file(cos_path, local_path, user_token or "")
            if success:
                downloaded.append(local_path)
                logger.info(f"Downloaded file: {cos_path} -> {local_path}")
            else:
                logger.warning(f"Failed to download: {cos_path}")

        return downloaded

    async def chat(
        self,
        session: Session,
        query_text: str,
        query_info: Optional[str] = None,
        skill_name: Optional[str] = None,
        user_token: Optional[str] = None,
        history_list: Optional[str] = None,
        parsed_query = None,  # 新增：可选的已解析对象
    ) -> AsyncGenerator[Any, None]:
        """
        发送对话请求（流式响应）

        Args:
            session: 会话对象
            query_text: 用户查询（query 字段）
            query_info: 问句详情 JSON（企微格式）
            skill_name: 技能名称
            user_token: 用户鉴权 Token（COS 操作需要）
            history_list: 对话历史 JSON（企微格式）
            parsed_query: 可选的已解析对象（如果提供，跳过解析步骤）

        Yields:
            SDK 消息流
        """
        # 调试日志
        logger.info(f"[DEBUG] chat() called with query_text='{query_text[:100] if query_text else 'EMPTY'}', query_info type={type(query_info)}")

        # 如果提供了已解析的对象，直接使用；否则解析 query_info
        if parsed_query is not None:
            parsed = parsed_query
            logger.info(f"[DEBUG] Using pre-parsed query object, files={len(parsed.files)}")
        else:
            # 解析 query_info（传入 history_list）
            parsed = parse_query_info(query_text, query_info, history_list)
            logger.info(f"[DEBUG] parsed.text='{parsed.text[:100] if parsed.text else 'EMPTY'}', files={len(parsed.files)}")

        logger.info(f"[FILE] Parsed files: {len(parsed.files)}, user_token: {'✓ present' if user_token else '✗ MISSING'}")

        # 下载文件到工作目录（传入 user_token）
        # 注意：如果使用 parsed_query，调用方应该已经下载过文件了
        if parsed.files and parsed_query is None:
            if not user_token:
                logger.error(f"[FILE] Cannot download {len(parsed.files)} files without user_token!")
            logger.info(f"[FILE] Starting download for {len(parsed.files)} files to {session.workspace}...")
            downloaded = await self.download_files_to_workspace(parsed, session.workspace, user_token)
            logger.info(f"[FILE] Downloaded {len(downloaded)}/{len(parsed.files)} files successfully")

        # 构建提示 - 极简版本：只有文件路径和用户问题
        prompt = parsed.text

        # 如果有文件，直接把路径拼到用户问题前面
        if parsed.files:
            workspace_path = Path(session.workspace)
            file_paths = []

            for f in parsed.files:
                # 判断是本地路径还是 COS 路径
                if Path(f.content).is_absolute():
                    local_path = Path(f.content)
                else:
                    filename = f.content.split("/")[-1] if "/" in f.content else f.content
                    local_path = workspace_path / filename

                file_paths.append(str(local_path))

            # 只拼路径，没有任何额外的标签或说明
            if len(file_paths) == 1:
                prompt = f"{file_paths[0]}\n{parsed.text}"
            else:
                files_str = "\n".join(file_paths)
                prompt = f"{files_str}\n{parsed.text}"

            logger.info(f"[FILE] Prepended {len(file_paths)} file path(s) to user query")

        # Windows 平台需要转义换行符（与 _build_system_prompt 保持一致）
        # Claude CLI 在 Windows 上无法正确处理命令行参数中的实际换行符
        # 但会正确解释 \\n 为换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")
            logger.debug(f"[chat] Applied Windows newline escaping to prompt")

        # 构建 system prompt（技能由 SDK 动态加载，包含用户工作目录）
        system_prompt = self._build_system_prompt(str(session.workspace))

        # 设置环境变量，供 cron_cli.py 等脚本读取当前用户的 workspace
        # 解决并发场景下项目根目录上下文文件被覆盖的问题
        os.environ["CLAUDE_USER_WORKSPACE"] = str(session.workspace)

        # 构建选项参数
        sdk_env = self._build_sdk_env()
        options_kwargs = {
            "model": self.model,
            "system_prompt": system_prompt,
            "allowed_tools": self.allowed_tools,
            "permission_mode": "bypassPermissions",
            "cwd": config.resolved_agent_root,
            "setting_sources": ["project", "local"],
            "max_buffer_size": 50 * 1024 * 1024,  # 50MB，支持大文件处理
            "stderr": _log_stderr,  # 捕获 CLI stderr 输出（包含 "Prompt is too long" 等警告）
        }
        if sdk_env:
            options_kwargs["env"] = sdk_env

        # --settings 内联覆盖（防止用户 ~/.claude/settings.json 干扰 apiUrl/model）
        settings_override = self._build_settings_override()
        if settings_override:
            options_kwargs["settings"] = settings_override

        # CLI 路径自动检测
        resolved_cli = settings.resolve_cli_path()
        if resolved_cli:
            options_kwargs["cli_path"] = resolved_cli

        options = ClaudeAgentOptions(**options_kwargs)

        # 安全钩子：黑名单拦截敏感路径和危险命令
        options.hooks = build_security_hooks()

        # MCP 配置（包含 file-output 工具）
        options.mcp_servers = self._build_mcp_servers(Path(session.workspace))

        # 如果有之前的 Claude session_id，使用 resume
        if session.claude_session_id:
            options.resume = session.claude_session_id
            logger.debug(f"Resuming session: {session.claude_session_id}")

        logger.info(
            f"Starting query for user {session.user_id}, "
            f"skill: {skill_name}, workspace: {session.workspace}"
        )
        logger.info(f"SDK setting_sources: {options_kwargs.get('setting_sources')}, cwd: {options_kwargs.get('cwd')}")
        logger.info(f"SDK allowed_tools: {self.allowed_tools}")
        logger.info(f"[DEBUG] Final prompt to SDK (length={len(prompt)}): '{prompt[:200] if prompt else 'EMPTY'}...'")

        # 调试日志
        logger.info(f"SDK Options: model={self.model}, cli_path={resolved_cli or 'bundled'}")
        logger.info(f"ENV: ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', 'NOT SET')[:10]}...")
        logger.info(f"ENV: ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', 'NOT SET')}")

        # 调试：打印 prompt 类型和内容
        logger.info(f"[DEBUG] prompt type: {type(prompt)}, is string: {isinstance(prompt, str)}")
        logger.info(f"[DEBUG] prompt repr (first 100): {repr(prompt[:100]) if prompt else 'EMPTY'}")

        # 额外调试：尝试打印完整的 file_context（如果有文件）
        if parsed.files:
            logger.info(f"[DEBUG] prompt contains {len(parsed.files)} files")
            logger.info(f"[DEBUG] prompt length: {len(prompt)}")
            # 写入文件以避免编码问题
            debug_file = Path(session.workspace) / "_debug_prompt.txt"
            try:
                debug_file.write_text(prompt, encoding="utf-8")
                logger.info(f"[DEBUG] Wrote prompt to {debug_file} for inspection")

                # 新增：验证 Python 中的 prompt 是否正确
                if "用户上传了以下文件" in prompt:
                    logger.info(f"[DEBUG] ✓ Prompt contains Chinese text correctly in Python")
                    # 提取第一行文件信息
                    lines = prompt.split("\n")
                    for line in lines[:10]:
                        if "绝对路径" in line or "png" in line.lower():
                            logger.info(f"[DEBUG] File line: {line[:100]}")
                else:
                    logger.error(f"[DEBUG] ✗ Prompt does NOT contain expected Chinese text!")
            except Exception as e:
                logger.error(f"[DEBUG] Failed to write debug file: {e}")

        try:
            msg_count = 0
            async for message in query(prompt=prompt, options=options):
                msg_count += 1

                # ========== SDK 处理过程日志 ==========
                msg_type = type(message).__name__
                logger.info(f"[SDK] #{msg_count} Message type: {msg_type}")

                # 打印文本内容
                if hasattr(message, "content") and message.content:
                    content_preview = str(message.content)[:200]
                    logger.info(f"[SDK] #{msg_count} Content: {content_preview}...")

                # 打印工具调用信息
                if hasattr(message, "tool_use"):
                    tool = message.tool_use
                    tool_name = getattr(tool, "name", "unknown")
                    tool_input = getattr(tool, "input", {})
                    input_preview = str(tool_input)[:300] if tool_input else "{}"
                    logger.info(f"[SDK] #{msg_count} Tool call: {tool_name}")
                    logger.info(f"[SDK] #{msg_count} Tool input: {input_preview}")

                # 打印工具结果
                if hasattr(message, "tool_result"):
                    result = message.tool_result
                    result_preview = str(result)[:300] if result else "None"
                    logger.info(f"[SDK] #{msg_count} Tool result: {result_preview}...")

                # 打印 Skill 调用信息
                if msg_type == "ToolUseMessage" and hasattr(message, "tool_use"):
                    tool_name = getattr(message.tool_use, "name", "")
                    if tool_name == "Skill":
                        skill_input = getattr(message.tool_use, "input", {})
                        logger.info(f"[SDK] #{msg_count} >>> SKILL INVOKED: {skill_input}")

                # 更新 Claude session_id（以 user_id 为主键）
                if hasattr(message, "session_id") and message.session_id:
                    if session.claude_session_id != message.session_id:
                        await session_manager.update_claude_session(
                            session.user_id, message.session_id
                        )
                        session.claude_session_id = message.session_id

                yield message

            logger.info(f"[SDK] Total messages: {msg_count}")

        except Exception as e:
            logger.error(f"Error in chat: {e}")
            raise

    async def chat_with_files(
        self,
        session: Session,
        user_text: str,
        processed_files: List[ProcessedFile],
        conversation_id: Optional[str] = None,
        is_group: bool = False,
    ) -> AsyncGenerator[Any, None]:
        """
        使用新的文件处理架构发送对话请求

        核心改进：
        - 图片：使用 multimodal message (base64 直接传递给 SDK)
        - 文档：提示 Claude 使用 Read 工具

        Args:
            session: 会话对象
            user_text: 用户文本
            processed_files: 处理后的文件列表
            conversation_id: 企微对话 ID（用于并发安全传递给脚本）
            is_group: 是否群聊（用于并发安全传递给脚本）

        Yields:
            SDK 消息流
        """
        workspace_path = str(session.workspace)

        # 处理用户文本中的换行符（换行符会导致 SDK 截断消息）
        if user_text:
            user_text = user_text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            logger.debug(f"[chat_with_files] Normalized user_text (removed newlines)")

        # 检查是否有图片
        has_images = MessageBuilder.has_images(processed_files)

        logger.info(
            f"[chat_with_files] user={session.user_id}, "
            f"text='{user_text[:50] if user_text else 'EMPTY'}...', "
            f"files={len(processed_files)}, has_images={has_images}"
        )

        # 构建 system prompt（包含用户工作目录和请求上下文）
        # conversation_id 和 is_group 直接注入到 prompt 中，解决并发覆盖问题
        system_prompt = self._build_system_prompt(
            workspace_path=workspace_path,
            conversation_id=conversation_id,
            is_group=is_group,
        )

        # 构建选项参数
        sdk_env = self._build_sdk_env()
        options_kwargs = {
            "model": self.model,
            "system_prompt": system_prompt,
            "allowed_tools": self.allowed_tools,
            "permission_mode": "bypassPermissions",
            "cwd": config.resolved_agent_root,
            "setting_sources": ["project", "local"],
            "max_buffer_size": 50 * 1024 * 1024,  # 50MB，支持大文件处理
            "stderr": _log_stderr,  # 捕获 CLI stderr 输出（包含 "Prompt is too long" 等警告）
        }
        if sdk_env:
            options_kwargs["env"] = sdk_env

        # --settings 内联覆盖（防止用户 ~/.claude/settings.json 干扰 apiUrl/model）
        settings_override = self._build_settings_override()
        if settings_override:
            options_kwargs["settings"] = settings_override

        resolved_cli = settings.resolve_cli_path()
        if resolved_cli:
            options_kwargs["cli_path"] = resolved_cli

        options = ClaudeAgentOptions(**options_kwargs)

        # 安全钩子：黑名单拦截敏感路径和危险命令
        options.hooks = build_security_hooks()

        # MCP 配置（包含 file-output 工具）
        options.mcp_servers = self._build_mcp_servers(Path(session.workspace))

        # 如果有之前的 Claude session_id，使用 resume
        if session.claude_session_id:
            options.resume = session.claude_session_id
            logger.info(f"[chat_with_files] RESUMING session: {session.claude_session_id}")
        else:
            logger.info(f"[chat_with_files] NEW session")

        # ======== 设置环境变量，供 cron_cli.py 等脚本读取 ========
        # 解决并发场景下上下文文件被覆盖的问题
        # 环境变量的设置和 SDK 调用在同一个同步代码块中，不会被并发覆盖
        os.environ["CLAUDE_USER_WORKSPACE"] = str(session.workspace)
        if conversation_id:
            os.environ["CLAUDE_CONVERSATION_ID"] = conversation_id
        else:
            os.environ.pop("CLAUDE_CONVERSATION_ID", None)  # 清除旧值
        os.environ["CLAUDE_IS_GROUP"] = "true" if is_group else "false"
        logger.info(f"[chat_with_files] Set env: CLAUDE_CONVERSATION_ID={conversation_id}, CLAUDE_IS_GROUP={is_group}")

        # 统一路径方式：所有文件（包括图片）都用路径传递，由 Claude 用 Read 工具读取
        if has_images:
            file_paths = [str(f.local_path) for f in processed_files]
            if len(file_paths) == 1:
                prompt = f"{file_paths[0]}\n{user_text}" if user_text else file_paths[0]
            else:
                files_str = "\n".join(file_paths)
                prompt = f"{files_str}\n{user_text}" if user_text else files_str
            logger.info(f"[chat_with_files] Using image paths prompt with {len(file_paths)} files")
        else:
            prompt = MessageBuilder.build_text_only_prompt(
                user_text, processed_files, workspace_path
            )
            logger.info(f"[chat_with_files] Using text-only prompt (length={len(prompt)})")

        # Windows 平台需要转义换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")
            logger.debug(f"[chat_with_files] Applied Windows newline escaping")

        # 调试日志
        logger.info(f"[chat_with_files] SDK Options: model={self.model}")
        logger.info(f"[chat_with_files] FULL PROMPT length={len(prompt)}")
        logger.info(f"[chat_with_files] PROMPT START (800 chars): {prompt[:800]}")
        logger.info(f"[chat_with_files] PROMPT END (200 chars): ...{prompt[-200:] if len(prompt) > 200 else prompt}")
        logger.info(f"[chat_with_files] RESUME MODE: {'YES - ' + str(options.resume) if options.resume else 'NO - new session'}")
        logger.info(f"[chat_with_files] ENV: ANTHROPIC_API_KEY={os.environ.get('ANTHROPIC_API_KEY', 'NOT SET')[:10]}...")
        logger.info(f"[chat_with_files] ENV: ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', 'NOT SET')}")

        try:
            msg_count = 0
            async for message in query(prompt=prompt, options=options):
                msg_count += 1

                # ========== SDK 处理过程日志 ==========
                msg_type = type(message).__name__
                logger.info(f"[SDK] #{msg_count} Message type: {msg_type}")

                # 打印文本内容（AssistantMessage）
                if hasattr(message, "content") and message.content:
                    content_preview = str(message.content)[:200]
                    logger.info(f"[SDK] #{msg_count} Content: {content_preview}...")

                # 打印工具调用信息（ToolUseMessage）
                if hasattr(message, "tool_use"):
                    tool = message.tool_use
                    tool_name = getattr(tool, "name", "unknown")
                    tool_input = getattr(tool, "input", {})
                    # 对于长输入，只打印前 200 字符
                    input_preview = str(tool_input)[:300] if tool_input else "{}"
                    logger.info(f"[SDK] #{msg_count} Tool call: {tool_name}")
                    logger.info(f"[SDK] #{msg_count} Tool input: {input_preview}")

                # 打印工具结果（ToolResultMessage）
                if hasattr(message, "tool_result"):
                    result = message.tool_result
                    result_preview = str(result)[:300] if result else "None"
                    logger.info(f"[SDK] #{msg_count} Tool result: {result_preview}...")

                # 打印 Skill 调用信息
                if msg_type == "ToolUseMessage" and hasattr(message, "tool_use"):
                    tool_name = getattr(message.tool_use, "name", "")
                    if tool_name == "Skill":
                        skill_input = getattr(message.tool_use, "input", {})
                        logger.info(f"[SDK] #{msg_count} >>> SKILL INVOKED: {skill_input}")

                # 更新 Claude session_id
                if hasattr(message, "session_id") and message.session_id:
                    if session.claude_session_id != message.session_id:
                        await session_manager.update_claude_session(
                            session.user_id, message.session_id
                        )
                        session.claude_session_id = message.session_id

                yield message

            logger.info(f"[SDK] Total messages: {msg_count}")

        except Exception as e:
            import traceback
            logger.error(f"Error in chat_with_files: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise

    async def chat_with_files_stream(
        self,
        session: Session,
        user_text: str,
        processed_files: List[ProcessedFile],
        conversation_id: Optional[str] = None,
        is_group: bool = False,
    ) -> AsyncGenerator[str, None]:
        """
        使用新的文件处理架构发送对话请求（SSE 流式响应）
        """
        sse_handler = SSEHandler()
        sdk_stream = self.chat_with_files(
            session, user_text, processed_files,
            conversation_id=conversation_id, is_group=is_group
        )
        async for event in sse_handler.convert_stream(sdk_stream):
            yield event

    async def chat_with_files_blocking(
        self,
        session: Session,
        user_text: str,
        processed_files: List[ProcessedFile],
        conversation_id: Optional[str] = None,
        is_group: bool = False,
    ) -> Dict[str, Any]:
        """
        使用新的文件处理架构发送对话请求（阻塞式响应）
        """
        messages = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        async for message in self.chat_with_files(
            session, user_text, processed_files,
            conversation_id=conversation_id, is_group=is_group
        ):
            messages.append(message)

            if hasattr(message, "message"):
                msg_usage = getattr(message.message, "usage", None)
                if msg_usage:
                    usage["input_tokens"] += getattr(msg_usage, "input_tokens", 0)
                    usage["output_tokens"] += getattr(msg_usage, "output_tokens", 0)

        return format_blocking_response(messages, usage)

    async def chat_with_files_blocking_with_progress(
        self,
        session: Session,
        user_text: str,
        processed_files: List[ProcessedFile],
        pusher: Optional[Any] = None,
        conversation_id: Optional[str] = None,
        is_group: bool = False,
    ) -> Dict[str, Any]:
        """
        使用新的文件处理架构发送对话请求（阻塞式响应 + 进度推送）

        与 chat_with_files_blocking 的区别：
        - 在处理过程中将 AssistantMessage 传递给 ProgressPusher
        - 支持按间隔推送处理进度

        Args:
            session: 会话对象
            user_text: 用户文本
            processed_files: 处理后的文件列表
            pusher: 进度推送器（可选）
            conversation_id: 企微对话 ID（用于并发安全传递给脚本）
            is_group: 是否群聊（用于并发安全传递给脚本）

        Returns:
            SDK 响应结果
        """
        messages = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        async for message in self.chat_with_files(
            session, user_text, processed_files,
            conversation_id=conversation_id, is_group=is_group
        ):
            messages.append(message)

            # 将 AssistantMessage 传递给 pusher
            msg_type = type(message).__name__
            if pusher and msg_type == "AssistantMessage":
                await pusher.add_message(message)
                logger.debug(f"[PROGRESS] Added AssistantMessage to pusher")

            if hasattr(message, "message"):
                msg_usage = getattr(message.message, "usage", None)
                if msg_usage:
                    usage["input_tokens"] += getattr(msg_usage, "input_tokens", 0)
                    usage["output_tokens"] += getattr(msg_usage, "output_tokens", 0)

        # pusher 存在时使用 only_last_text=True，只返回最后一个 TextBlock
        # 避免与已推送的进度消息重复
        return format_blocking_response(messages, usage, only_last_text=(pusher is not None))

    async def chat_with_sdk_client(
        self,
        session: Session,
        user_text: str,
        processed_files: List[ProcessedFile],
        sdk_client: Any,
        pusher: Optional[Any] = None,
        conversation_id: Optional[str] = None,
        is_group: bool = False,
    ) -> Dict[str, Any]:
        """
        v2.7 新增：使用已有的 SDK 客户端发送对话请求

        与 chat_with_files_blocking_with_progress 的区别：
        - 使用传入的 sdk_client 长连接（保持多轮对话上下文）
        - 不创建新的 SDK 连接

        Args:
            session: 会话对象
            user_text: 用户文本
            processed_files: 处理后的文件列表
            sdk_client: ClaudeSDKClient 实例（长连接）
            pusher: 进度推送器（可选）
            conversation_id: 企微对话 ID
            is_group: 是否群聊

        Returns:
            SDK 响应结果
        """
        workspace_path = str(session.workspace)

        # 处理用户文本中的换行符
        if user_text:
            user_text = user_text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

        # 检查是否有图片
        has_images = MessageBuilder.has_images(processed_files)

        logger.info(
            f"[chat_with_sdk_client] user={session.user_id}, "
            f"text='{user_text[:50] if user_text else 'EMPTY'}...', "
            f"files={len(processed_files)}, has_images={has_images}"
        )

        # 设置环境变量
        os.environ["CLAUDE_USER_WORKSPACE"] = str(session.workspace)
        if conversation_id:
            os.environ["CLAUDE_CONVERSATION_ID"] = conversation_id
        else:
            os.environ.pop("CLAUDE_CONVERSATION_ID", None)
        os.environ["CLAUDE_IS_GROUP"] = "true" if is_group else "false"

        # 构建 prompt
        if has_images:
            file_paths = [str(f.local_path) for f in processed_files]
            if len(file_paths) == 1:
                prompt = f"{file_paths[0]}\n{user_text}" if user_text else file_paths[0]
            else:
                files_str = "\n".join(file_paths)
                prompt = f"{files_str}\n{user_text}" if user_text else files_str
        else:
            prompt = MessageBuilder.build_text_only_prompt(
                user_text, processed_files, workspace_path
            )

        # Windows 平台需要转义换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")

        logger.info(f"[chat_with_sdk_client] PROMPT length={len(prompt)}")
        logger.info(f"[chat_with_sdk_client] PROMPT START (500 chars): {prompt[:500]}")

        messages = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        try:
            # 使用已有的长连接发送查询
            await sdk_client.query(prompt)

            # 接收响应
            async for message in sdk_client.receive_response():
                messages.append(message)

                # 打印调试信息
                msg_type = type(message).__name__
                logger.info(f"[SDK] Message type: {msg_type}")

                if hasattr(message, "content") and message.content:
                    content_preview = str(message.content)[:200]
                    logger.info(f"[SDK] Content: {content_preview}...")

                # 将 AssistantMessage 传递给 pusher
                if pusher and msg_type == "AssistantMessage":
                    await pusher.add_message(message)
                    logger.debug(f"[PROGRESS] Added AssistantMessage to pusher")

                # 更新 Claude session_id
                if hasattr(message, "session_id") and message.session_id:
                    if session.claude_session_id != message.session_id:
                        await session_manager.update_claude_session(
                            session.user_id, message.session_id
                        )
                        session.claude_session_id = message.session_id

                if hasattr(message, "message"):
                    msg_usage = getattr(message.message, "usage", None)
                    if msg_usage:
                        usage["input_tokens"] += getattr(msg_usage, "input_tokens", 0)
                        usage["output_tokens"] += getattr(msg_usage, "output_tokens", 0)

            logger.info(f"[SDK] Total messages: {len(messages)}")

        except Exception as e:
            import traceback
            logger.error(f"Error in chat_with_sdk_client: {e}")
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise

        return format_blocking_response(messages, usage, only_last_text=(pusher is not None))

    async def chat_stream(
        self,
        session: Session,
        query_text: str,
        query_info: Optional[str] = None,
        skill_name: Optional[str] = None,
        user_token: Optional[str] = None,
        history_list: Optional[str] = None,
        parsed_query = None,  # 新增：可选的已解析对象
    ) -> AsyncGenerator[str, None]:
        """
        发送对话请求（SSE 流式响应）
        """
        sse_handler = SSEHandler()
        sdk_stream = self.chat(session, query_text, query_info, skill_name, user_token, history_list, parsed_query)
        async for event in sse_handler.convert_stream(sdk_stream):
            yield event

    async def chat_blocking(
        self,
        session: Session,
        query_text: str,
        query_info: Optional[str] = None,
        skill_name: Optional[str] = None,
        user_token: Optional[str] = None,
        history_list: Optional[str] = None,
        parsed_query = None,  # 新增：可选的已解析对象
    ) -> Dict[str, Any]:
        """
        发送对话请求（阻塞式响应）
        """
        messages = []
        usage = {"input_tokens": 0, "output_tokens": 0}

        async for message in self.chat(session, query_text, query_info, skill_name, user_token, history_list, parsed_query):
            # 调试：打印消息类型和属性
            logger.info(f"Received message type: {type(message).__name__}")
            logger.info(f"Message attributes: {dir(message)}")
            logger.info(f"Message repr: {repr(message)[:500]}")
            messages.append(message)

            if hasattr(message, "message"):
                msg_usage = getattr(message.message, "usage", None)
                if msg_usage:
                    usage["input_tokens"] += getattr(msg_usage, "input_tokens", 0)
                    usage["output_tokens"] += getattr(msg_usage, "output_tokens", 0)

        logger.info(f"Total messages received: {len(messages)}")
        return format_blocking_response(messages, usage)

    def reload_config(self) -> List[Dict]:
        """重新加载配置，返回隔离诊断结果"""
        self.base_system_prompt = load_system_prompt()
        self.collab_system_prompt = load_collab_system_prompt()
        self.worker_system_prompt = load_worker_system_prompt()
        self.mcp_config = load_mcp_config()
        self.allowed_tools = self._load_allowed_tools()
        self.emoticon_prompts = {}
        for ch in ("wecom", "feishu"):
            content = load_prompt_part(f"emoticons_{ch}.md")
            if content:
                self.emoticon_prompts[ch] = content
        self._write_settings_overrides()
        diagnostics = self.diagnose_isolation()
        logger.info("Agent service config reloaded")
        return diagnostics


# 全局 Agent 服务实例
agent_service = ClaudeAgentService()
