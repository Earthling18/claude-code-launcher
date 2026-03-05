"""
通道连接状态注册表

线程安全的单例，跟踪每个通道（飞书 WebSocket、企微 Bridge 等）的连接状态。
供 /health 端点和 Web UI 重启流程使用。
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ChannelStatus(Enum):
    DISABLED = "disabled"          # 未启用
    STARTING = "starting"          # 线程/进程已启动，连接中
    CONNECTED = "connected"        # 已连接
    DISCONNECTED = "disconnected"  # 断连
    ERROR = "error"                # 错误


@dataclass
class ChannelInfo:
    name: str
    status: ChannelStatus
    status_since: float = field(default_factory=time.time)
    error: str = ""
    managed: bool = True  # False = 外部进程（如 Bridge），不参与 all_ready() 判断


class ChannelStatusRegistry:
    """线程安全的通道状态注册表（单例）"""

    def __init__(self):
        self._channels: Dict[str, ChannelInfo] = {}
        self._lock = threading.Lock()

    def update(self, channel: str, status: ChannelStatus, error: str = "",
               managed: Optional[bool] = None):
        with self._lock:
            old = self._channels.get(channel)
            # 只在状态真正变化时更新 since 时间戳
            if old and old.status == status:
                if error != old.error:
                    old.error = error
                return
            # managed: 首次注册时设置，后续更新保留原值
            if managed is None:
                managed = old.managed if old else True
            self._channels[channel] = ChannelInfo(
                name=channel,
                status=status,
                status_since=time.time(),
                error=error,
                managed=managed,
            )
            logger.info(
                f"[CHANNEL] {channel}: "
                f"{old.status.value if old else 'N/A'} -> {status.value}"
                f"{f' ({error})' if error else ''}"
            )

    def get(self, channel: str) -> Optional[ChannelInfo]:
        with self._lock:
            return self._channels.get(channel)

    def get_all(self) -> Dict[str, ChannelInfo]:
        with self._lock:
            return dict(self._channels)

    def all_ready(self) -> bool:
        """所有已启用的自管理通道（managed=True 且非 DISABLED）都是 CONNECTED。
        外部通道（managed=False，如 Bridge）不参与判断。"""
        with self._lock:
            managed_enabled = [
                ch for ch in self._channels.values()
                if ch.managed and ch.status != ChannelStatus.DISABLED
            ]
            if not managed_enabled:
                return True
            return all(ch.status == ChannelStatus.CONNECTED for ch in managed_enabled)

    def to_dict(self) -> dict:
        """序列化为 API 响应格式"""
        with self._lock:
            result = {}
            for name, info in self._channels.items():
                result[name] = {
                    "status": info.status.value,
                    "since": info.status_since,
                    "managed": info.managed,
                }
                if info.error:
                    result[name]["error"] = info.error
            return result

    def reset(self):
        """清除所有状态（用于重启时）"""
        with self._lock:
            self._channels.clear()


# 全局单例
channel_registry = ChannelStatusRegistry()
