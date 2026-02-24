"""
会话管理器
以 user_id 为主键管理用户会话，支持持久化
"""
import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def sanitize_path_component(s: str) -> str:
    """
    清理字符串中的非法路径字符，使其可以安全用作目录名

    Windows 非法字符: < > : " / \\ | ? *
    将这些字符替换为下划线
    """
    return re.sub(r'[<>:"/\\|?*]', '_', s)


@dataclass
class Session:
    """用户会话数据结构 - 以 user_id 为主键"""
    user_id: str  # 企微用户ID，唯一标识
    user_name: str  # 用户显示名称
    workspace: Path  # 用户工作目录
    claude_session_id: Optional[str] = None  # Claude SDK 内部 session_id
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    message_count: int = 0  # 消息计数
    # [DEPRECATED] 以下字段已迁移到 RequestQueue，保留以兼容旧的持久化数据
    pending_files: list = field(default_factory=list)  # 待处理的文件列表
    pending_files_time: Optional[float] = None  # 文件缓存时间戳
    downloading: bool = False  # 文件下载中标志（不再使用）

    def touch(self) -> None:
        """更新最后访问时间"""
        self.last_accessed = time.time()

    def is_expired(self, ttl: int) -> bool:
        """检查会话是否过期"""
        return time.time() - self.last_accessed > ttl

    def clear_expired_pending_files(self, timeout: int = 300) -> None:
        """
        [DEPRECATED] 清理超时的待处理文件
        已迁移到 RequestQueue，保留以兼容旧的持久化数据
        """
        if self.pending_files_time and time.time() - self.pending_files_time > timeout:
            logger.info(f"[SESSION] Clearing expired pending files for user {self.user_id}")
            self.pending_files = []
            self.pending_files_time = None

    def add_pending_files(self, files: list) -> None:
        """
        [DEPRECATED] 添加待处理文件
        已迁移到 RequestQueue，保留以兼容旧的持久化数据
        """
        if not self.pending_files:
            self.pending_files = []
        self.pending_files.extend(files)
        self.pending_files_time = time.time()
        logger.info(f"[SESSION] Added {len(files)} pending files for user {self.user_id}, total: {len(self.pending_files)}")

    def get_and_clear_pending_files(self) -> list:
        """
        [DEPRECATED] 获取并清空待处理文件
        已迁移到 RequestQueue，保留以兼容旧的持久化数据
        """
        files = self.pending_files.copy()
        self.pending_files = []
        self.pending_files_time = None
        if files:
            logger.info(f"[SESSION] Retrieved and cleared {len(files)} pending files for user {self.user_id}")
        return files

    def to_dict(self) -> dict:
        """转换为可序列化的字典"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "workspace": str(self.workspace),
            "claude_session_id": self.claude_session_id,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "message_count": self.message_count,
            "pending_files": self.pending_files,
            "pending_files_time": self.pending_files_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """从字典创建 Session 对象"""
        return cls(
            user_id=data["user_id"],
            user_name=data.get("user_name", ""),
            workspace=Path(data["workspace"]),
            claude_session_id=data.get("claude_session_id"),
            created_at=data.get("created_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            message_count=data.get("message_count", 0),
            pending_files=data.get("pending_files", []),
            pending_files_time=data.get("pending_files_time"),
        )


class SessionManager:
    """
    会话管理器
    - 以 user_id 为主键管理会话（每个用户一个持续的对话）
    - 每用户独立 workspace 目录
    - 支持 JSON 文件持久化
    - 支持 TTL 自动过期
    - 映射 Claude SDK 内部 session_id
    """

    def __init__(
        self,
        workspace_dir: Optional[Path] = None,
        ttl: Optional[int] = None,
    ):
        self.workspace_dir = workspace_dir or settings.workspace_path
        self.ttl = ttl or settings.session_ttl
        self.sessions: Dict[str, Session] = {}  # key = user_id
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._download_locks: Dict[str, asyncio.Lock] = {}  # 每个会话的下载锁

        # 持久化文件路径
        self.sessions_file = self.workspace_dir / "user_sessions.json"

        # 确保工作目录存在
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # 启动时加载持久化的会话
        self._load_sessions()

    def _load_sessions(self) -> None:
        """从文件加载会话数据"""
        if not self.sessions_file.exists():
            logger.info("No sessions file found, starting fresh")
            return

        try:
            data = json.loads(self.sessions_file.read_text(encoding="utf-8"))
            loaded_count = 0
            expired_count = 0

            for user_id, session_data in data.items():
                session = Session.from_dict(session_data)
                # 跳过过期的会话
                if session.is_expired(self.ttl):
                    expired_count += 1
                    continue
                self.sessions[user_id] = session
                loaded_count += 1

            logger.info(
                f"Loaded {loaded_count} sessions from file, "
                f"skipped {expired_count} expired sessions"
            )
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    def _save_sessions(self) -> None:
        """保存会话数据到文件"""
        try:
            data = {
                user_id: session.to_dict()
                for user_id, session in self.sessions.items()
            }
            self.sessions_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    async def start(self) -> None:
        """启动会话管理器，开始后台清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Session cleanup task started")

    async def stop(self) -> None:
        """停止会话管理器"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Session cleanup task stopped")

        # 停止时保存会话
        self._save_sessions()

    async def get_or_create(
        self,
        user_id: str,
        user_name: str = "",
        session_id: str = ""  # 保留参数以兼容旧调用，但不再使用
    ) -> Session:
        """
        获取或创建用户会话

        Args:
            user_id: 用户 ID（企微用户ID，作为主键）
            user_name: 用户显示名称
            session_id: Dify session_id（保留兼容，不再使用）

        Returns:
            Session 对象
        """
        async with self._lock:
            if user_id in self.sessions:
                session = self.sessions[user_id]
                session.touch()
                # 更新用户名（可能会变化）
                if user_name and session.user_name != user_name:
                    session.user_name = user_name
                self._save_sessions()
                return session

            # 创建新用户会话
            # 清理 user_id 中的非法路径字符（如群聊 ID 的 R:xxx 格式）
            safe_user_id = sanitize_path_component(user_id)
            workspace = self.workspace_dir / safe_user_id
            workspace.mkdir(parents=True, exist_ok=True)

            session = Session(
                user_id=user_id,
                user_name=user_name,
                workspace=workspace,
            )
            self.sessions[user_id] = session
            self._save_sessions()

            logger.info(f"Created session for user: {user_id}, workspace: {workspace}")
            return session

    async def get(self, user_id: str) -> Optional[Session]:
        """
        获取用户会话

        Args:
            user_id: 用户 ID

        Returns:
            Session 对象或 None
        """
        async with self._lock:
            session = self.sessions.get(user_id)
            if session:
                session.touch()
                self._save_sessions()
            return session

    async def update_claude_session(
        self, user_id: str, claude_session_id: str
    ) -> None:
        """
        更新 Claude SDK session_id

        Args:
            user_id: 用户 ID
            claude_session_id: Claude SDK 内部 session_id
        """
        async with self._lock:
            if user_id in self.sessions:
                self.sessions[user_id].claude_session_id = claude_session_id
                self.sessions[user_id].message_count += 1
                self._save_sessions()
                logger.debug(
                    f"Updated claude_session_id for user {user_id}: {claude_session_id}"
                )

    async def reset_session(self, user_id: str) -> bool:
        """
        重置用户会话（清空 claude_session_id，开始新对话）

        Args:
            user_id: 用户 ID

        Returns:
            是否成功重置
        """
        async with self._lock:
            if user_id in self.sessions:
                self.sessions[user_id].claude_session_id = None
                self.sessions[user_id].message_count = 0
                self._save_sessions()
                logger.info(f"Reset session for user: {user_id}")
                return True
            return False

    async def destroy(self, user_id: str) -> bool:
        """
        销毁用户会话及其工作目录

        Args:
            user_id: 用户 ID

        Returns:
            是否成功销毁
        """
        async with self._lock:
            session = self.sessions.pop(user_id, None)
            if session:
                # 删除工作目录
                if session.workspace.exists():
                    shutil.rmtree(session.workspace, ignore_errors=True)
                self._save_sessions()
                logger.info(f"Destroyed session for user: {user_id}")
                return True
            return False

    async def cleanup_expired(self) -> int:
        """
        清理过期会话

        Returns:
            清理的会话数量
        """
        expired_users = []

        async with self._lock:
            for user_id, session in list(self.sessions.items()):
                if session.is_expired(self.ttl):
                    expired_users.append(user_id)

        count = 0
        for user_id in expired_users:
            if await self.destroy(user_id):
                count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired sessions")

        return count

    async def _cleanup_loop(self) -> None:
        """后台清理循环"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    def get_session_info(self, user_id: str) -> Optional[dict]:
        """
        获取会话信息（用于 API 响应）

        Args:
            user_id: 用户 ID

        Returns:
            会话信息字典
        """
        session = self.sessions.get(user_id)
        if not session:
            return None

        return {
            "session_id": user_id,
            "user_id": session.user_id,
            "user_name": session.user_name,
            "workspace": str(session.workspace),
            "claude_session_id": session.claude_session_id,
            "created_at": session.created_at,
            "last_accessed": session.last_accessed,
            "message_count": session.message_count,
            "ttl_remaining": max(0, self.ttl - (time.time() - session.last_accessed)),
        }

    @property
    def active_session_count(self) -> int:
        """获取活跃会话数量"""
        return len(self.sessions)

    def get_download_lock(self, user_id: str) -> asyncio.Lock:
        """
        获取用户的下载锁（用于防止竞态条件）

        Args:
            user_id: 用户 ID

        Returns:
            该用户的异步锁
        """
        if user_id not in self._download_locks:
            self._download_locks[user_id] = asyncio.Lock()
        return self._download_locks[user_id]


# 全局会话管理器实例
session_manager = SessionManager()
