"""
请求路由器 - 零延迟消息分发

替代 6 秒消息聚合窗口，实现：
1. 消息到达后立即处理（零延迟）
2. Per-user 请求队列确保顺序
3. 智能识别消息类型（纯文件/有文本）
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable, Dict, List, Optional, Tuple

from app.config import settings
from app.core.query_parser import ParsedQuery
from app.core.user_session import UserSession, UserSessionContext, user_session_manager
from app.core.progress_pusher import ProgressPusher

logger = logging.getLogger(__name__)


@dataclass
class QueuedRequest:
    """排队中的请求"""
    request_id: str
    user_id: str
    parsed: ParsedQuery
    session_id: str
    user_name: Optional[str]
    user_token: Optional[str]
    timestamp: float = field(default_factory=time.time)
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())

    def age_seconds(self) -> float:
        """请求存在的时间（秒）"""
        return time.time() - self.timestamp


class RequestRouter:
    """
    请求路由器

    核心机制：
    1. 消息到达后立即分发到用户队列（零延迟）
    2. 每个用户有独立的 asyncio.Lock，确保串行处理
    3. 智能识别请求类型：
       - 纯文件请求：静默缓存，立即返回
       - 有文本请求：获取锁后处理，返回完整响应
    """

    def __init__(self):
        self._user_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()  # 保护 _user_locks
        self._request_counter = 0

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        """获取用户专属锁（线程安全）"""
        async with self._global_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            return self._user_locks[user_id]

    def _generate_request_id(self, user_id: str) -> str:
        """生成唯一请求 ID"""
        self._request_counter += 1
        return f"{user_id}_{int(time.time() * 1000)}_{self._request_counter}"

    async def route_request(
        self,
        user_id: str,
        parsed: ParsedQuery,
        session_id: str,
        user_name: Optional[str],
        user_token: Optional[str],
        process_func: Callable[..., Awaitable[Any]],
        conversation_id: Optional[str] = None,
        group_chat_name: Optional[str] = None,
        conversation_type: Optional[str] = None,
    ) -> Any:
        """
        路由请求到用户队列（零延迟）

        Args:
            user_id: 用户 ID
            parsed: 解析后的请求
            session_id: 会话 ID
            user_name: 用户名
            user_token: 用户令牌
            process_func: 处理函数
            conversation_id: 企微对话 ID（传递给 process_func）
            group_chat_name: 群聊名称（传递给 process_func）

        Returns:
            处理结果
        """
        request_id = self._generate_request_id(user_id)

        # 检查请求类型
        has_files = len(parsed.files) > 0
        has_meaningful_text = parsed.has_text_item

        logger.info(
            f"[ROUTER] Request {request_id}: "
            f"files={len(parsed.files)}, has_text={has_meaningful_text}"
        )

        # 获取用户锁
        user_lock = await self._get_user_lock(user_id)

        start_time = time.time()
        logger.info(f"[ROUTER] Request {request_id}: Waiting for user lock...")

        async with user_lock:
            wait_time = time.time() - start_time
            logger.info(f"[ROUTER] Request {request_id}: Lock acquired after {wait_time:.3f}s")

            # 检查超时
            if wait_time > settings.queue_timeout_seconds:
                logger.error(f"[ROUTER] Request {request_id}: Timeout after {wait_time:.1f}s")
                raise TimeoutError(f"Request waited too long in queue: {wait_time:.1f}s")

            # 调用处理函数
            try:
                result = await process_func(
                    user_id=user_id,
                    parsed=parsed,
                    session_id=session_id,
                    user_name=user_name,
                    user_token=user_token,
                    conversation_id=conversation_id,
                    group_chat_name=group_chat_name,
                    conversation_type=conversation_type,
                )

                process_time = time.time() - start_time - wait_time
                logger.info(
                    f"[ROUTER] Request {request_id}: Completed "
                    f"(wait={wait_time:.3f}s, process={process_time:.3f}s)"
                )

                return result

            except Exception as e:
                logger.error(f"[ROUTER] Request {request_id}: Failed with error: {e}")
                raise

    async def route_request_with_async(
        self,
        user_id: str,
        parsed: ParsedQuery,
        session_id: str,
        user_name: Optional[str],
        user_token: Optional[str],
        process_func: Callable[..., Awaitable[Any]],
        timeout_seconds: float = 120,
        async_context: Optional[Dict] = None,
    ) -> Any:
        """
        带异步超时的请求路由

        在 timeout_seconds 内完成 → 正常返回结果
        超时 → 返回中间消息，后台继续等待 SDK 完成并主动推送

        Args:
            user_id: 用户 ID
            parsed: 解析后的请求
            session_id: 会话 ID
            user_name: 用户名
            user_token: 用户令牌
            process_func: 处理函数
            timeout_seconds: 等待超时（秒）
            async_context: 异步推送上下文（conversation_id, user_name, group_chat_name）
        """
        from app.api.schemas import ChatResponse, MessageItem

        user_lock = await self._get_user_lock(user_id)

        # 1. 尝试获取锁（1s 快速检测是否有前序请求）
        try:
            await asyncio.wait_for(user_lock.acquire(), timeout=1)
        except asyncio.TimeoutError:
            # 锁被占用：HTTP 挂起等待前序请求完成
            # 不返回任何 HTTP 响应，避免 Dify 工作流顶替 bug
            # （Dify bug：任何 HTTP 返回都会让工作流 B "完成"并顶掉正在运行的 A）
            logger.info(f"[ASYNC] Lock busy for {user_id}, HTTP holding until previous request completes")
            try:
                await asyncio.wait_for(user_lock.acquire(), timeout=settings.queue_timeout_seconds)
            except asyncio.TimeoutError:
                # 等待超时：不得已返回（此时前序工作流大概率已完成）
                logger.error(f"[ASYNC] Lock wait timed out for {user_id} after {settings.queue_timeout_seconds}s")
                return ChatResponse(message_list=[
                    MessageItem(type="txt", content="上一条消息处理时间过长，请重新发送。")
                ])
            logger.info(f"[ASYNC] Lock acquired after waiting for {user_id}")

        # 2. 启动处理任务
        request_id = self._generate_request_id(user_id)
        logger.info(f"[ASYNC] Request {request_id}: Starting with {timeout_seconds}s timeout")

        # 从 async_context 提取 conversation_id, group_chat_name, conversation_type
        context = async_context or {}
        task = asyncio.create_task(process_func(
            user_id=user_id,
            parsed=parsed,
            session_id=session_id,
            user_name=user_name,
            user_token=user_token,
            conversation_id=context.get("conversation_id"),
            group_chat_name=context.get("group_chat_name"),
            conversation_type=context.get("conversation_type"),
        ))

        try:
            # 3. 等待完成或超时（shield 防止取消正在运行的 SDK 任务）
            result = await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
            user_lock.release()
            logger.info(f"[ASYNC] Request {request_id}: Completed within timeout")
            return result

        except asyncio.TimeoutError:
            # 4. 超时 → 立即释放锁，让新请求可以进来
            user_lock.release()
            logger.info(
                f"[ASYNC] Request {request_id}: Timeout after {timeout_seconds}s, "
                f"lock released, switching to async push for {user_id}"
            )

            import random
            timeout_messages = [
                "任务需要一点时间，请放心，完成后我会发给你",
                "收到，完成后我会发给你",
                "好嘞，完成后发你",
                "没问题，完成后发你",
                "好滴，做好了发你",
                "可能需要几分钟，完成后发你",
                "稍等，做好了发你",
            ]
            content = random.choice(timeout_messages)
            logger.info(f"[ASYNC] Request {request_id}: Timeout, async message: {content}")

            # 后台继续等待，完成后通过 sendMsg 推送（不再管理锁）
            asyncio.create_task(
                self._handle_async_completion_no_lock(
                    task, user_id, request_id, async_context or {}
                )
            )
            return ChatResponse(message_list=[
                MessageItem(type="txt", content=content)
            ])

        except Exception as e:
            logger.error(f"[ASYNC] Request {request_id}: Failed with error: {e}")
            task.cancel()
            user_lock.release()
            raise

    async def _handle_async_completion_no_lock(
        self,
        task: asyncio.Task,
        user_id: str,
        request_id: str,
        context: Dict,
    ):
        """后台等待 SDK 完成并主动推送结果（不管理锁）

        注意：锁已经在超时时释放，此方法只负责等待任务完成并推送结果。
        """
        try:
            result = await task
            logger.info(f"[ASYNC] Request {request_id}: Background task completed for {user_id}")

            if result.message_list:
                from app.services.proactive_messenger import proactive_messenger
                await proactive_messenger.send_message_list(
                    message_list=result.message_list,
                    conversation_id=context.get("conversation_id"),
                    user_name=context.get("user_name"),
                    group_chat_name=context.get("group_chat_name"),
                )
                logger.info(
                    f"[ASYNC] Request {request_id}: Results sent for {user_id}: "
                    f"{len(result.message_list)} messages"
                )
            else:
                logger.warning(f"[ASYNC] Request {request_id}: Empty result for {user_id}")

        except Exception as e:
            logger.error(f"[ASYNC] Request {request_id}: Background task failed for {user_id}: {e}")
            # 尝试发送错误通知
            try:
                from app.services.proactive_messenger import proactive_messenger
                await proactive_messenger.send_text(
                    content="处理过程中出现了问题，请重新发送你的请求。",
                    conversation_id=context.get("conversation_id"),
                    user_name=context.get("user_name"),
                    group_chat_name=context.get("group_chat_name"),
                )
            except Exception as notify_err:
                logger.error(
                    f"[ASYNC] Request {request_id}: "
                    f"Failed to send error notification for {user_id}: {notify_err}"
                )
        # 注意：这里不再释放锁，因为锁已经在超时时释放了

    async def route_request_immediate_async(
        self,
        user_id: str,
        parsed: ParsedQuery,
        session_id: str,
        user_name: Optional[str],
        user_token: Optional[str],
        process_func: Callable[..., Awaitable[Any]],
        async_context: Optional[Dict] = None,
    ) -> Any:
        """
        立即返回模式：HTTP 立即返回空响应，后台处理并推送结果

        工作流程：
        1. 首条消息：创建 UserSession，启动 SDK 任务（后台运行）
        2. HTTP 立即返回空响应
        3. SDK 有输出 → ProgressPusher 推送进度
        4. SDK 完成 → 推送最终结果
        5. 后续消息 → 追加到已有 session 的队列

        Args:
            user_id: 用户 ID
            parsed: 解析后的请求
            session_id: 会话 ID
            user_name: 用户名
            user_token: 用户令牌
            process_func: 处理函数（需要支持 pusher 参数）
            async_context: 异步推送上下文（conversation_id, user_name, group_chat_name）
        """
        from app.api.schemas import ChatResponse
        from pathlib import Path

        request_id = self._generate_request_id(user_id)
        context = async_context or {}

        logger.info(f"[IMMEDIATE] Request {request_id}: Received (immediate return mode)")

        # 构建会话上下文
        session_context = UserSessionContext(
            user_id=user_id,
            session_id=session_id,
            user_name=user_name,
            user_token=user_token,
            conversation_id=context.get("conversation_id"),
            group_chat_name=context.get("group_chat_name"),
            workspace=context.get("workspace"),
            conversation_type=context.get("conversation_type"),
            channel=context.get("channel", "wecom"),
        )
        logger.info(
            f"[IMMEDIATE] session_context: user_id={session_context.user_id!r}, "
            f"session_id={session_context.session_id!r}, "
            f"user_name={session_context.user_name!r}, "
            f"conversation_id={session_context.conversation_id!r}, "
            f"channel={session_context.channel!r}, "
            f"conversation_type={session_context.conversation_type!r}, "
            f"workspace={session_context.workspace!r}"
        )

        # 获取或创建用户会话
        session, is_new = await user_session_manager.get_or_create_session(
            user_id=user_id,
            context=session_context,
            process_func=process_func,
        )

        if is_new:
            logger.info(f"[IMMEDIATE] Request {request_id}: New session created (session_key={session.session_key})")
        else:
            logger.info(f"[IMMEDIATE] Request {request_id}: Appending to existing session (session_key={session.session_key})")

        # 添加消息到会话（首条会启动任务，后续会追加）
        started_new_task = await session.add_message(parsed)

        if started_new_task:
            logger.info(f"[IMMEDIATE] Request {request_id}: SDK task started in background")
        else:
            logger.info(f"[IMMEDIATE] Request {request_id}: Message queued")

        # HTTP 立即返回空响应
        logger.info(f"[IMMEDIATE] Request {request_id}: Returning empty response immediately")
        return ChatResponse(message_list=[])

    async def cleanup_inactive_locks(self, keep_user_ids: set = None) -> int:
        """
        清理不活跃用户的锁（防止内存泄漏）

        Args:
            keep_user_ids: 需要保留的用户 ID 集合

        Returns:
            清理的锁数量
        """
        if keep_user_ids is None:
            keep_user_ids = set()

        async with self._global_lock:
            to_remove = []
            for user_id, lock in self._user_locks.items():
                if user_id not in keep_user_ids and not lock.locked():
                    to_remove.append(user_id)

            for user_id in to_remove:
                del self._user_locks[user_id]

            if to_remove:
                logger.info(f"[ROUTER] Cleaned up {len(to_remove)} inactive locks")

            return len(to_remove)


# 全局实例
request_router = RequestRouter()
