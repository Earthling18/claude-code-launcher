"""
用户模式管理 - Per-user 模式持久化

支持两种运行模式：
- auto（托管/全自动）：所有消息都回复
- semi（协作/半自动）：只在匹配到 Skill 时回复
"""
import json
import logging
from pathlib import Path
from threading import Lock

from app.config import settings

logger = logging.getLogger(__name__)


class AvatarModeManager:
    """
    用户模式管理器

    Per-user 模式存储在 workspace/avatar_modes.json。
    查询优先级：per-user 覆盖 > 全局默认值（settings.avatar_mode）。
    """

    MODES_FILE = Path("workspace/avatar_modes.json")
    VALID_MODES = {"auto", "semi"}

    def __init__(self):
        self._modes: dict[str, str] = {}
        self._lock = Lock()
        self._load()

    def _load(self):
        """从磁盘加载模式配置"""
        if self.MODES_FILE.exists():
            try:
                data = json.loads(self.MODES_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._modes = {
                        k: v for k, v in data.items()
                        if v in self.VALID_MODES
                    }
                    logger.info(f"[AVATAR] Loaded {len(self._modes)} user mode(s) from disk")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[AVATAR] Failed to load modes file: {e}")
                self._modes = {}
        else:
            logger.info("[AVATAR] No modes file found, using defaults")

    def _save(self):
        """持久化到磁盘"""
        try:
            self.MODES_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.MODES_FILE.write_text(
                json.dumps(self._modes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except IOError as e:
            logger.error(f"[AVATAR] Failed to save modes file: {e}")

    def get_mode(self, user_id: str) -> str:
        """
        获取用户模式

        优先级：per-user 覆盖 > 全局默认值
        """
        with self._lock:
            return self._modes.get(user_id, settings.avatar_mode)

    def set_mode(self, user_id: str, mode: str) -> str:
        """
        设置用户模式

        Args:
            user_id: 用户 ID
            mode: 'auto' 或 'semi'

        Returns:
            设置后的模式
        """
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode: {mode}, must be one of {self.VALID_MODES}")

        with self._lock:
            self._modes[user_id] = mode
            self._save()

        logger.info(f"[AVATAR] User {user_id}: mode set to '{mode}'")
        return mode

    def is_semi_auto(self, user_id: str) -> bool:
        """是否处于协作模式"""
        return self.get_mode(user_id) == "semi"

    def get_mode_display(self, user_id: str) -> str:
        """获取模式的中文显示名称"""
        mode = self.get_mode(user_id)
        if mode == "semi":
            return "协作（只在匹配到技能时回复）"
        return "托管（所有消息都会回复）"


# 全局实例
avatar_mode_manager = AvatarModeManager()
