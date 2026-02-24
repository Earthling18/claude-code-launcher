"""
API Key 认证模块

从 api_keys.json 加载 API Key 配置，提供 FastAPI Depends 依赖。
Key 仅用于请求验证，不绑定 user_id。
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

API_KEYS_FILE = Path("api_keys.json")


@dataclass
class ApiKeyInfo:
    """API Key 信息"""
    key: str
    name: str
    enabled: bool


# 内存缓存：key -> ApiKeyInfo
_key_store: Dict[str, ApiKeyInfo] = {}


def load_api_keys() -> int:
    """从 api_keys.json 加载 API Key 到内存。"""
    global _key_store
    _key_store.clear()

    if not API_KEYS_FILE.exists():
        logger.warning(f"[API_KEY] Config file not found: {API_KEYS_FILE}")
        return 0

    try:
        data = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
        for item in data.get("keys", []):
            info = ApiKeyInfo(
                key=item["key"],
                name=item.get("name", ""),
                enabled=item.get("enabled", True),
            )
            _key_store[info.key] = info

        logger.info(f"[API_KEY] Loaded {len(_key_store)} API keys")
        return len(_key_store)
    except Exception as e:
        logger.error(f"[API_KEY] Failed to load api_keys.json: {e}")
        return 0


def reload_api_keys() -> int:
    """热重载 API Key 配置"""
    count = load_api_keys()
    logger.info(f"[API_KEY] Reloaded: {count} keys")
    return count


async def verify_api_key(
    authorization: Optional[str] = Header(None, description="Bearer API Key"),
) -> ApiKeyInfo:
    """
    FastAPI Depends 依赖：验证 Authorization Header。

    当没有配置 api_keys.json 时（桌面 Launcher 场景），跳过认证。

    Raises:
        HTTPException 401: 配置了 API Key 但提供的 key 无效或禁用
    """
    # 没有配置任何 API Key 时，跳过认证（桌面本地调用场景）
    if not _key_store:
        return ApiKeyInfo(key="", name="local", enabled=True)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")

    info = _key_store.get(token)
    if info is None or not info.enabled:
        logger.warning(f"[API_KEY] Rejected: {token[:10]}...")
        raise HTTPException(status_code=401, detail="Invalid or disabled API key")

    logger.info(f"[API_KEY] Authenticated: {info.name}")
    return info


# 启动时自动加载
load_api_keys()
