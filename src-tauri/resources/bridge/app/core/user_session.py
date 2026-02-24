"""
用户会话管理器 - 管理用户的消息队列和 SDK 任务

v2.8 最终方案（双任务架构）：
- SDK 的 query() 是非阻塞的，只写入 transport 立即返回
- sender 任务：监听消息队列，调用 query() 发送
- receiver 任务：使用 receive_messages() 持续接收
- 新消息可以在 Claude 处理过程中立即发送，不需要等待当前任务完成
- 类似正常对话，用户可以边等边补充指令
"""
import asyncio
import json
import logging
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

from app.config import settings
from app.core.query_parser import ParsedQuery
from app.core.progress_pusher import ProgressPusher
from app.core.security_hooks import build_security_hooks

logger = logging.getLogger(__name__)


def _log_stderr(line: str) -> None:
    """记录 CLI 的 stderr 输出"""
    if not line or not line.strip():
        return
    line_lower = line.lower()
    if "prompt is too long" in line_lower or "context" in line_lower:
        logger.warning(f"[CLI STDERR] Context limit warning: {line}")
    elif "error" in line_lower or "failed" in line_lower:
        logger.warning(f"[CLI STDERR] Error: {line}")
    else:
        logger.debug(f"[CLI STDERR] {line}")


@dataclass
class UserSessionContext:
    """用户会话上下文"""
    user_id: str
    session_id: str
    user_name: Optional[str] = None
    user_token: Optional[str] = None
    conversation_id: Optional[str] = None
    group_chat_name: Optional[str] = None
    workspace: Optional[Path] = None
    conversation_type: Optional[str] = None  # 企微会话类型：'GROUP' 或 'PRIVATE'


