"""
代理 Agent — 使用独立 query() 执行长任务（Subagent 模式）

WorkerSession 为后台委托任务提供独立的 Agent 执行环境：
- 独立的 query() 调用（完全独立的上下文窗口）
- 独立的 MCP + Skills
- 完成后将完整结果注入主会话，由主 Agent 转达给用户
- Worker 不直接推送给用户（仅错误除外）
"""
import asyncio
import logging
import os
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from claude_agent_sdk import query, ClaudeAgentOptions

import app.config as config
from app.config import settings
from app.core.task_registry import task_registry, BackgroundTask, TaskStatus
from app.core.progress_pusher import ProgressPusher

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

logger = logging.getLogger(__name__)

# Watchdog thresholds (seconds)
_WATCHDOG_INTERVAL = 30
_IDLE_WARN_THRESHOLD = 300   # 5 minutes
_IDLE_FAIL_THRESHOLD = 900   # 15 minutes
_WORKER_TIMEOUT = 1800       # 30 minutes — hard cap for entire worker run


_STDERR_WARN_KEYWORDS = [
    "error", "failed", "prompt is too long", "context",
    "timeout", "timed out", "rate limit", "rate_limit", "ratelimit",
    "connection", "refused", "reset", "econnrefused", "econnreset",
    "etimedout", "epipe", "eof", "broken pipe",
]


def _log_stderr(line: str) -> None:
    """记录 CLI 的 stderr 输出"""
    if not line or not line.strip():
        return
    line_lower = line.lower()
    if any(kw in line_lower for kw in _STDERR_WARN_KEYWORDS):
        logger.warning(f"[WORKER STDERR] {line}")
    else:
        logger.info(f"[WORKER STDERR] {line}")


