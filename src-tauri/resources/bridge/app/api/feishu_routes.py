"""
飞书渠道路由

长连接模式下 webhook 端点已移除，事件通过 WebSocket 接收。
仅保留健康检查端点。
"""
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/feishu", tags=["Feishu"])


@router.get("/health")
async def feishu_health():
    """飞书渠道健康检查"""
    return {"status": "healthy", "channel": "feishu", "mode": "long_connection"}
