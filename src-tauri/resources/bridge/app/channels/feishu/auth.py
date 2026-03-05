"""
飞书 Token 管理

管理 tenant_access_token（2小时有效期，自动刷新）。
"""
import asyncio
import logging
import time

import httpx

from app.config import feishu_settings

logger = logging.getLogger(__name__)

# 飞书开放平台 API 基础地址
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


class FeishuAuth:
    """飞书认证管理器"""

    # token 提前 5 分钟刷新
    TOKEN_REFRESH_MARGIN = 300

    def __init__(self):
        self._token: str = ""
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """
        获取有效的 tenant_access_token

        过期前 5 分钟自动刷新，使用 asyncio.Lock 保证并发安全。

        Returns:
            有效的 tenant_access_token
        """
        if self._token and time.time() < self._expires_at - self.TOKEN_REFRESH_MARGIN:
            return self._token

        async with self._lock:
            # 双重检查：可能其他协程已刷新
            if self._token and time.time() < self._expires_at - self.TOKEN_REFRESH_MARGIN:
                return self._token

            await self._refresh_token()
            return self._token

    async def _refresh_token(self):
        """请求新的 tenant_access_token"""
        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": feishu_settings.app_id,
            "app_secret": feishu_settings.app_secret,
        }

        try:
            async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

            if data.get("code") != 0:
                raise Exception(f"Feishu token error: {data.get('msg', 'unknown')}")

            self._token = data["tenant_access_token"]
            expire_seconds = data.get("expire", 7200)
            self._expires_at = time.time() + expire_seconds
            logger.info(f"[FEISHU_AUTH] Token refreshed, expires in {expire_seconds}s")

        except Exception as e:
            logger.error(f"[FEISHU_AUTH] Failed to refresh token ({type(e).__name__}): {e}")
            raise


# 全局实例
feishu_auth = FeishuAuth()
