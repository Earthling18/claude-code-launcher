"""
Claude Agent 服务
封装 Claude Agent SDK，提供对话功能
"""
import asyncio
import json
import os
import platform
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
import logging

from claude_agent_sdk import query, ClaudeAgentOptions
import claude_agent_sdk
print(f"[IMPORT DEBUG] claude_agent_sdk location: {claude_agent_sdk.__file__}")

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
        logger.debug(f"[CLI STDERR] {line}")


def load_soul() -> str:
    """加载身份人格文件，不存在则使用默认值"""
    soul_file = Path(settings.soul_file)
    if soul_file.exists():
        logger.info(f"Loading soul from: {soul_file}")
        return soul_file.read_text(encoding="utf-8")
    return "你是一个智能工作助手，运行在企业微信环境中。"


def load_system_prompt() -> str:
    """
    加载系统提示，自动注入 soul.md 到 {soul} 占位符
    优先从 system_prompt.md 文件加载，否则使用默认值
    """
    soul_content = load_soul()

    prompt_file = Path(settings.system_prompt_file)
    if prompt_file.exists():
        logger.info(f"Loading system prompt from: {prompt_file}")
        content = prompt_file.read_text(encoding="utf-8")
        if "{soul}" in content:
            content = content.replace("{soul}", soul_content)
        return content

    # 默认系统提示
    return f"""{soul_content}

**工作原则：**
- 准确理解用户意图
- 高效完成任务
- 清晰汇报执行结果
- 遇到问题及时反馈
"""