class WorkerSession:
    """
    代理 Agent 执行环境

    使用独立 query() 执行长任务，有完全独立的上下文窗口和工具集。
    """

    def __init__(
        self,
        task: BackgroundTask,
        workspace: Path,
        pusher_context: Dict[str, Any],
        notify_session_key: str,
    ):
        self.task = task
        self.workspace = workspace
        self.pusher_context = pusher_context
        self.notify_session_key = notify_session_key

    def _build_options(self) -> ClaudeAgentOptions:
        """构建独立的 SDK 选项"""
        from app.core.agent_service import agent_service

        # --settings 内联覆盖（防止用户 ~/.claude/settings.json 干扰 apiUrl/model）
        settings_override = agent_service._build_settings_override()

        options_kwargs = {
            "model": settings.claude_model,
            "system_prompt": self._build_worker_prompt(),
            "allowed_tools": [
                "Bash", "Read", "Write", "Edit", "Glob", "Grep",
                "Skill", "WebSearch", "WebFetch",
            ],
            "cwd": config.resolved_agent_root,
            "setting_sources": ["project", "local"],  # 自动加载 Skills，local 覆盖 model/apiUrl
            "max_buffer_size": 50 * 1024 * 1024,
            "permission_mode": "bypassPermissions",
            "stderr": _log_stderr,
        }
        if settings_override:
            options_kwargs["settings"] = settings_override

        resolved_cli = settings.resolve_cli_path()
        if resolved_cli:
            options_kwargs["cli_path"] = resolved_cli

        options = ClaudeAgentOptions(**options_kwargs)

        # Worker 不设置安全钩子（hooks）
        # hooks 在 query() 一次性调用模式下会出现 Stream closed 错误
        # bypassPermissions 跳过 CLI 权限检查（与主会话一致）
        # 安全边界由 allowed_tools 控制（无 MCP 工具）

        # Worker 不注册 MCP 服务器：
        # 1. allowed_tools 中无 MCP 工具，注册了也用不到
        # 2. query() 一次性调用模式下，MCP 服务器的管道通信在 close() 时会触发
        #    CLIConnectionError: ProcessTransport is not ready for writing

        return options

    def _build_worker_prompt(self) -> str:
        """构建 Worker 系统提示：使用专用精简 prompt（不继承主 prompt）"""
        from app.core.agent_service import agent_service

        prompt = agent_service.worker_system_prompt
        prompt = prompt.replace("{workspace}", str(self.workspace))
        prompt = prompt.replace("{task_type}", self.task.task_type)

        # Windows 平台需要转义换行符
        if platform.system() == "Windows":
            prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")

        return prompt

    @staticmethod
    def _estimate_message_bytes(message: Any) -> int:
        """估算消息内容的字节大小（用于追踪 context 累积）"""
        total = 0
        if hasattr(message, "content"):
            content = message.content
            if isinstance(content, str):
                total += len(content.encode("utf-8", errors="replace"))
            elif isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        total += len(block.text.encode("utf-8", errors="replace"))
                    elif hasattr(block, "thinking"):
                        total += len(block.thinking.encode("utf-8", errors="replace"))
                    elif hasattr(block, "content"):
                        # ToolResultBlock etc.
                        bc = block.content
                        if isinstance(bc, str):
                            total += len(bc.encode("utf-8", errors="replace"))
                        elif isinstance(bc, list):
                            for item in bc:
                                if isinstance(item, dict) and "text" in item:
                                    total += len(str(item["text"]).encode("utf-8", errors="replace"))
                                elif hasattr(item, "text"):
                                    total += len(item.text.encode("utf-8", errors="replace"))
        return total

    @staticmethod
    def _describe_message(message: Any) -> str:
        """格式化消息类型为可读字符串，用于看门狗日志"""
        msg_type = type(message).__name__
        if msg_type == "AssistantMessage" and hasattr(message, "content") and message.content:
            parts: List[str] = []
            for block in message.content:
                block_type = type(block).__name__
                if hasattr(block, "name"):  # ToolUseBlock
                    parts.append(f"Tool({getattr(block, 'name', '?')})")
                elif hasattr(block, "text") and block.text.strip():
                    parts.append(f"Text({len(block.text)}ch)")
                elif block_type == "ThinkingBlock":
                    parts.append(f"Think({len(getattr(block, 'thinking', ''))}ch)")
                else:
                    parts.append(block_type)
            return f"AssistantMessage[{', '.join(parts)}]" if parts else "AssistantMessage[empty]"
        return msg_type

    @staticmethod
    def _collect_subprocess_diag() -> str:
        """收集当前进程的 claude 子进程诊断信息"""
        if not _HAS_PSUTIL:
            return "psutil_not_installed"
        try:
            current = psutil.Process(os.getpid())
            children = current.children(recursive=True)
            claude_procs = []
            for child in children:
                try:
                    name = child.name().lower()
                    cmdline = " ".join(child.cmdline()).lower()
                    if "claude" in name or "claude" in cmdline or "node" in name:
                        mem_mb = child.memory_info().rss / (1024 * 1024)
                        cpu = child.cpu_percent(interval=0)
                        claude_procs.append(
                            f"pid={child.pid},status={child.status()},mem={mem_mb:.0f}MB,cpu={cpu}%"
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            if claude_procs:
                return "; ".join(claude_procs)
            return "NO_SUBPROCESS_FOUND"
        except Exception as e:
            return f"error: {e}"

    async def _watchdog(self, task_id: str, state: Dict[str, Any]):
        """独立看门狗：每 30s 输出诊断日志，检测 idle 超时"""
        try:
            while True:
                await asyncio.sleep(_WATCHDOG_INTERVAL)
                now = time.time()
                elapsed = int(now - state["start_time"])
                msgs = state["msg_count"]
                idle = int(now - state["last_msg_time"])
                last_type = state.get("last_type", "none")
                diag = self._collect_subprocess_diag()

                ctx_kb = state.get("total_ctx_bytes", 0) / 1024
                last_kb = state.get("last_msg_bytes", 0) / 1024

                if idle >= _IDLE_FAIL_THRESHOLD:
                    logger.error(
                        f"[WATCHDOG] {task_id} HUNG: no messages for {idle}s. "
                        f"ctx={ctx_kb:.0f}KB, last_msg={last_kb:.0f}KB. "
                        f"Subprocess: {diag}"
                    )
                elif idle >= _IDLE_WARN_THRESHOLD:
                    logger.warning(
                        f"[WATCHDOG] {task_id} IDLE WARNING: no messages for {idle}s. "
                        f"ctx={ctx_kb:.0f}KB, last_msg={last_kb:.0f}KB. "
                        f"Subprocess: {diag}"
                    )
                else:
                    logger.info(
                        f"[WATCHDOG] {task_id}: elapsed={elapsed}s, msgs={msgs}, "
                        f"idle={idle}s, last_type={last_type}, "
                        f"ctx={ctx_kb:.0f}KB, subprocess={diag}"
                    )
        except asyncio.CancelledError:
            logger.info(f"[WATCHDOG] {task_id} watchdog stopped")

    async def run(self):
        """在后台 asyncio.Task 中执行（Subagent 模式：结果注入主会话，不直接推送用户）"""
        self.task.status = TaskStatus.RUNNING
        task_id = self.task.task_id
        logger.info(f"[WORKER] Task {task_id} starting: {self.task.description[:100]}")

        # pusher 仅用于错误推送，正常结果走主会话
        pusher = ProgressPusher(self.pusher_context)
        await pusher.start()

        watchdog_task: Optional[asyncio.Task] = None

        try:
            options = self._build_options()
            last_text = None
            msg_count = 0
            start_time = time.time()
            last_heartbeat = start_time

            # 看门狗共享状态（同一事件循环，无需锁）
            watchdog_state: Dict[str, Any] = {
                "start_time": start_time,
                "msg_count": 0,
                "last_msg_time": start_time,
                "last_type": "none",
                "total_ctx_bytes": 0,
                "last_msg_bytes": 0,
            }
            watchdog_task = asyncio.create_task(self._watchdog(task_id, watchdog_state))

            # Windows 平台转义 prompt 换行符
            prompt = self.task.description
            if platform.system() == "Windows":
                prompt = prompt.replace("\r\n", "\\n").replace("\n", "\\n")

            async with asyncio.timeout(_WORKER_TIMEOUT):
                async for message in query(prompt=prompt, options=options):
                    msg_count += 1
                    msg_type = type(message).__name__
                    elapsed = int(time.time() - start_time)

                    # 更新看门狗状态
                    msg_bytes = self._estimate_message_bytes(message)
                    watchdog_state["msg_count"] = msg_count
                    watchdog_state["last_msg_time"] = time.time()
                    watchdog_state["last_type"] = self._describe_message(message)
                    watchdog_state["total_ctx_bytes"] += msg_bytes
                    watchdog_state["last_msg_bytes"] = msg_bytes

                    # 心跳日志：每 60 秒输出一次
                    now = time.time()
                    if now - last_heartbeat >= 60:
                        logger.info(f"[WORKER] Task {task_id} heartbeat: {msg_count} msgs, {elapsed}s elapsed")
                        last_heartbeat = now

                    # AssistantMessage → 记录 block 类型详情
                    if msg_type == "AssistantMessage" and hasattr(message, "content") and message.content:
                        block_types = []
                        for block in message.content:
                            block_type = type(block).__name__
                            if hasattr(block, "text") and block.text.strip():
                                last_text = block.text.strip()
                                # 更新进度快照（仅纯文本，不含工具调用信息）
                                self.task.progress_snapshot = last_text[:150]
                                block_types.append(f"Text({len(block.text)}ch)")
                            elif hasattr(block, "name"):  # ToolUseBlock
                                tool_name = getattr(block, "name", "unknown")
                                block_types.append(f"Tool({tool_name})")
                            elif block_type == "ThinkingBlock":
                                thinking_len = len(getattr(block, "thinking", ""))
                                block_types.append(f"Think({thinking_len}ch)")
                            else:
                                block_types.append(block_type)
                        logger.info(f"[WORKER] Task {task_id} #{msg_count} ({elapsed}s): {msg_type} [{', '.join(block_types)}]")
                    elif msg_type == "ResultMessage":
                        result_text = ""
                        if hasattr(message, "content"):
                            result_text = str(message.content)[:100]
                        logger.info(f"[WORKER] Task {task_id} #{msg_count} ({elapsed}s): ResultMessage - {result_text}")
                    else:
                        extra = ""
                        if msg_bytes > 10240:  # 大于 10KB 的消息标注大小
                            extra = f" ({msg_bytes // 1024}KB)"
                        logger.info(f"[WORKER] Task {task_id} #{msg_count} ({elapsed}s): {msg_type}{extra}")

            # 任务完成 → 注入完整结果到主会话
            total_elapsed = int(time.time() - start_time)
            summary = last_text[:500] if last_text else "任务已完成"
            task_registry.complete(task_id, summary)
            logger.info(f"[WORKER] Task {task_id} completed ({msg_count} messages, {total_elapsed}s)")
            await self._notify_main_session(last_text or "任务已完成")

        except TimeoutError:
            elapsed = int(time.time() - start_time)
            task_registry.fail(task_id, f"Worker timed out after {_WORKER_TIMEOUT}s")
            logger.error(f"[WORKER] Task {task_id} timed out after {elapsed}s ({msg_count} msgs)")
            await pusher.send_error(f"后台任务执行超时（{_WORKER_TIMEOUT // 60}分钟），请重试。")

        except asyncio.CancelledError:
            elapsed = int(time.time() - start_time)
            task_registry.cancel(task_id)
            logger.info(f"[WORKER] Task {task_id} cancelled after {elapsed}s ({msg_count} msgs)")
        except Exception as e:
            elapsed = int(time.time() - start_time)
            error_msg = str(e)[:200]
            task_registry.fail(task_id, error_msg)
            logger.error(f"[WORKER] Task {task_id} failed after {elapsed}s ({msg_count} msgs): {e}")
            import traceback
            logger.error(f"[WORKER] Traceback:\n{traceback.format_exc()}")
            # 错误直接推给用户（不经过主 Agent）
            await pusher.send_error(f"刚才安排的任务执行遇到问题: {str(e)[:100]}")
        finally:
            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()
                try:
                    await watchdog_task
                except asyncio.CancelledError:
                    pass
            await pusher.stop()

    async def _notify_main_session(self, full_result: str):
        """向主会话注入完成通知 + 完整结果（subagent → 主 agent）"""
        try:
            from app.core.user_session import user_session_manager
            from app.core.query_parser import ParsedQuery
            from app.mcp_tools.file_output_tool import parse_return_files_from_text

            session = user_session_manager._sessions.get(self.notify_session_key)
            if not session:
                logger.warning(f"[WORKER] Main session {self.notify_session_key} not found, skipping notification")
                return

            desc_short = self.task.description[:100]

            # Worker 使用文本标记（MCP 在 query() 模式下有管道兼容性问题）
            return_files, clean_text = parse_return_files_from_text(full_result)
            result_text = clean_text[:8000]

            parts = [
                f"[任务完成] {desc_short}",
                f"",
                result_text,
            ]

            if return_files:
                parts.append(f"")
                parts.append(f"产出文件（请用 return_file_to_user 发送）：")
                for fp in return_files:
                    parts.append(f"  {fp}")

            notification = ParsedQuery(
                text="\n".join(parts),
                files=[],
                is_system_notification=True,
            )
            await session.add_system_notification(notification)
            logger.info(f"[WORKER] Injected result to main session {self.notify_session_key} (files={len(return_files) if return_files else 0})")
        except Exception as e:
            logger.error(f"[WORKER] Failed to notify main session: {e}")
