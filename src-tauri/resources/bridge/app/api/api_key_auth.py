"""
API Key 认证模块

从 api_keys.json 加载 API Key 配置，提供 FastAPI Depends 依赖。
Key 仅用于请求验证，不绑定 user_id。
"""
import json
import logging
import secrets
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


def _generate_api_key() -> str:
    """Generate a random API key with ak- prefix."""
    return f"ak-{secrets.token_hex(20)}"


def _save_api_keys():
    """Persist current _key_store to api_keys.json."""
    data = {
        "keys": [
            {"key": info.key, "name": info.name, "enabled": info.enabled}
            for info in _key_store.values()
        ]
    }
    API_KEYS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_api_keys() -> int:
    """从 api_keys.json 加载 API Key 到内存。"""
    global _key_store
    _key_store.clear()

    if API_KEYS_FILE.exists():
        try:
            data = json.loads(API_KEYS_FILE.read_text(encoding="utf-8"))
            for item in data.get("keys", []):
                info = ApiKeyInfo(
                    key=item["key"],
                    name=item.get("name", ""),
                    enabled=item.get("enabled", True),
                )
                _key_store[info.key] = info
        except Exception as e:
            logger.error(f"[API_KEY] Failed to load api_keys.json: {e}")

    # Auto-generate a default key if none exist
    if not _key_store:
        new_key = _generate_api_key()
        info = ApiKeyInfo(key=new_key, name="default", enabled=True)
        _key_store[new_key] = info
        _save_api_keys()
        logger.info("[API_KEY] Auto-generated default API key")

    logger.info(f"[API_KEY] Loaded {len(_key_store)} API keys")
    return len(_key_store)


def reload_api_keys() -> int:
    """热重载 API Key 配置"""
    count = load_api_keys()
    logger.info(f"[API_KEY] Reloaded: {count} keys")
    return count


async def verify_api_key(
    authorization: str = Header(..., description="Bearer API Key"),
) -> ApiKeyInfo:
    """
    FastAPI Depends 依赖：验证 Authorization Header。

    Raises:
        HTTPException 401: 无效或禁用的 API Key
    """
    if not authorization.startswith("Bearer "):
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
