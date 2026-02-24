"""
FastAPI 应用主入口
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.routes import router
from app.api.v2_routes import router as v2_router
from app.core.session_manager import session_manager
from app.core.user_session import user_session_manager
from app.core.cron_service import cron_service

# 配置日志 - 同时输出到文件和控制台
import os
from pathlib import Path

# 创建日志目录
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "service.log"

# 配置根日志器
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 控制台输出
        logging.FileHandler(log_file, encoding="utf-8"),  # 文件输出
    ],
)

# 同时配置 uvicorn 的日志
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.handlers = logging.root.handlers

logger = logging.getLogger(__name__)
logger.info(f"Log file: {log_file.absolute()}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting application...")

    # 技能加载由 SDK 自动完成（从 .claude/skills/ 目录）
    logger.info("Skills will be loaded dynamically by Claude Agent SDK")

    # 启动会话管理器
    await session_manager.start()
    logger.info("Session manager started")

    # 启动用户会话管理器（全异步模式）
    await user_session_manager.start()
    logger.info("User session manager started")

    # 启动定时任务服务
    cron_service.start()
    logger.info("Cron service started")

    logger.info(f"Application started on {settings.host}:{settings.port}")
    logger.info(f"Immediate return mode: {settings.immediate_return_mode}")
    logger.info(f"[CONFIG] auth_mode={settings.claude_auth_mode}, model={settings.claude_model or 'EMPTY'}, base_url={settings.claude_api_base or 'EMPTY'}, api_key={'SET' if settings.claude_api_key else 'EMPTY'}")
    logger.info(f"[PROXY] WECOM_HTTP_PROXY={settings.http_proxy or 'EMPTY'} (os HTTP_PROXY deliberately cleared)")

    yield

    # 关闭时
    logger.info("Shutting down application...")

    # 停止定时任务服务
    cron_service.stop()
    logger.info("Cron service stopped")

    # 停止用户会话管理器
    await user_session_manager.stop()
    logger.info("User session manager stopped")

    # 停止会话管理器
    await session_manager.stop()
    logger.info("Session manager stopped")

    logger.info("Application shutdown complete")


# 创建 FastAPI 应用
app = FastAPI(
    title="企业微信数字分身后端服务",
    description="基于 Claude Agent SDK 的智能办公助手 API",
    version="1.0.0",
    lifespan=lifespan,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求验证错误处理 - 记录详细错误
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    body = await request.body()
    logger.error(f"Validation error: {exc.errors()}")
    logger.error(f"Request body: {body.decode('utf-8', errors='ignore')}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body.decode('utf-8', errors='ignore')[:500]}
    )

# 注册路由
app.include_router(router)
app.include_router(v2_router)


# 用于直接运行
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