def load_mcp_config() -> Optional[Dict]:
    """
    加载 MCP 配置
    从 .mcp.json 文件加载 MCP servers 配置
    """
    mcp_file = Path(settings.mcp_config_file)
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
        logger.info(f"[CONFIG] mode={settings.claude_auth_mode}, model={settings.claude_model}, base_url={settings.claude_api_base or 'EMPTY'}, api_key={'SET' if settings.claude_api_key else 'EMPTY'}")

        # Proxy env for CLI subprocess only (NOT os.environ — that would affect sendMsg/COS)
        self._cli_proxy_env: dict[str, str] = {}

        # 根据认证模式设置环境变量
        if settings.claude_auth_mode == "oauth":
            # OAuth 模式：使用 Claude Code 登录凭证
            os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("ANTHROPIC_BASE_URL", None)

            # 代理只传给 CLI 子进程（通过 options.env），不污染 agent server
            if settings.http_proxy:
                self._cli_proxy_env = {
                    "HTTP_PROXY": settings.http_proxy,
                    "HTTPS_PROXY": settings.http_proxy,
                }
                logger.info(f"[AUTH] OAuth mode, CLI proxy={settings.http_proxy}")
            else:
                logger.info("[AUTH] OAuth mode, no proxy")
        else:
            # 代理模式：使用内部代理网关，不需要代理
            if settings.claude_api_key:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = settings.claude_api_key
                os.environ["ANTHROPIC_API_KEY"] = settings.claude_api_key
            if settings.claude_api_base:
                os.environ["ANTHROPIC_BASE_URL"] = settings.claude_api_base
            logger.info(f"[AUTH] proxy mode: ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', 'NOT SET')}, API_KEY={'SET' if os.environ.get('ANTHROPIC_API_KEY') else 'NOT SET'}")

        self.model = settings.claude_model or "claude-sonnet-4-5-20250929"
        self.base_system_prompt = load_system_prompt()
        self.mcp_config = load_mcp_config()

        # 基础工具列表（用户可通过配置扩展）
        self.allowed_tools = self._load_allowed_tools()

    def _load_allowed_tools(self) -> List[str]:
        """加载允许的工具列表"""
        tools = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Skill", "WebSearch", "WebFetch"]

        # MCP 工具需要显式添加（格式：mcp__<服务器名>__<工具名>）
        # 注意：prompt 模式不需要 MCP 工具，使用格式约定替代
        if settings.file_output_mode == "mcp":
            tools.append("mcp__file-output__return_file_to_user")

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

    def _build_mcp_servers(self, workspace: Path) -> Dict:
        """
        构建 MCP 服务器配置

        Args:
            workspace: 会话工作目录

        Returns:
            MCP servers 配置字典
        """
        # 从配置文件加载基础 MCP 配置
        mcp_servers = dict(self.mcp_config.get("mcpServers", {})) if self.mcp_config else {}

        # 添加文件输出 SDK MCP 服务器（进程内运行）
        if settings.file_output_mode == "mcp":
            mcp_servers["file-output"] = create_file_output_server(workspace)
            logger.info(f"[MCP] Added SDK file-output server (workspace={workspace})")

        return mcp_servers

    def _build_system_prompt(
        self,
        workspace_path: Optional[str] = None,
        conversation_id: Optional[str] = None,
        is_group: bool = False,
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

创建定时任务时，请使用上述对话 ID 作为 --context-conversation-id 参数的值。
"""
            prompt = prompt + context_section

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
        logger.debug(f"[DEBUG] chat() called with query_text='{query_text[:100] if query_text else 'EMPTY'}', query_info type={type(query_info)}")

        # 如果提供了已解析的对象，直接使用；否则解析 query_info
        if parsed_query is not None:
            parsed = parsed_query
            logger.debug(f"Using pre-parsed query object, files={len(parsed.files)}")
        else:
            # 解析 query_info（传入 history_list）
            parsed = parse_query_info(query_text, query_info, history_list)
            logger.debug(f"parsed.text='{parsed.text[:100] if parsed.text else 'EMPTY'}', files={len(parsed.files)}")

        logger.debug(f"[FILE] Parsed files: {len(parsed.files)}, user_token: {'✓ present' if user_token else '✗ MISSING'}")

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
        # 设置 cwd 指向项目根目录，SDK 将从 .claude/skills/ 加载技能
        project_root = Path.cwd().resolve()
        options_kwargs = {
            "model": self.model,
            "max_turns": settings.agent_max_turns,  # Launcher UI 可通过 WECOM_AGENT_MAX_TURNS 覆盖
            "system_prompt": system_prompt,
            "allowed_tools": self.allowed_tools,
            "cwd": str(project_root),  # SDK 动态加载技能需要
            "setting_sources": ["user", "project"],  # 启用官方 SDK Skill 动态加载
            "max_buffer_size": 50 * 1024 * 1024,  # 50MB，支持大文件处理
            "stderr": _log_stderr,  # 捕获 CLI stderr 输出（包含 "Prompt is too long" 等警告）
        }

        # 如果配置了 CLI 路径，添加到选项中
        if settings.claude_cli_path:
            options_kwargs["cli_path"] = settings.claude_cli_path
            logger.info(f"Using CLI path: {settings.claude_cli_path}")

        # Pass proxy env to CLI subprocess only (OAuth mode)
        if self._cli_proxy_env:
            options_kwargs["env"] = self._cli_proxy_env

        options = ClaudeAgentOptions(**options_kwargs)

        # 安全钩子：黑名单拦截敏感路径和危险命令
        options.hooks = build_security_hooks()

        # MCP 配置（包含 file-output 工具）
        options.mcp_servers = self._build_mcp_servers(Path(session.workspace))

        # 如果有之前的 Claude session_id，使用 resume
        if session.claude_session_id:
            options.resume = session.claude_session_id
            logger.debug(f"Resuming session: {session.claude_session_id}")

        logger.info(f"[QUERY] user={session.user_id}, model={self.model}, max_turns={settings.agent_max_turns}, prompt_len={len(prompt)}")
        logger.debug(f"[QUERY] allowed_tools={self.allowed_tools}")
        logger.debug(f"[QUERY] ENV: ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', 'NOT SET')}")

        try:
            msg_count = 0
            async for message in query(prompt=prompt, options=options):
                msg_count += 1
                msg_type = type(message).__name__

                # Compact SDK logs: one line per message
                if hasattr(message, "tool_use") and message.tool_use:
                    tool_name = getattr(message.tool_use, "name", "unknown")
                    logger.info(f"[SDK] #{msg_count} Tool: {tool_name}")
                elif hasattr(message, "content") and message.content:
                    content_preview = str(message.content)[:100]
                    logger.info(f"[SDK] #{msg_count} {msg_type}: {content_preview}...")
                else:
                    logger.debug(f"[SDK] #{msg_count} {msg_type}")

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
            # If resume failed, clear stale session_id and retry fresh
            if session.claude_session_id:
                logger.warning(f"[SDK] Resume failed, clearing stale session_id and retrying fresh: {e}")
                session.claude_session_id = None
                await session_manager.update_claude_session(session.user_id, None)
                options.resume = None
                try:
                    msg_count = 0
                    async for message in query(prompt=prompt, options=options):
                        msg_count += 1
                        if hasattr(message, "session_id") and message.session_id:
                            if session.claude_session_id != message.session_id:
                                await session_manager.update_claude_session(
                                    session.user_id, message.session_id
                                )
                                session.claude_session_id = message.session_id
                        yield message
                    logger.info(f"[SDK] Retry succeeded, total messages: {msg_count}")
                    return
                except Exception as e2:
                    logger.error(f"[SDK] Fresh retry also failed: {e2}")
                    raise e2
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

        logger.debug(
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
        project_root = Path.cwd().resolve()
        options_kwargs = {
            "model": self.model,
            "max_turns": settings.agent_max_turns,  # Launcher UI 可通过 WECOM_AGENT_MAX_TURNS 覆盖
            "system_prompt": system_prompt,
            "allowed_tools": self.allowed_tools,
            "cwd": str(project_root),
            "setting_sources": ["user", "project"],
            "max_buffer_size": 50 * 1024 * 1024,  # 50MB，支持大文件处理
            "stderr": _log_stderr,  # 捕获 CLI stderr 输出（包含 "Prompt is too long" 等警告）
        }

        if settings.claude_cli_path:
            options_kwargs["cli_path"] = settings.claude_cli_path

        # Pass proxy env to CLI subprocess only (OAuth mode)
        if self._cli_proxy_env:
            options_kwargs["env"] = self._cli_proxy_env

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
        logger.info(f"[chat_with_files] max_turns: {settings.agent_max_turns}")

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

        # 暂时禁用 multimodal content，统一使用纯文本格式
        # 原因：Claude Agent SDK 的 query() 可能不支持 List[dict] 作为 prompt
        # 所有文件（包括图片）都使用路径方式传递，让 Claude 用 Read 工具读取

        if has_images:
            # 有图片时，使用图片路径 + 文本格式
            file_paths = [str(f.local_path) for f in processed_files]
            if len(file_paths) == 1:
                prompt = f"{file_paths[0]}\n{user_text}" if user_text else file_paths[0]
            else:
                files_str = "\n".join(file_paths)
                prompt = f"{files_str}\n{user_text}" if user_text else files_str
            logger.debug(f"[chat_with_files] Using image paths prompt with {len(file_paths)} files")
        else:
            # 无图片时，使用简单文本格式
            prompt = MessageBuilder.build_text_only_prompt(
                user_text, processed_files, workspace_path
            )
            logger.debug(f"[chat_with_files] Using text-only prompt (length={len(prompt)})")

        # Windows 平台需要转义换行符（与 _build_system_prompt 保持一致）
        # Claude CLI 在 Windows 上无法正确处理命令行参数中的实际换行符
        # 但会正确解释 \\n 为换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")
            logger.debug(f"[chat_with_files] Applied Windows newline escaping")

        resume = "resume" if options.resume else "new"
        logger.info(f"[QUERY] user={session.user_id}, model={self.model}, max_turns={settings.agent_max_turns}, prompt_len={len(prompt)}, session={resume}")
        logger.debug(f"[QUERY] ENV: ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', 'NOT SET')}")

        try:
            msg_count = 0
            async for message in query(prompt=prompt, options=options):
                msg_count += 1
                msg_type = type(message).__name__

                # Compact SDK logs: one line per message
                if hasattr(message, "tool_use") and message.tool_use:
                    tool_name = getattr(message.tool_use, "name", "unknown")
                    logger.info(f"[SDK] #{msg_count} Tool: {tool_name}")
                elif hasattr(message, "content") and message.content:
                    content_preview = str(message.content)[:100]
                    logger.info(f"[SDK] #{msg_count} {msg_type}: {content_preview}...")
                else:
                    logger.debug(f"[SDK] #{msg_count} {msg_type}")

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
            messages.append(message)

            if hasattr(message, "message"):
                msg_usage = getattr(message.message, "usage", None)
                if msg_usage:
                    usage["input_tokens"] += getattr(msg_usage, "input_tokens", 0)
                    usage["output_tokens"] += getattr(msg_usage, "output_tokens", 0)

        logger.info(f"Total messages received: {len(messages)}")
        return format_blocking_response(messages, usage)

    def reload_config(self) -> None:
        """重新加载配置"""
        self.base_system_prompt = load_system_prompt()
        self.mcp_config = load_mcp_config()
        self.allowed_tools = self._load_allowed_tools()
        logger.info("Agent service config reloaded")


# 全局 Agent 服务实例
agent_service = ClaudeAgentService()
