"""
数据看板 API 路由

提供看板 HTML 页面和 JSON 数据端点。
"""
import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.metrics_collector import metrics_collector

logger = logging.getLogger(__name__)

metrics_router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

DASHBOARD_HTML = Path(__file__).parent.parent / "static" / "dashboard.html"


@metrics_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """看板页面"""
    if not DASHBOARD_HTML.exists():
        return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)
    return HTMLResponse(DASHBOARD_HTML.read_text(encoding="utf-8"))


@metrics_router.get("/overview")
async def overview():
    """今日 + 近7天概览"""
    data = await metrics_collector.get_overview()
    return JSONResponse(data)


@metrics_router.get("/timeline")
async def timeline():
    """近7天每日趋势"""
    data = await metrics_collector.get_timeline()
    return JSONResponse(data)


@metrics_router.get("/users/top")
async def top_users():
    """近7天活跃用户 Top5"""
    data = await metrics_collector.get_top_users()
    return JSONResponse(data)


@metrics_router.get("/skills/stats")
async def skill_stats():
    """近7天技能排行"""
    data = await metrics_collector.get_skill_stats()
    return JSONResponse(data)


@metrics_router.get("/hourly")
async def hourly_distribution():
    """近7天每小时请求分布"""
    data = await metrics_collector.get_hourly_distribution()
    return JSONResponse(data)


@metrics_router.get("/requests/recent")
async def recent_requests():
    """最近20条请求"""
    data = await metrics_collector.get_recent_requests()
    return JSONResponse(data)
