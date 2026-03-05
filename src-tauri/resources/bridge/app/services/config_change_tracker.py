class ConfigChangeTracker:
    """配置变更追踪器（单例模式）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._has_changes = False
            cls._instance._changed_categories = set()
        return cls._instance

    def mark_changed(self, category: str):
        """标记某类配置已变更"""
        self._has_changes = True
        self._changed_categories.add(category)

    def clear(self):
        """清空变更标记（重启后调用）"""
        self._has_changes = False
        self._changed_categories.clear()

    def get_status(self) -> dict:
        return {
            "has_changes": self._has_changes,
            "categories": list(self._changed_categories),
        }


# 全局单例
tracker = ConfigChangeTracker()
