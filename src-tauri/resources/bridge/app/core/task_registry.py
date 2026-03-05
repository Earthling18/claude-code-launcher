"""
后台任务注册表

管理所有后台委托任务的生命周期和状态。
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    task_id: str
    user_id: str
    task_type: str              # 自由文本，如 "notebooklm" | "deep-research" | "code-analysis" 等
    description: str            # 用户可读的任务描述
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result_summary: Optional[str] = None
    error: Optional[str] = None
    progress_snapshot: Optional[str] = None  # Worker 最新进度文本（150字）
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)

    @property
    def elapsed_seconds(self) -> float:
        end = self.completed_at or time.time()
        return end - self.created_at


class TaskRegistry:
    """后台任务注册表，管理所有用户的后台任务"""

    MAX_HISTORY_PER_USER = 10

    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._counter = 0

    def generate_task_id(self, user_id: str) -> str:
        """生成唯一任务 ID"""
        self._counter += 1
        return f"task-{self._counter}"

    def register(self, task: BackgroundTask):
        """注册新任务"""
        self._tasks[task.task_id] = task
        logger.info(f"[TASK_REG] Registered task {task.task_id}: {task.task_type} - {task.description[:60]}")

        # 清理旧任务（保留最近 N 条已完成的）
        self._cleanup_old_tasks(task.user_id)

    def get(self, task_id: str) -> Optional[BackgroundTask]:
        """获取任务"""
        return self._tasks.get(task_id)

    def get_user_tasks(self, user_id: str, active_only: bool = False) -> List[BackgroundTask]:
        """获取用户的所有任务"""
        tasks = [t for t in self._tasks.values() if t.user_id == user_id]
        if active_only:
            tasks = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def complete(self, task_id: str, summary: str):
        """标记任务完成"""
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result_summary = summary
            logger.info(f"[TASK_REG] Task {task_id} completed ({task.elapsed_seconds:.0f}s): {summary[:100]}")

    def fail(self, task_id: str, error: str):
        """标记任务失败"""
        task = self._tasks.get(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            task.error = error
            logger.error(f"[TASK_REG] Task {task_id} failed: {error[:200]}")

    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return False

        # 取消 asyncio.Task
        if task._asyncio_task and not task._asyncio_task.done():
            task._asyncio_task.cancel()

        task.status = TaskStatus.CANCELLED
        task.completed_at = time.time()
        logger.info(f"[TASK_REG] Task {task_id} cancelled")
        return True

    def format_status_for_prompt(self, user_id: str) -> str:
        """生成可注入到 prompt 的任务状态文本（极简模式，仅计数+类型）

        已完成任务不再展示：Worker 通知已单独注入主会话，Claude 上下文中已有完整信息。
        """
        active = self.get_user_tasks(user_id, active_only=True)

        if not active:
            return ""

        count = len(active)
        types = "、".join(set(t.task_type for t in active))
        return f"[{count}个任务处理中: {types}]"

    def _cleanup_old_tasks(self, user_id: str):
        """清理用户的旧任务记录，保留最近 N 条"""
        user_tasks = [
            t for t in self._tasks.values()
            if t.user_id == user_id and t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        user_tasks.sort(key=lambda t: t.created_at, reverse=True)

        # 删除超出限制的旧任务
        for old_task in user_tasks[self.MAX_HISTORY_PER_USER:]:
            del self._tasks[old_task.task_id]


# 全局实例
task_registry = TaskRegistry()
