"""
输出文件注册表 - 追踪 Agent 指定返回的文件

核心机制：
1. Agent 通过 MCP 工具调用 return_file_to_user 注册文件
2. SDK 完成后，从注册表获取文件列表
3. 只上传和返回注册的文件（过滤中间过程文件）
"""
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class OutputFileEntry:
    """输出文件条目"""
    file_path: str  # 相对于 workspace 的路径
    description: str = ""  # 文件描述（可选）
    timestamp: float = field(default_factory=time.time)
    absolute_path: Optional[str] = None  # 绝对路径（运行时填充）


class OutputFileRegistry:
    """
    Per-session 输出文件注册表

    线程安全：使用 threading.Lock 保护内部数据结构
    （MCP 工具可能从不同线程调用）
    """

    def __init__(self):
        self._registry: Dict[str, List[OutputFileEntry]] = {}
        self._lock = threading.Lock()

    def add(
        self,
        session_id: str,
        file_path: str,
        description: str = "",
        workspace: Optional[Path] = None,
    ) -> bool:
        """
        注册输出文件

        Args:
            session_id: 会话 ID（user_id）
            file_path: 文件路径（相对于 workspace 或绝对路径）
            description: 文件描述
            workspace: 工作目录（用于解析绝对路径）

        Returns:
            是否成功注册
        """
        with self._lock:
            if session_id not in self._registry:
                self._registry[session_id] = []

            # 检查是否已注册
            for entry in self._registry[session_id]:
                if entry.file_path == file_path:
                    logger.info(f"[OutputRegistry] File already registered: {file_path}")
                    return True

            # 解析绝对路径
            absolute_path = None
            if workspace:
                path = Path(file_path)
                if path.is_absolute():
                    absolute_path = str(path)
                else:
                    absolute_path = str(workspace / file_path)

            entry = OutputFileEntry(
                file_path=file_path,
                description=description,
                absolute_path=absolute_path,
            )
            self._registry[session_id].append(entry)

            logger.info(
                f"[OutputRegistry] Registered file: session={session_id}, "
                f"path={file_path}, desc='{description}'"
            )
            return True

    def get_files(self, session_id: str) -> List[OutputFileEntry]:
        """
        获取会话的所有注册文件（不清空）

        Args:
            session_id: 会话 ID

        Returns:
            文件列表
        """
        with self._lock:
            return list(self._registry.get(session_id, []))

    def get_and_clear(self, session_id: str) -> List[OutputFileEntry]:
        """
        获取并清空会话的注册文件

        Args:
            session_id: 会话 ID

        Returns:
            文件列表
        """
        with self._lock:
            files = self._registry.pop(session_id, [])
            if files:
                logger.info(
                    f"[OutputRegistry] Retrieved and cleared {len(files)} files "
                    f"for session {session_id}"
                )
            return files

    def clear(self, session_id: str) -> int:
        """
        清空会话的注册文件

        Args:
            session_id: 会话 ID

        Returns:
            清空的文件数量
        """
        with self._lock:
            files = self._registry.pop(session_id, [])
            return len(files)

    def has_files(self, session_id: str) -> bool:
        """检查会话是否有注册的文件"""
        with self._lock:
            return bool(self._registry.get(session_id))

    def count(self, session_id: str) -> int:
        """获取会话注册的文件数量"""
        with self._lock:
            return len(self._registry.get(session_id, []))

    def cleanup_expired(self, max_age_seconds: float = None) -> int:
        """
        清理过期的注册文件

        Args:
            max_age_seconds: 最大存活时间（默认使用配置）

        Returns:
            清理的会话数量
        """
        if max_age_seconds is None:
            max_age_seconds = settings.file_cache_timeout_seconds

        now = time.time()
        cleaned = 0

        with self._lock:
            expired_sessions = []
            for session_id, files in self._registry.items():
                # 如果所有文件都过期，清理整个会话
                if all(now - f.timestamp > max_age_seconds for f in files):
                    expired_sessions.append(session_id)

            for session_id in expired_sessions:
                del self._registry[session_id]
                cleaned += 1

        if cleaned:
            logger.info(f"[OutputRegistry] Cleaned up {cleaned} expired sessions")

        return cleaned


# 全局实例
output_registry = OutputFileRegistry()


# 上下文变量，用于在 MCP 工具中访问当前会话信息
# 这些变量在处理请求时设置，在 MCP 工具中读取
_current_session_id: Optional[str] = None
_current_workspace: Optional[Path] = None


def set_current_context(session_id: str, workspace: Path) -> None:
    """设置当前请求上下文（在处理请求开始时调用）"""
    global _current_session_id, _current_workspace
    _current_session_id = session_id
    _current_workspace = workspace
    logger.debug(f"[OutputRegistry] Set context: session={session_id}, workspace={workspace}")


def clear_current_context() -> None:
    """清除当前请求上下文（在处理请求结束时调用）"""
    global _current_session_id, _current_workspace
    _current_session_id = None
    _current_workspace = None


def get_current_session_id() -> Optional[str]:
    """获取当前会话 ID"""
    return _current_session_id


def get_current_workspace() -> Optional[Path]:
    """获取当前工作目录"""
    return _current_workspace


def register_output_file(file_path: str, description: str = "") -> bool:
    """
    便捷函数：在当前上下文中注册输出文件

    用于 MCP 工具调用
    """
    session_id = get_current_session_id()
    workspace = get_current_workspace()

    if not session_id:
        logger.error("[OutputRegistry] Cannot register file: no current session")
        return False

    return output_registry.add(
        session_id=session_id,
        file_path=file_path,
        description=description,
        workspace=workspace,
    )
