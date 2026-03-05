"""
请求队列管理器

Per-user 请求队列和锁，确保：
1. 文件请求完成后才处理文本请求
2. 所有文件操作（下载、缓存读取、合并）都在同一个锁内完成
"""
import asyncio
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.core.file_processor import file_processor, ProcessedFile
from app.core.query_parser import QueryItem, ParsedQuery

logger = logging.getLogger(__name__)


# 文件缓存超时时间（秒）
FILE_CACHE_TIMEOUT = 300  # 5 分钟


@dataclass
class PendingFileEntry:
    """缓存的文件条目"""
    file_type: str  # file/image
    content: str  # 本地路径
    filename: str
    timestamp: float = field(default_factory=time.time)


class RequestQueue:
    """
    请求队列管理器

    核心机制：
    - 每个用户一个独立的 asyncio.Lock
    - 所有文件操作（下载、缓存读取、合并）都在锁内完成
    - 解决时序问题：文件请求 → 等待锁 → 文本请求获取锁时文件已就绪
    """

    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._pending_files: Dict[str, List[PendingFileEntry]] = {}
        self._global_lock = asyncio.Lock()  # 保护 _locks 字典的原子性初始化

    async def _get_lock(self, user_id: str) -> asyncio.Lock:
        """获取用户专属的锁（线程安全）

        使用全局锁保护锁字典的初始化，避免竞态条件：
        如果两个请求同时到达且 user_id 相同，可能创建两个不同的锁对象
        """
        async with self._global_lock:
            if user_id not in self._locks:
                self._locks[user_id] = asyncio.Lock()
            return self._locks[user_id]

    def _clear_expired_files(self, user_id: str) -> None:
        """清理超时的缓存文件"""
        if user_id not in self._pending_files:
            return

        now = time.time()
        original_count = len(self._pending_files[user_id])
        self._pending_files[user_id] = [
            f for f in self._pending_files[user_id]
            if now - f.timestamp < FILE_CACHE_TIMEOUT
        ]

        removed = original_count - len(self._pending_files[user_id])
        if removed > 0:
            logger.info(f"[RequestQueue] Cleared {removed} expired files for user {user_id}")

    def _add_pending_files(
        self,
        user_id: str,
        files: List[ProcessedFile],
    ) -> None:
        """添加文件到缓存"""
        if user_id not in self._pending_files:
            self._pending_files[user_id] = []

        for f in files:
            entry = PendingFileEntry(
                file_type=f.original_type,
                content=str(f.local_path),
                filename=f.filename,
            )
            self._pending_files[user_id].append(entry)

        logger.info(
            f"[RequestQueue] Cached {len(files)} files for user {user_id}, "
            f"total: {len(self._pending_files[user_id])}"
        )

    def get_and_clear_pending_files(self, user_id: str) -> List[PendingFileEntry]:
        """获取并清空缓存的文件"""
        files = self._pending_files.pop(user_id, [])
        if files:
            logger.info(f"[RequestQueue] Retrieved and cleared {len(files)} pending files for user {user_id}")
        return files

    async def process_file_only_request(
        self,
        user_id: str,
        parsed: ParsedQuery,
        workspace: Path,
        user_token: str,
        channel: str = "wecom",
    ) -> Tuple[bool, int]:
        """
        处理纯文件请求（文件上传但没有文本）

        在锁内完成：
        1. 下载并处理文件
        2. 缓存文件供后续文本请求使用

        Args:
            user_id: 用户 ID
            parsed: 解析后的请求（包含文件列表）
            workspace: 工作目录
            user_token: 用户鉴权 Token
            channel: 渠道标识 ("wecom" | "feishu")

        Returns:
            (success, file_count) 元组
        """
        lock = await self._get_lock(user_id)
        async with lock:
            # 清理过期缓存
            self._clear_expired_files(user_id)

            logger.info(f"[RequestQueue] Processing file-only request for user {user_id}")

            # 下载并处理文件
            processed_files = await file_processor.process_files(
                file_items=parsed.files,
                workspace=workspace,
                user_token=user_token,
                channel=channel,
            )

            if not processed_files:
                logger.error(f"[RequestQueue] No files processed for user {user_id}")
                return False, 0

            # 缓存文件
            self._add_pending_files(user_id, processed_files)

            return True, len(processed_files)

    async def process_text_request(
        self,
        user_id: str,
        parsed: ParsedQuery,
        workspace: Path,
        user_token: str,
        channel: str = "wecom",
    ) -> Tuple[str, List[ProcessedFile]]:
        """
        处理文本请求（可能带有文件）

        在锁内完成：
        1. 获取缓存的文件
        2. 下载当前请求的文件（如果有）
        3. 合并所有文件

        Args:
            user_id: 用户 ID
            parsed: 解析后的请求
            workspace: 工作目录
            user_token: 用户鉴权 Token
            channel: 渠道标识 ("wecom" | "feishu")

        Returns:
            (text, processed_files) 元组
        """
        lock = await self._get_lock(user_id)
        async with lock:
            # 清理过期缓存
            self._clear_expired_files(user_id)

            logger.info(f"[RequestQueue] Processing text request for user {user_id}")

            all_files: List[ProcessedFile] = []

            # 1. 获取缓存的文件
            cached_entries = self.get_and_clear_pending_files(user_id)
            if cached_entries:
                logger.info(f"[RequestQueue] Found {len(cached_entries)} cached files")

                # 将缓存条目转换为 ProcessedFile
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
                    workspace=workspace,
                )
                all_files.extend(cached_processed)

            # 2. 下载当前请求的文件（如果有）
            # 飞书渠道不需要 user_token（内部使用 tenant_token）
            if parsed.files and (user_token or channel == "feishu"):
                logger.info(f"[RequestQueue] Downloading {len(parsed.files)} files from current request")
                current_processed = await file_processor.process_files(
                    file_items=parsed.files,
                    workspace=workspace,
                    user_token=user_token,
                    channel=channel,
                )
                all_files.extend(current_processed)

            logger.info(
                f"[RequestQueue] Text request processed: text='{parsed.text[:50] if parsed.text else 'EMPTY'}...', "
                f"files={len(all_files)}"
            )

            return parsed.text, all_files

    def get_pending_file_count(self, user_id: str) -> int:
        """获取用户缓存的文件数量"""
        self._clear_expired_files(user_id)
        return len(self._pending_files.get(user_id, []))

    def has_pending_files(self, user_id: str) -> bool:
        """检查用户是否有缓存的文件"""
        return self.get_pending_file_count(user_id) > 0


# 全局实例
request_queue = RequestQueue()