class UserSession:
    """
    用户会话：管理消息队列和 SDK 长连接

    v2.8 最终方案（双任务架构）：

    SDK 调研发现：
    - query() 是非阻塞的，只写入 transport 立即返回
    - receive_messages() 持续接收消息，不会因 ResultMessage 停止
    - 可以在接收响应的同时发送新消息

    架构设计：
    1. 首条消息到达 → 创建 ClaudeSDKClient 连接
    2. 启动两个并行任务：
       - sender 任务：监听消息队列，调用 query() 发送（非阻塞）
       - receiver 任务：使用 receive_messages() 持续接收
    3. 新消息到达 → 入队并通知 sender 任务
    4. sender 任务立即发送，不需要等待当前任务完成
    5. Claude 在处理过程中实时接收新消息

    关键特性：
    - 真正的流式输入：新消息在 Claude 处理过程中立即发送
    - 类似正常对话：用户可以边等边补充指令
    - 上下文累积：同一连接中的所有消息共享对话历史
    - 零延迟：不需要等待 ResultMessage 才处理下一条消息
    """

    # 消息队列超时（秒）：超时后结束消息流
    MESSAGE_QUEUE_TIMEOUT = 300  # 5 分钟

    def __init__(self, user_id: str, context: UserSessionContext, session_key: Optional[str] = None):
        self.user_id = user_id          # 保留，用于日志和 workspace
        self.session_key = session_key or user_id  # 用于 dict/持久化/request_queue
        self.context = context
        self.message_queue: asyncio.Queue[ParsedQuery] = asyncio.Queue()
        self.sdk_task: Optional[asyncio.Task] = None
        self.pusher: Optional[ProgressPusher] = None
        self._running = False
        self._created_at = time.time()
        self._last_activity = time.time()

        # 处理函数（由外部注入，用于文件处理等）
        self._process_func: Optional[Callable] = None

        # v2.8: SDK 长连接（内聚到 UserSession）
        self._client: Optional[ClaudeSDKClient] = None
        self._is_connected = False
        self._connection_lock = asyncio.Lock()  # 保护连接操作

        # v2.8 最终方案：双任务架构
        self._sender_task: Optional[asyncio.Task] = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._new_message_event = asyncio.Event()  # 通知 sender 有新消息
        self._pending_messages = 0

        # 用于 resume 恢复上下文：存储上次对话的 session_id
        self._claude_session_id: Optional[str] = None

        # 群聊历史截点：记录上次注入的群聊历史最后一条消息时间
        self._last_history_cutoff: Optional[str] = None

        # 持久化回调：捕获 session_id 时通知 manager 写入磁盘
        self._on_session_id_captured: Optional[Callable[[str, str], None]] = None

    @property
    def is_running(self) -> bool:
        """检查 SDK 任务是否正在运行（只要 receiver 在运行，会话就是活的）"""
        if not self._running:
            return False
        # 只检查 receiver 任务：receiver 代表 SDK 长连接
        # sender 可能因超时退出，但可以重启
        receiver_running = self._receiver_task is not None and not self._receiver_task.done()
        return receiver_running

    @property
    def _sender_running(self) -> bool:
        """检查 sender 任务是否在运行"""
        return self._sender_task is not None and not self._sender_task.done()

    @property
    def age_seconds(self) -> float:
        """会话存在时间（秒）"""
        return time.time() - self._created_at

    @property
    def idle_seconds(self) -> float:
        """空闲时间（秒）"""
        return time.time() - self._last_activity

    def set_process_func(self, func: Callable):
        """设置处理函数"""
        self._process_func = func

    def _build_sdk_options(self) -> ClaudeAgentOptions:
        """构建 SDK 选项"""
        from app.core.agent_service import agent_service

        project_root = Path(__file__).parent.parent.parent.resolve()

        options_kwargs = {
            "model": settings.claude_model,
            "system_prompt": agent_service._build_system_prompt(
                workspace_path=str(self.context.workspace),
                conversation_id=self.context.conversation_id,
                is_group=self._is_group(),
            ),
            "allowed_tools": agent_service.allowed_tools,
            "cwd": str(project_root),
            "setting_sources": ["user", "project"],
            "max_buffer_size": 50 * 1024 * 1024,  # 50MB
            "stderr": _log_stderr,
        }

        if settings.claude_cli_path:
            options_kwargs["cli_path"] = settings.claude_cli_path

        options = ClaudeAgentOptions(**options_kwargs)

        # 安全钩子：黑名单拦截敏感路径和危险命令
        options.hooks = build_security_hooks()

        # 恢复上下文：使用上次对话的 session_id
        if self._claude_session_id:
            options.resume = self._claude_session_id
            logger.info(f"[SESSION] User {self.user_id}: Resuming with session_id: {self._claude_session_id[:20]}...")

        # MCP 配置
        options.mcp_servers = agent_service._build_mcp_servers(self.context.workspace)

        return options

    def _is_group(self) -> bool:
        """判断是否群聊"""
        conv_type = self.context.conversation_type
        return conv_type == "GROUP" if conv_type else bool(self.context.group_chat_name)

    def _write_env_and_context(self):
        """设置环境变量并写入 .request_context.json，供 cron_cli.py 等脚本读取"""
        # 设置环境变量（subprocess 在创建时继承快照）
        if self.context.workspace:
            os.environ["CLAUDE_USER_WORKSPACE"] = str(self.context.workspace)
        if self.context.conversation_id:
            os.environ["CLAUDE_CONVERSATION_ID"] = self.context.conversation_id
        else:
            os.environ.pop("CLAUDE_CONVERSATION_ID", None)
        os.environ["CLAUDE_IS_GROUP"] = "true" if self._is_group() else "false"

        # 写入 .request_context.json 到用户 workspace
        if self.context.workspace:
            context_data = {
                "user_id": self.user_id,
                "user_name": self.context.user_name or "",
                "conversation_id": self.context.conversation_id or "",
                "group_chat_name": self.context.group_chat_name or "",
                "is_group": self._is_group(),
                "conversation_type": self.context.conversation_type or "",
                "user_token": self.context.user_token or "",
            }
            context_file = Path(self.context.workspace) / ".request_context.json"
            try:
                context_file.write_text(
                    json.dumps(context_data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"[SESSION] Failed to write request context: {e}")

    async def _ensure_connection(self) -> bool:
        """
        确保 SDK 连接存在

        Returns:
            True 如果连接成功，False 如果失败
        """
        async with self._connection_lock:
            if self._is_connected and self._client is not None:
                return True

            try:
                options = self._build_sdk_options()
                self._write_env_and_context()
                self._client = ClaudeSDKClient(options=options)
                await self._client.__aenter__()
                self._is_connected = True
                logger.info(f"[SESSION] User {self.user_id}: SDK connection established")
                return True
            except Exception as e:
                logger.error(f"[SESSION] User {self.user_id}: SDK connection failed: {e}")
                self._is_connected = False
                self._client = None

                # If resume failed, clear stale session_id and retry fresh
                if self._claude_session_id:
                    logger.warning(f"[SESSION] User {self.user_id}: Clearing stale session_id and retrying fresh")
                    self._claude_session_id = None
                    try:
                        options = self._build_sdk_options()
                        self._client = ClaudeSDKClient(options=options)
                        await self._client.__aenter__()
                        self._is_connected = True
                        logger.info(f"[SESSION] User {self.user_id}: SDK connection established (fresh)")
                        return True
                    except Exception as e2:
                        logger.error(f"[SESSION] User {self.user_id}: Fresh connection also failed: {e2}")
                        self._is_connected = False
                        self._client = None

                return False

    async def _close_connection(self):
        """关闭 SDK 连接"""
        async with self._connection_lock:
            if self._is_connected and self._client is not None:
                try:
                    await self._client.__aexit__(None, None, None)
                    logger.info(f"[SESSION] User {self.user_id}: SDK connection closed")
                except Exception as e:
                    logger.error(f"[SESSION] User {self.user_id}: SDK close error: {e}")
                finally:
                    self._is_connected = False
                    self._client = None

    async def add_message(self, parsed: ParsedQuery) -> bool:
        """
        添加消息到队列

        v2.8 最终方案（双任务架构）：
        - 消息入队后通知 sender 任务
        - sender 任务立即调用 query() 发送（非阻塞）
        - Claude 在处理过程中实时接收新消息

        Args:
            parsed: 解析后的请求

        Returns:
            True 如果启动了新任务，False 如果追加到现有任务
        """
        self._last_activity = time.time()
        await self.message_queue.put(parsed)
        self._pending_messages += 1
        self._new_message_event.set()  # 通知 sender 任务有新消息
        logger.info(f"[SESSION] User {self.user_id}: Message added to queue (queue_size={self.message_queue.qsize()}, pending={self._pending_messages})")

        if not self._running:
            # 首条消息：启动双任务（sender + receiver）
            self._running = True
            self._receiver_task = asyncio.create_task(self._run_receiver())
            self._sender_task = asyncio.create_task(self._run_sender())
            # 保持 sdk_task 指向 receiver（用于兼容 is_running 检查）
            self.sdk_task = self._receiver_task
            logger.info(f"[SESSION] User {self.user_id}: Dual-task architecture started (sender + receiver)")
            return True
        else:
            # 后续消息：通知 pusher 重置冷却，下一条 SDK 消息立即发送
            if self.pusher:
                await self.pusher.notify_user_message()

            # 如果 sender 已超时退出但 receiver 仍在运行，重启 sender
            if not self._sender_running:
                self._sender_task = asyncio.create_task(self._run_sender())
                logger.info(f"[SESSION] User {self.user_id}: Sender restarted (was timed out), message will be sent")
            else:
                logger.info(f"[SESSION] User {self.user_id}: Message queued, sender will send immediately")
            return False

    async def _run_sender(self):
        """
        v2.8 最终方案：Sender 任务

        监听消息队列，调用 query() 发送消息。
        query() 是非阻塞的，立即返回，Claude 会立即收到新消息。
        """
        logger.info(f"[SESSION] User {self.user_id}: Sender task started")

        try:
            # 等待连接建立
            while self._running and not self._is_connected:
                await asyncio.sleep(0.1)

            if not self._running:
                return

            while self._running:
                try:
                    # 等待新消息通知（带超时）
                    await asyncio.wait_for(
                        self._new_message_event.wait(),
                        timeout=self.MESSAGE_QUEUE_TIMEOUT
                    )
                    self._new_message_event.clear()

                    # 发送队列中所有消息
                    while not self.message_queue.empty() and self._running:
                        try:
                            parsed = self.message_queue.get_nowait()
                            self._pending_messages -= 1

                            # 构建 prompt
                            prompt = await self._build_prompt_for_message(parsed)
                            logger.info(f"[SESSION] User {self.user_id}: Sending to Claude: '{prompt[:50]}...'")

                            # 非阻塞发送！Claude 立即收到
                            await self._client.query(prompt)
                            logger.info(f"[SESSION] User {self.user_id}: Message sent successfully")

                        except asyncio.QueueEmpty:
                            break

                except asyncio.TimeoutError:
                    # 超时，检查是否有未完成的工作
                    logger.info(f"[SESSION] User {self.user_id}: No new messages for {self.MESSAGE_QUEUE_TIMEOUT}s")
                    # 超时后退出 sender，让 receiver 自然结束
                    break

        except asyncio.CancelledError:
            logger.info(f"[SESSION] User {self.user_id}: Sender task cancelled")
        except Exception as e:
            logger.error(f"[SESSION] User {self.user_id}: Sender task error: {e}")
            import traceback
            logger.error(f"[SESSION] Traceback:\n{traceback.format_exc()}")
        finally:
            logger.info(f"[SESSION] User {self.user_id}: Sender task ended")

    async def _run_receiver(self):
        """
        v2.8 最终方案：Receiver 任务

        使用 receive_messages() 持续接收 Claude 的响应。
        receive_messages() 不会因 ResultMessage 停止，可以持续接收多轮对话。
        """
        logger.info(f"[SESSION] User {self.user_id}: Receiver task started")

        # 创建 pusher，使用 callable 动态获取最新 context
        # 这样会话复用时（私聊切群聊），pusher 能获取到正确的 context
        def get_pusher_context() -> Dict[str, Any]:
            return {
                "conversation_id": self.context.conversation_id,
                "user_name": self.context.user_name,
                "group_chat_name": self.context.group_chat_name,
                "is_group": self._is_group(),
                # 用于文件上传到 COS
                "user_token": self.context.user_token,
                "workspace": self.context.workspace,
            }
        self.pusher = ProgressPusher(get_pusher_context)
        await self.pusher.start()

        try:
            # 建立 SDK 连接
            connected = await self._ensure_connection()
            if not connected:
                logger.error(f"[SESSION] User {self.user_id}: Failed to establish SDK connection")
                await self.pusher.send_error()
                return

            # 持续接收 Claude 的响应
            # receive_messages() 不会因 ResultMessage 停止
            logger.info(f"[SESSION] User {self.user_id}: Starting to receive messages")
            result_count = 0
            last_text_content = None  # 跟踪最近一条 TextBlock 内容
            async for response in self._client.receive_messages():
                msg_type = type(response).__name__
                logger.info(f"[SESSION] User {self.user_id}: Received {msg_type}")

                # 捕获 session_id 用于后续 resume 恢复上下文（所有消息类型都检查）
                if hasattr(response, "session_id") and response.session_id:
                    if self._claude_session_id != response.session_id:
                        self._claude_session_id = response.session_id
                        logger.info(f"[SESSION] User {self.user_id}: Captured session_id for resume: {response.session_id[:20]}...")
                        # 通知 manager 持久化到磁盘
                        if self._on_session_id_captured:
                            self._on_session_id_captured(self.session_key, response.session_id)

                # 处理响应内容
                if hasattr(response, "content") and response.content:
                    content_preview = str(response.content)[:100]
                    logger.info(f"[SESSION] User {self.user_id}: Content: {content_preview}...")

                # 将 AssistantMessage 传递给 pusher
                if msg_type == "AssistantMessage" and self.pusher:
                    # 跟踪最近的 TextBlock 内容（用于 ResultMessage 兜底推送）
                    if hasattr(response, "content") and response.content:
                        for block in response.content:
                            if hasattr(block, "text") and block.text.strip():
                                last_text_content = block.text.strip()
                    await self.pusher.add_message(response)

                # ResultMessage 表示一轮对话完成
                # 但不退出循环，继续等待下一轮对话的响应
                if msg_type == "ResultMessage":
                    result_count += 1
                    logger.info(f"[SESSION] User {self.user_id}: Round {result_count} complete, waiting for next...")
                    # 推送当前累积的进度
                    if self.pusher:
                        pushed = await self.pusher.push_progress()
                        # 兜底：如果 push_progress 没有推送内容（pending_texts 为空），
                        # 强制推送最后一条 TextBlock 内容，确保用户收到最终回复
                        if not pushed and last_text_content:
                            logger.info(f"[SESSION] User {self.user_id}: push_progress had nothing, force pushing last text")
                            await self.pusher.force_push_text(last_text_content)
                    last_text_content = None  # 重置，防止重复推送

            logger.info(f"[SESSION] User {self.user_id}: Receiver loop ended (total rounds: {result_count})")

        except asyncio.CancelledError:
            logger.info(f"[SESSION] User {self.user_id}: Receiver task cancelled")
        except Exception as e:
            logger.error(f"[SESSION] User {self.user_id}: Receiver task error: {e}")
            import traceback
            logger.error(f"[SESSION] Traceback:\n{traceback.format_exc()}")
            if self.pusher:
                await self.pusher.send_error()
        finally:
            self._running = False
            await self._close_connection()
            if self.pusher:
                await self.pusher.stop()
                self.pusher = None
            logger.info(f"[SESSION] User {self.user_id}: Receiver task ended")

    async def _build_prompt_for_message(self, parsed: ParsedQuery) -> str:
        """
        为单条消息构建 prompt

        处理文件下载、格式转换等，包括：
        1. 从 request_queue 读取缓存文件（先发文件后发文字场景）
        2. 处理当前请求中的文件（文件+文字一起到达的场景）

        Args:
            parsed: 解析后的请求

        Returns:
            构建好的 prompt 字符串
        """
        from app.core.file_processor import file_processor
        from app.core.message_builder import MessageBuilder
        from app.core.request_queue import request_queue

        workspace_path = str(self.context.workspace)
        user_text = parsed.text

        # 处理用户文本中的换行符
        if user_text:
            user_text = user_text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

        all_processed_files = []

        # 1. 获取 request_queue 缓存的文件（先发文件后发文字场景）
        cached_entries = request_queue.get_and_clear_pending_files(self.session_key)
        if cached_entries:
            cached_dicts = [
                {
                    "type": e.file_type,
                    "content": e.content,
                    "filename": e.filename,
                }
                for e in cached_entries
            ]
            cached_processed = await file_processor.process_cached_files(
                cached_files=cached_dicts,
                workspace=self.context.workspace,
            )
            all_processed_files.extend(cached_processed)

        # 2. 处理当前请求中的文件（文件+文字一起到达的场景）
        if parsed.files:
            current_processed = await file_processor.process_files(
                file_items=parsed.files,
                workspace=self.context.workspace,
                user_token=self.context.user_token or "",
            )
            all_processed_files.extend(current_processed)

        # 3. 构建 prompt
        if all_processed_files:
            has_images = MessageBuilder.has_images(all_processed_files)

            if has_images:
                file_paths = [str(f.local_path) for f in all_processed_files]
                files_str = "\n".join(file_paths)
                prompt = f"{files_str}\n{user_text}" if user_text else files_str
            else:
                prompt = MessageBuilder.build_text_only_prompt(
                    user_text, all_processed_files, workspace_path
                )
        else:
            prompt = user_text or ""

        # 群聊场景：注入群聊上下文（只注入上次交互之后的新消息）
        if self._is_group() and parsed.history_list:
            from app.core.query_parser import format_group_chat_history
            group_context, latest_time = format_group_chat_history(
                parsed.history_list,
                since_time=self._last_history_cutoff,
            )
            if group_context:
                prompt = group_context + "\n" + prompt
                logger.info(f"[SESSION] User {self.user_id}: Injected group chat context ({len(group_context)} chars)")
            if latest_time:
                self._last_history_cutoff = latest_time

        # Windows 平台需要转义换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")

        return prompt


    async def stop(self):
        """停止会话"""
        self._running = False

        # 停止 sender 任务
        if self._sender_task:
            self._sender_task.cancel()
            try:
                await self._sender_task
            except asyncio.CancelledError:
                pass
            self._sender_task = None

        # 停止 receiver 任务
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            self._receiver_task = None

        # 清理 sdk_task 引用
        self.sdk_task = None

        await self._close_connection()

        if self.pusher:
            await self.pusher.stop()
            self.pusher = None

        logger.info(f"[SESSION] User {self.user_id}: Session stopped")


class UserSessionManager:
    """
    用户会话管理器

    维护 per-user 的 UserSession，支持：
    - 首条消息创建会话
    - 后续消息追加到会话（流式注入）
    - 会话超时清理
    """

    # 会话超时（秒）：超过此时间无活动则清理
    SESSION_TIMEOUT = 1800  # 30 分钟

    # claude_session_id 持久化文件
    SESSIONS_FILE = Path("workspace/claude_sessions.json")

    @staticmethod
    def make_session_key(user_id: str, conversation_id: Optional[str] = None) -> str:
        """构建会话隔离 key：user_id:conversation_id"""
        if conversation_id:
            return f"{user_id}:{conversation_id}"
        return user_id

    def __init__(self):
        self._sessions: Dict[str, UserSession] = {}
        self._global_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    def _load_all_claude_session_ids(self) -> dict:
        """加载所有持久化的 session_id"""
        if self.SESSIONS_FILE.exists():
            try:
                return json.loads(self.SESSIONS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _load_claude_session_id(self, session_key: str) -> Optional[str]:
        """从磁盘加载 claude_session_id"""
        data = self._load_all_claude_session_ids()
        return data.get(session_key)

    def _save_claude_session_id(self, session_key: str, session_id: str):
        """持久化 claude_session_id 到磁盘"""
        data = self._load_all_claude_session_ids()
        data[session_key] = session_id
        self.SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.SESSIONS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info(f"[SESSION_MGR] {session_key}: Persisted session_id to disk")

    async def start(self):
        """启动管理器"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("[SESSION_MGR] Started")

    async def stop(self):
        """停止管理器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # 停止所有会话
        async with self._global_lock:
            for session in self._sessions.values():
                await session.stop()
            self._sessions.clear()

        logger.info("[SESSION_MGR] Stopped")

    async def get_or_create_session(
        self,
        user_id: str,
        context: UserSessionContext,
        process_func: Callable,
    ) -> Tuple[UserSession, bool]:
        """
        获取或创建用户会话

        Args:
            user_id: 用户 ID
            context: 会话上下文
            process_func: 处理函数（v2.8 中不再使用，保留兼容）

        Returns:
            (UserSession, is_new) - 会话对象和是否新创建
        """
        # 计算 session_key：按 conversation_id 隔离对话上下文
        session_key = self.make_session_key(user_id, context.conversation_id)

        async with self._global_lock:
            # 检查现有会话
            if session_key in self._sessions:
                session = self._sessions[session_key]
                # 复用时更新上下文
                session.context = context
                # 确保回调已注入（防御性编程）
                if not session._on_session_id_captured:
                    session._on_session_id_captured = self._save_claude_session_id
                if session.is_running:
                    logger.info(f"[SESSION_MGR] {session_key}: Reusing running session (context updated)")
                else:
                    # 会话空闲（receiver 已结束），复用以保留 _claude_session_id 用于 resume
                    logger.info(f"[SESSION_MGR] {session_key}: Reusing idle session (will resume with session_id)")
                return session, False

            # 创建新会话
            session = UserSession(user_id, context, session_key=session_key)
            session.set_process_func(process_func)
            # 尝试从磁盘恢复 claude_session_id（跨清理/跨重启恢复）
            saved_id = self._load_claude_session_id(session_key)
            if saved_id:
                session._claude_session_id = saved_id
                logger.info(f"[SESSION_MGR] {session_key}: Restored session_id from disk: {saved_id[:20]}...")
            # 注入持久化回调
            session._on_session_id_captured = self._save_claude_session_id
            self._sessions[session_key] = session
            logger.info(f"[SESSION_MGR] {session_key}: New session created")
            return session, True

    async def remove_session(self, session_key: str):
        """移除会话"""
        async with self._global_lock:
            if session_key in self._sessions:
                session = self._sessions.pop(session_key)
                await session.stop()
                logger.info(f"[SESSION_MGR] {session_key}: Session removed")

    async def _cleanup_loop(self):
        """定期清理超时会话"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次

                async with self._global_lock:
                    to_remove = []
                    for session_key, session in self._sessions.items():
                        if session.idle_seconds > self.SESSION_TIMEOUT and not session.is_running:
                            to_remove.append(session_key)

                    for session_key in to_remove:
                        session = self._sessions.pop(session_key)
                        await session.stop()
                        logger.info(f"[SESSION_MGR] {session_key}: Session cleaned up (idle={session.idle_seconds:.0f}s)")

                    if to_remove:
                        logger.info(f"[SESSION_MGR] Cleaned up {len(to_remove)} sessions, remaining={len(self._sessions)}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SESSION_MGR] Cleanup error: {e}")


# 全局实例
user_session_manager = UserSessionManager()
