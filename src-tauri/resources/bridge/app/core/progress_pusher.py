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
from app.channels import get_file_client, get_messenger

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
        self._sent_files: set[str] = set()  # 本轮已发送的文件路径（用于文件级去重）
        self._pending_tool_files: List[str] = []  # MCP tool 检测到的待发送文件路径
        self._avatar_gate: Optional[Any] = None  # AvatarGate 实例（协作模式门控）

        # 从配置读取间隔
        self.intervals = settings.progress_push_intervals_list

    @property
    def context(self) -> Dict[str, Any]:
        """动态获取当前 context（每次访问都调用 getter）"""
        return self._context_getter()

    def set_avatar_gate(self, gate):
        """设置响应门控（协作模式）"""
        self._avatar_gate = gate

    def discard_pending(self):
        """丢弃所有缓冲消息（协作模式静默时调用）"""
        count = len(self.pending_texts)
        self.pending_texts.clear()
        if count:
            logger.info(f"[PROGRESS] Discarded {count} pending texts (avatar gate closed)")

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
                        text = self._clean_builtin_tool_output(text)
                        if text:
                            self.pending_texts.append(text)
                            logger.debug(f"[PROGRESS] Added text ({len(text)} chars): {text[:100]}...")

                # ToolUseBlock：检测 return_file_to_user 工具调用
                elif hasattr(block, "name") and block.name and "return_file_to_user" in block.name:
                    block_input = getattr(block, "input", {})
                    if isinstance(block_input, dict):
                        file_path = block_input.get("file_path", "")
                        if file_path:
                            # 文件级去重：检查是否已发送或已排队
                            resolved = str(Path(file_path).resolve()) if Path(file_path).exists() else file_path
                            already_sent = resolved in self._sent_files
                            already_pending = file_path in self._pending_tool_files
                            if already_sent or already_pending:
                                reason = "already sent" if already_sent else "already pending"
                                logger.info(f"[PROGRESS] Skipping duplicate return_file_to_user: {file_path} ({reason})")
                            else:
                                self._pending_tool_files.append(file_path)
                                logger.info(f"[PROGRESS] Detected return_file_to_user tool call: {file_path}")

            # 门控：_can_send=True 时发送，否则累积
            # return_file_to_user 工具调用无视冷却立即发送，避免文件被吞
            has_return_files = bool(self._pending_tool_files)
            has_content = bool(self.pending_texts) or has_return_files
            gate_open = not self._avatar_gate or self._avatar_gate.should_respond
            if (self._can_send or has_return_files) and has_content:
                if gate_open:
                    is_first = not self.first_push_done
                    await self._send_progress_internal(is_first=is_first)
                    if is_first:
                        self.first_push_done = True
                    self._can_send = False
                    self.push_count += 1
                    self._start_cooldown()
                # else: 门控关闭，pending_texts 保留缓冲，_can_send 不变
                #        后续门控打开时下一条消息会触发 flush

    def _clean_builtin_tool_output(self, text: str) -> str:
        """过滤 Z.ai Built-in Tool 中间过程输出（GLM-5 图片分析等）"""
        # 1. 工具调用块：包含 "Z.ai Built-in Tool:" 标识
        if "Z.ai Built-in Tool:" in text:
            logger.info(f"[PROGRESS] Filtered Z.ai tool invocation ({len(text)} chars)")
            return ""

        # 2. 工具输出块：以 **Output:** 开头 + 包含 _result 关键字（JSON 格式结果）
        if text.startswith("**Output:**") and "_result" in text:
            logger.info(f"[PROGRESS] Filtered Z.ai tool output ({len(text)} chars)")
            return ""

        return text

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
        """用户发送了新消息，重置冷却，允许下条消息立即发送"""
        # 取消冷却定时器
        if self._cooldown_task and not self._cooldown_task.done():
            self._cooldown_task.cancel()
            self._cooldown_task = None

        async with self._lock:
            self._can_send = True
            # pending_texts: 保留！已累积的文本会和下条回复合并发送，不再丢弃
            # first_push_done: 保留！维持合并推送模式（join 所有 pending_texts）
            # first_push_content: 保留！force_push_text 的文本去重继续生效
            self._sent_files.clear()  # 清空文件去重记录，允许用户要求重发
            self._pending_tool_files.clear()  # 清空待发送文件列表
        logger.info("[PROGRESS] User message received, cooldown cancelled, ready for next SDK message")

    async def _send_progress_internal(self, is_first: bool):
        """
        发送当前进度（内部方法，需在锁内调用）

        直接使用 SDK 输出内容，不加固定前缀
        首次推送只发送第一条，后续推送合并所有累积内容（避免丢失中间进度）
        支持 MCP tool 检测的文件上传到 COS
        """
        if not self.pending_texts and not self._pending_tool_files:
            return

        # 首次推送：只发送第一条（最早的回复）
        # 后续推送：合并所有累积内容（换行分隔，方便阅读）
        if self.pending_texts:
            if is_first:
                clean_content = self.pending_texts[0]
            else:
                clean_content = "\n\n".join(self.pending_texts)
        else:
            clean_content = ""

        self.pending_texts.clear()

        # 诊断日志：记录推送内容长度和尾部（排查截断问题）
        if clean_content:
            logger.info(
                f"[PROGRESS] Pushing text: len={len(clean_content)}, "
                f"tail=...{clean_content[-50:]}"
            )

        # 从 _pending_tool_files 获取文件列表（由 add_message 中 ToolUseBlock 检测填充）
        return_files = list(self._pending_tool_files)
        self._pending_tool_files.clear()

        if not clean_content.strip() and not return_files:
            logger.info(f"[PROGRESS] Skipping empty content (no text, no files)")
            return

        try:
            messenger = get_messenger(self.context.get("channel", "wecom"))

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

                    # Git Bash 路径归一化：/c/Users/... → C:\Users\...
                    path_str = str(file_path)
                    if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
                        drive = path_str[1].upper()
                        file_path = Path(f"{drive}:{path_str[2:]}")

                    # 如果是相对路径，相对于 workspace
                    if not file_path.is_absolute() and workspace:
                        file_path = Path(workspace) / file_path

                    # 双重保险：上传前再次检查是否已发送
                    resolved_check = str(file_path.resolve()) if file_path.exists() else str(file_path)
                    if resolved_check in self._sent_files:
                        logger.info(f"[PROGRESS] Skipping duplicate file upload: {file_path}")
                        continue

                    if not file_path.exists():
                        # 容错：去掉文件名中的空格重试
                        no_space = file_path.parent / file_path.name.replace(" ", "")
                        if no_space.exists():
                            logger.warning(f"[PROGRESS] File path corrected (spaces removed): {file_path.name} -> {no_space.name}")
                            file_path = no_space
                        else:
                            logger.warning(f"[PROGRESS] File not found: {file_path}")
                            continue

                    # 上传到 COS / 飞书
                    channel = self.context.get("channel", "wecom")
                    if user_token or channel == "feishu":
                        try:
                            file_client = get_file_client(channel)
                            cos_path = await file_client.upload_file(file_path, user_token)
                            if cos_path:
                                # 根据文件类型决定 type
                                suffix = file_path.suffix.lower()
                                if suffix in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"]:
                                    file_type = "image"
                                else:
                                    file_type = "file"
                                message_list.append({"type": file_type, "content": cos_path})
                                self._sent_files.add(str(file_path.resolve()))
                                logger.info(f"[PROGRESS] Uploaded file: {file_path} -> {cos_path}")
                            else:
                                logger.error(f"[PROGRESS] Failed to upload file: {file_path}")
                        except Exception as e:
                            logger.error(f"[PROGRESS] Error uploading file {file_path}: {e}")
                    else:
                        logger.warning(f"[PROGRESS] No user_token, cannot upload file: {file_path}")

                # 发送 message_list
                if message_list:
                    await messenger.send_message_list(
                        message_list=message_list,
                        conversation_id=self.context.get("conversation_id"),
                        user_name=self.context.get("user_name"),
                        group_chat_name=self.context.get("group_chat_name"),
                        is_group=self.context.get("is_group"),
                    )
                    # 发送成功后才记录去重标记
                    if is_first:
                        self.first_push_content = clean_content
                    self.last_pushed_content = clean_content
                    logger.info(f"[PROGRESS] Sent progress with {len(return_files)} files (first={is_first}, count={self.push_count})")
            else:
                # 没有文件，只发送文本
                if clean_content.strip():
                    await messenger.send_text(
                        content=clean_content,
                        conversation_id=self.context.get("conversation_id"),
                        user_name=self.context.get("user_name"),
                        group_chat_name=self.context.get("group_chat_name"),
                        is_group=self.context.get("is_group"),
                    )
                    # 发送成功后才记录去重标记
                    if is_first:
                        self.first_push_content = clean_content
                    self.last_pushed_content = clean_content
                    logger.info(f"[PROGRESS] Sent progress (first={is_first}, count={self.push_count}): {clean_content[:100]}...")
        except Exception as e:
            logger.error(f"[PROGRESS] Failed to send progress: {e}")
            import traceback
            logger.error(f"[PROGRESS] Traceback: {traceback.format_exc()}")
            return False

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
            messenger = get_messenger(self.context.get("channel", "wecom"))
            await messenger.send_message_list(
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
        # 门控关闭时不推送
        if self._avatar_gate and not self._avatar_gate.should_respond:
            return False

        async with self._lock:
            if self.pending_texts:
                result = await self._send_progress_internal(is_first=False)
                self.push_count += 1
                # ResultMessage 后也进入冷却，避免密集推送
                self._can_send = False
                self._start_cooldown()
                return result is not False
        return False

    async def force_push_text(self, text: str):
        """
        强制推送指定文本（兜底机制）

        当 ResultMessage 到达但 push_progress() 没有推送内容时调用。
        跳过去重检查（因为 add_message 可能已发送但 MCP 失败），
        确保用户一定能收到最终回复。
        """
        # 门控关闭时不推送
        if self._avatar_gate and not self._avatar_gate.should_respond:
            return

        try:
            messenger = get_messenger(self.context.get("channel", "wecom"))

            # 从 _pending_tool_files 获取文件列表
            clean_content = text
            return_files = list(self._pending_tool_files)
            self._pending_tool_files.clear()

            if not clean_content.strip() and not return_files:
                return

            # 检查文本是否与最近推送的内容重复（子串检查，兼容合并文本 vs 单条文本）
            text_already_sent = False
            if self.last_pushed_content and clean_content.strip() and (
                clean_content == self.last_pushed_content
                or clean_content in self.last_pushed_content
            ):
                text_already_sent = True
                logger.info(f"[PROGRESS] Force push text already included in last push")
            elif self.first_push_content and clean_content.strip() and (
                clean_content == self.first_push_content
                or clean_content in self.first_push_content
            ):
                text_already_sent = True
                logger.info(f"[PROGRESS] Force push text already included in first push")

            # 文件级去重：过滤掉已发送的文件
            if return_files:
                workspace = self.context.get("workspace")
                filtered_files = []
                for file_path_str in return_files:
                    file_path = Path(file_path_str)
                    if not file_path.is_absolute() and workspace:
                        file_path = Path(workspace) / file_path
                    resolved = str(file_path.resolve()) if file_path.exists() else str(file_path)
                    if resolved in self._sent_files:
                        logger.info(f"[PROGRESS] Skipping already sent file: {file_path}")
                    else:
                        filtered_files.append(file_path_str)
                return_files = filtered_files

            # 如果文本已发送且无新文件，完全跳过
            if text_already_sent and not return_files:
                logger.info(f"[PROGRESS] Skipping force push (content already sent, no new files)")
                return

            if return_files:
                message_list = []
                # 如果文本已发送过，不重复发送文本部分
                if clean_content.strip() and not text_already_sent:
                    message_list.append({"type": "txt", "content": clean_content})

                user_token = self.context.get("user_token")
                workspace = self.context.get("workspace")
                for file_path_str in return_files:
                    file_path = Path(file_path_str)
                    if not file_path.is_absolute() and workspace:
                        file_path = Path(workspace) / file_path
                    if not file_path.exists():
                        # 容错：去掉文件名中的空格重试
                        no_space = file_path.parent / file_path.name.replace(" ", "")
                        if no_space.exists():
                            logger.warning(f"[PROGRESS] File path corrected (spaces removed): {file_path.name} -> {no_space.name}")
                            file_path = no_space
                        else:
                            logger.warning(f"[PROGRESS] File not found (force push): {file_path}")
                            continue
                    channel = self.context.get("channel", "wecom")
                    if user_token or channel == "feishu":
                        try:
                            file_client = get_file_client(channel)
                            cos_path = await file_client.upload_file(file_path, user_token)
                            if cos_path:
                                suffix = file_path.suffix.lower()
                                file_type = "image" if suffix in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"] else "file"
                                message_list.append({"type": file_type, "content": cos_path})
                                self._sent_files.add(str(file_path.resolve()))
                        except Exception as e:
                            logger.error(f"[PROGRESS] Force push file upload error: {e}")

                if message_list:
                    await messenger.send_message_list(
                        message_list=message_list,
                        conversation_id=self.context.get("conversation_id"),
                        user_name=self.context.get("user_name"),
                        group_chat_name=self.context.get("group_chat_name"),
                        is_group=self.context.get("is_group"),
                    )
                    logger.info(f"[PROGRESS] Force pushed final result with {len(return_files)} files")
            else:
                await messenger.send_text(
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
            messenger = get_messenger(self.context.get("channel", "wecom"))
            await messenger.send_text(
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
        # 清理缓冲，断开闭包引用（帮助 GC 回收循环引用）
        self.pending_texts.clear()
        self._pending_tool_files.clear()
        self._sent_files.clear()
        self._context_getter = None
        logger.info(f"[PROGRESS] Pusher stopped (total pushes={self.push_count})")
