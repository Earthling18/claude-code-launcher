"""
进度推送器 - 固定冷却期 + 事件驱动推送

策略：
1. 首条 AssistantMessage 立即推送，进入冷却期
2. 冷却期内的 AssistantMessage 累积不发送
3. 冷却到期后如有累积 → 发送最新一条 + 重新冷却（循环推送）
4. 冷却到期后无累积 → 解锁状态，等下条消息触发
5. ResultMessage 始终立即推送（不受冷却影响）
6. 用户发新消息时取消冷却、清空累积，下一条 SDK 消息立即发送
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.mcp_tools.file_output_tool import parse_return_files_from_text
from app.services.cos_client import cos_client

logger = logging.getLogger(__name__)


class ProgressPusher:
    """
    进度推送器

    收集 SDK 输出的 AssistantMessage，按冷却机制推送给用户：
    - 首条消息立即推送，进入冷却期
    - 冷却期内累积不发送
    - 冷却到期有累积 → 发送最新一条，重新冷却（循环推送）
    - 冷却到期无累积 → 解锁，下条消息立即发送
    - 用户新消息重置冷却
    - ResultMessage 始终立即推送
    """

    DEFAULT_INTERVALS = [15]

    def __init__(self, context: Dict[str, Any] | Callable[[], Dict[str, Any]]):
        """
        初始化进度推送器

        Args:
            context: 推送上下文，或者返回上下文的 callable（支持动态获取最新 context）
                     包含 conversation_id, user_name, group_chat_name, is_group
        """
        self._context_getter = context if callable(context) else lambda: context
        self._cached_context: Optional[Dict[str, Any]] = None  # 缓存（仅用于非 callable 情况）
        self.pending_texts: List[str] = []  # 累积的思考文本
        self.push_count = 0  # 已推送次数
        self.first_push_done = False  # 首次推送是否完成
        self.first_push_content: Optional[str] = None  # 首次推送的内容（用于去重）
        self.last_pushed_content: Optional[str] = None  # 最近推送的内容（用于 force_push 去重）
        self._running = False
        self._can_send: bool = True  # 门控：True=下条消息可立即发送
        self._cooldown_task: Optional[asyncio.Task] = None  # 一次性冷却定时器
        self._lock = asyncio.Lock()  # 保护 pending_texts 和 _can_send

        # 从配置读取间隔
        self.intervals = settings.progress_push_intervals_list

    @property
    def context(self) -> Dict[str, Any]:
        """动态获取当前 context（每次访问都调用 getter）"""
        return self._context_getter()

    async def start(self):
        """启动推送器"""
        self._running = True
        self._can_send = True
        interval = self.intervals[0] if self.intervals else 15
        logger.info(f"[PROGRESS] Pusher started, cooldown_interval={interval}s")

    async def add_message(self, message: Any):
        """
        添加过程消息（从 AssistantMessage 提取文本）

        门控逻辑：_can_send=True 时立即发送，否则累积等待冷却到期。

        Args:
            message: SDK 的 AssistantMessage
        """
        # 提取 TextBlock 内容
        if not hasattr(message, "content") or not message.content:
            return

        async with self._lock:
            for block in message.content:
                # TextBlock 有 text 属性
                if hasattr(block, "text"):
                    text = block.text.strip()
                    if text:
                        self.pending_texts.append(text)
                        logger.debug(f"[PROGRESS] Added text ({len(text)} chars): {text[:100]}...")

            # 门控：_can_send=True 时发送，否则累积
            if self._can_send and self.pending_texts:
                is_first = not self.first_push_done
                await self._send_progress_internal(is_first=is_first)
                if is_first:
                    self.first_push_done = True
                self._can_send = False
                self.push_count += 1
                self._start_cooldown()

    def _start_cooldown(self):
        """发送后启动冷却定时器"""
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
        self._cooldown_task = asyncio.create_task(self._cooldown_timer())

    async def _cooldown_timer(self):
        """等待冷却到期，发送累积内容或解锁发送状态"""
        interval = self.intervals[0] if self.intervals else 15
        try:
            await asyncio.sleep(interval)
            async with self._lock:
                if self.pending_texts:
                    # 到期时有累积 → 发送最新一条，重新冷却
                    await self._send_progress_internal(is_first=False)
                    self.push_count += 1
                    logger.debug(f"[PROGRESS] Cooldown expired, sent pending content, restarting cooldown")
                    self._start_cooldown()
                else:
                    # 到期时无累积 → 解锁，等待下条消息触发
                    self._can_send = True
                    logger.debug(f"[PROGRESS] Cooldown expired, no pending content, ready for next message")
        except asyncio.CancelledError:
            pass

    async def notify_user_message(self):
        """用户发送了新消息，取消冷却并重置"""
        # 取消冷却定时器
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            self._cooldown_task = None

        async with self._lock:
            self._can_send = True
            self.pending_texts.clear()
            self.first_push_done = False
        logger.info("[PROGRESS] User message received, cooldown cancelled, ready for next SDK message")

    async def _send_progress_internal(self, is_first: bool):
        """
        发送当前进度（内部方法，需在锁内调用）

        直接使用 SDK 输出内容，不加固定前缀
        首次推送只发送第一条，后续推送合并所有累积内容（避免丢失中间进度）
        支持解析 RETURN_FILES 并上传文件到 COS
        """
        if not self.pending_texts:
            return

        # 首次推送：只发送第一条（最早的回复）
        # 后续推送：合并所有累积内容（换行分隔，方便阅读）
        if is_first:
            content = self.pending_texts[0]
        else:
            content = "\n\n".join(self.pending_texts)

        self.pending_texts.clear()

        # 解析 RETURN_FILES 标记
        return_files, clean_content = parse_return_files_from_text(content)
        if not clean_content.strip() and not return_files:
            logger.info(f"[PROGRESS] Skipping empty content after cleaning RETURN_FILES")
            return

        # 记录推送内容，用于去重
        if is_first:
            self.first_push_content = clean_content
        self.last_pushed_content = clean_content

        try:
            from app.services.proactive_messenger import proactive_messenger

            # 如果有文件需要发送，构建 message_list
            if return_files:
                message_list = []

                # 添加文本消息
                if clean_content.strip():
                    message_list.append({"type": "txt", "content": clean_content})

                # 上传文件到 COS 并添加到 message_list
                user_token = self.context.get("user_token")
                workspace = self.context.get("workspace")

                for file_path_str in return_files:
                    file_path = Path(file_path_str)

                    # 如果是相对路径，相对于 workspace
                    if not file_path.is_absolute() and workspace:
                        file_path = Path(workspace) / file_path

                    if not file_path.exists():
                        logger.warning(f"[PROGRESS] File not found: {file_path}")
                        continue

                    # 上传到 COS
                    if user_token:
                        try:
                            cos_path = await cos_client.upload_file(file_path, user_token)
                            if cos_path:
                                # 根据文件类型决定 type
                                suffix = file_path.suffix.lower()
                                if suffix in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
                                    file_type = "image"
                                else:
                                    file_type = "file"
                                message_list.append({"type": file_type, "content": cos_path})
                                logger.info(f"[PROGRESS] Uploaded file: {file_path} -> {cos_path}")
                            else:
                                logger.error(f"[PROGRESS] Failed to upload file: {file_path}")
                        except Exception as e:
                            logger.error(f"[PROGRESS] Error uploading file {file_path}: {e}")
                    else:
                        logger.warning(f"[PROGRESS] No user_token, cannot upload file: {file_path}")

                # 发送 message_list
                if message_list:
                    await proactive_messenger.send_message_list(
                        message_list=message_list,
                        conversation_id=self.context.get("conversation_id"),
                        user_name=self.context.get("user_name"),
                        group_chat_name=self.context.get("group_chat_name"),
                        is_group=self.context.get("is_group"),
                    )
                    logger.info(f"[PROGRESS] Sent progress with {len(return_files)} files (first={is_first}, count={self.push_count})")
            else:
                # 没有文件，只发送文本
                if clean_content.strip():
                    await proactive_messenger.send_text(
                        content=clean_content,
                        conversation_id=self.context.get("conversation_id"),
                        user_name=self.context.get("user_name"),
                        group_chat_name=self.context.get("group_chat_name"),
                        is_group=self.context.get("is_group"),
                    )
                    logger.info(f"[PROGRESS] Sent progress (first={is_first}, count={self.push_count}): {clean_content[:100]}...")
        except Exception as e:
            logger.error(f"[PROGRESS] Failed to send progress: {e}")
            import traceback
            logger.error(f"[PROGRESS] Traceback: {traceback.format_exc()}")

    async def send_final_result(
        self,
        message_list: List[Any],
    ):
        """
        发送最终结果

        注意：调用此方法前会清空 pending_texts，避免重复发送

        Args:
            message_list: ChatResponse 的 message_list
        """
        # 停止冷却定时器，避免与最终结果冲突
        self._running = False
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            self._cooldown_task = None

        # 清空 pending_texts，避免重复发送
        async with self._lock:
            if self.pending_texts:
                logger.info(f"[PROGRESS] Clearing {len(self.pending_texts)} pending texts before final result")
                self.pending_texts.clear()

        # 检查是否需要去重（避免与首次进度推送重复）
        # 如果首次已推送，且最终结果包含相同的文本消息，移除重复的文本
        if self.first_push_done and self.first_push_content:
            filtered_list = []
            skipped_text = False
            for item in message_list:
                item_type = item.type if hasattr(item, "type") else item.get("type", "")
                item_content = item.content if hasattr(item, "content") else item.get("content", "")
                # 如果文本内容与首次推送相同，跳过（只跳过第一个匹配的）
                if item_type == "txt" and item_content == self.first_push_content and not skipped_text:
                    logger.info(f"[PROGRESS] Removing duplicate text (same as first push)")
                    skipped_text = True
                    continue
                filtered_list.append(item)

            # 如果过滤后没有消息了，直接返回
            if not filtered_list:
                logger.info(f"[PROGRESS] Skipping final result (all messages are duplicates)")
                return

            message_list = filtered_list

        try:
            from app.services.proactive_messenger import proactive_messenger
            await proactive_messenger.send_message_list(
                message_list=message_list,
                conversation_id=self.context.get("conversation_id"),
                user_name=self.context.get("user_name"),
                group_chat_name=self.context.get("group_chat_name"),
                is_group=self.context.get("is_group"),
            )
            logger.info(f"[PROGRESS] Sent final result: {len(message_list)} messages")
        except Exception as e:
            logger.error(f"[PROGRESS] Failed to send final result: {e}")

    async def push_progress(self) -> bool:
        """
        立即推送当前累积的进度

        用于在 ResultMessage 后立即推送，不受冷却影响

        Returns:
            True 如果推送了内容，False 如果没有内容可推送
        """
        async with self._lock:
            if self.pending_texts:
                await self._send_progress_internal(is_first=False)
                self.push_count += 1
                # ResultMessage 后也进入冷却，避免密集推送
                self._can_send = False
                self._start_cooldown()
                return True
        return False

    async def force_push_text(self, text: str):
        """
        强制推送指定文本（兜底机制）

        当 ResultMessage 到达但 push_progress() 没有推送内容时调用。
        跳过去重检查（因为 add_message 可能已发送但 MCP 失败），
        确保用户一定能收到最终回复。
        """
        try:
            from app.services.proactive_messenger import proactive_messenger

            # 解析 RETURN_FILES
            return_files, clean_content = parse_return_files_from_text(text)
            if not clean_content.strip() and not return_files:
                return

            # 检查是否与最近推送的内容相同（避免重复）
            # 在 parse_return_files 之后比较，确保去掉标记后一致
            if self.last_pushed_content and clean_content == self.last_pushed_content:
                logger.info(f"[PROGRESS] Skipping force push (same as last pushed content)")
                return
            if self.first_push_content and clean_content == self.first_push_content:
                logger.info(f"[PROGRESS] Skipping force push (same as first push)")
                return

            if return_files:
                message_list = []
                if clean_content.strip():
                    message_list.append({"type": "txt", "content": clean_content})

                user_token = self.context.get("user_token")
                workspace = self.context.get("workspace")
                for file_path_str in return_files:
                    file_path = Path(file_path_str)
                    if not file_path.is_absolute() and workspace:
                        file_path = Path(workspace) / file_path
                    if not file_path.exists():
                        continue
                    if user_token:
                        try:
                            cos_path = await cos_client.upload_file(file_path, user_token)
                            if cos_path:
                                suffix = file_path.suffix.lower()
                                file_type = "image" if suffix in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"] else "file"
                                message_list.append({"type": file_type, "content": cos_path})
                        except Exception as e:
                            logger.error(f"[PROGRESS] Force push file upload error: {e}")

                if message_list:
                    await proactive_messenger.send_message_list(
                        message_list=message_list,
                        conversation_id=self.context.get("conversation_id"),
                        user_name=self.context.get("user_name"),
                        group_chat_name=self.context.get("group_chat_name"),
                        is_group=self.context.get("is_group"),
                    )
                    logger.info(f"[PROGRESS] Force pushed final result with {len(return_files)} files")
            else:
                await proactive_messenger.send_text(
                    content=clean_content,
                    conversation_id=self.context.get("conversation_id"),
                    user_name=self.context.get("user_name"),
                    group_chat_name=self.context.get("group_chat_name"),
                    is_group=self.context.get("is_group"),
                )
                logger.info(f"[PROGRESS] Force pushed final text: {clean_content[:100]}...")
            self.push_count += 1
        except Exception as e:
            logger.error(f"[PROGRESS] Force push failed: {e}")

    async def stop_push_loop(self):
        """
        停止冷却定时器（但不清空 pending_texts）

        用于在 send_final_result 之前立即停止，避免竞态条件
        """
        self._running = False
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            self._cooldown_task = None
        logger.info(f"[PROGRESS] Cooldown stopped")

    async def send_error(self, error_message: str = "处理过程中出现了问题，请重新发送。"):
        """发送错误消息"""
        try:
            from app.services.proactive_messenger import proactive_messenger
            await proactive_messenger.send_text(
                content=error_message,
                conversation_id=self.context.get("conversation_id"),
                user_name=self.context.get("user_name"),
                group_chat_name=self.context.get("group_chat_name"),
                is_group=self.context.get("is_group"),
            )
            logger.info(f"[PROGRESS] Sent error message")
        except Exception as e:
            logger.error(f"[PROGRESS] Failed to send error: {e}")

    async def stop(self):
        """停止推送器"""
        self._running = False
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            self._cooldown_task = None
        logger.info(f"[PROGRESS] Pusher stopped (total pushes={self.push_count})")
