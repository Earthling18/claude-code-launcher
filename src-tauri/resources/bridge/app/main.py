"""
FastAPI 应用主入口
"""
import asyncio
import logging
import logging.handlers
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from app.config import settings

# ---- 日志配置（必须在业务模块 import 之前） ----
# 优先使用 data/logs/，支持 Embedded Python 打包模式
_project_root_dir = Path(__file__).parent.parent.resolve()
_data_dir = _project_root_dir / "data"
if _data_dir.exists() or not Path("logs").exists():
    log_dir = _data_dir / "logs"
else:
    log_dir = Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "service.log"

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 控制台输出
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=50*1024*1024, backupCount=3, encoding="utf-8"
        ),  # 文件输出（50MB 轮转，保留 3 个备份）
    ],
)

uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.handlers = logging.root.handlers

logger = logging.getLogger(__name__)
logger.info(f"Log file: {log_file.absolute()}")

# ---- 业务模块 import（agent_service 初始化依赖 logging） ----
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.api.v2_routes import router as v2_router
from app.api.config_routes import router as config_router
from app.core.session_manager import session_manager
from app.core.user_session import user_session_manager
from app.core.cron_service import cron_service

# ---- 模块来源诊断（更新后确认文件是否被替换） ----
from app.core import agent_service as _agent_svc_mod
logger.info(f"[STARTUP] agent_service loaded from: {_agent_svc_mod.__file__}")
logger.info(f"[STARTUP] agent_service build: {getattr(_agent_svc_mod, '_MODULE_BUILD', 'unknown')}")


# ---- SDK 预热状态 ----
_sdk_ready = False


def is_sdk_ready() -> bool:
    return _sdk_ready


async def _warmup_sdk():
    """启动时预热 SDK 连接，避免用户首条消息冷启动超时"""
    global _sdk_ready
    try:
        import app.config as config
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

        options_kwargs = {
            "model": settings.claude_model,
            "system_prompt": "warmup",
            "permission_mode": "bypassPermissions",
            "cwd": config.resolved_agent_root,
            "setting_sources": ["project", "local"],
        }
        resolved_cli = settings.resolve_cli_path()
        if resolved_cli:
            options_kwargs["cli_path"] = resolved_cli

        # --settings 内联覆盖（防止用户 ~/.claude/settings.json 干扰 apiUrl/model）
        from app.core.agent_service import agent_service
        settings_override = agent_service._build_settings_override()
        if settings_override:
            options_kwargs["settings"] = settings_override

        options = ClaudeAgentOptions(**options_kwargs)

        logger.info("[WARMUP] Starting SDK warmup...")
        client = ClaudeSDKClient(options=options)
        async with client:
            pass  # 建连成功即关闭
        logger.info("[WARMUP] SDK warmup complete")
    except Exception as e:
        logger.warning(f"[WARMUP] SDK warmup failed (non-blocking): {e}")
    finally:
        _sdk_ready = True  # 无论成功失败都标记完成，不阻塞业务


def _is_junction_or_symlink(path: Path) -> bool:
    """检测路径是否为 Junction 或 symlink

    Windows 上 Path.is_symlink() 不总能检测 Junction，补充 os.readlink() 检测。
    """
    if path.is_symlink():
        return True
    try:
        os.readlink(str(path))
        return True
    except (OSError, ValueError):
        return False


def _remove_junction(path: Path):
    """删除 Junction 或 symlink（Windows 用 rmdir，Unix 用 unlink）"""
    import platform as _platform
    if _platform.system() == "Windows":
        import subprocess
        subprocess.run(
            ["cmd", "/c", "rmdir", str(path)],
            check=True, capture_output=True,
        )
    else:
        path.unlink()


def _create_junction(link: Path, target: Path):
    """创建 Junction（Windows）或 symlink（Unix）"""
    import platform as _platform
    if _platform.system() == "Windows":
        import subprocess
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True,
        )
        logger.info(f"Created junction: {link} -> {target}")
    else:
        link.symlink_to(target)
        logger.info(f"Created symlink: {link} -> {target}")


def _init_agent_root():
    """
    初始化 Agent CWD 隔离目录

    将 SDK 会话存储到独立目录（默认 ~/.mobot-bridge-agent/），
    只 Junction .claude/skills/ 子目录（而非整个 .claude/），
    使 Skill 自动发现正常工作，同时确保 Agent 写入的
    settings.local.json 不会污染项目目录。

    架构：
      agent_root/.claude/              ← 真实目录
      agent_root/.claude/skills/       ← Junction → project/.claude/skills/
      agent_root/.claude/settings.*    ← Agent 独立文件，不影响项目

    注意：不复制 CLAUDE.md — setting_sources=["project"] 会从 cwd 读取
    CLAUDE.md 注入上下文，浪费 token 且是开发文档非 agent 所需，
    system_prompt 已通过 options.system_prompt 显式传入。
    """
    project_root = Path(__file__).parent.parent.resolve()

    # 解析目标路径
    if settings.agent_root:
        agent_dir = Path(settings.agent_root).expanduser().resolve()
    else:
        agent_dir = Path.home() / ".mobot-bridge-agent"

    logger.info(f"[AGENT_ROOT] === Skills-only Junction architecture (v2) ===")
    logger.info(f"[AGENT_ROOT] project_root = {project_root}")
    logger.info(f"[AGENT_ROOT] agent_dir    = {agent_dir}")

    try:
        agent_dir.mkdir(parents=True, exist_ok=True)

        claude_dir = agent_dir / ".claude"
        source_skills = project_root / ".claude" / "skills"

        # ── 旧架构迁移：如果 .claude 是 Junction/symlink → 删掉 ──
        if _is_junction_or_symlink(claude_dir):
            try:
                old_target = os.readlink(str(claude_dir))
            except (OSError, ValueError):
                old_target = "unknown"
            _remove_junction(claude_dir)
            logger.info(f"[AGENT_ROOT] MIGRATED old .claude junction (was -> {old_target})")
        else:
            if claude_dir.exists():
                logger.info(f"[AGENT_ROOT] .claude/ is real directory (OK, no migration needed)")
            else:
                logger.info(f"[AGENT_ROOT] .claude/ does not exist yet, will create")

        # ── 确保 .claude/ 作为真实目录存在 ──
        claude_dir.mkdir(parents=True, exist_ok=True)

        # ── 创建 skills Junction ──
        link_skills = claude_dir / "skills"

        if source_skills.exists():
            if _is_junction_or_symlink(link_skills):
                # 已存在，验证目标是否匹配
                try:
                    current_target = link_skills.resolve()
                    if current_target != source_skills.resolve():
                        _remove_junction(link_skills)
                        logger.info(
                            f"[AGENT_ROOT] Removed stale skills junction "
                            f"(was {current_target}, expected {source_skills.resolve()})"
                        )
                        _create_junction(link_skills, source_skills)
                    else:
                        logger.info(f"[AGENT_ROOT] skills junction already correct -> {source_skills}")
                except OSError:
                    # broken link → 删除重建
                    _remove_junction(link_skills)
                    _create_junction(link_skills, source_skills)
            elif link_skills.exists():
                # 是真实目录（不应该出现）→ 跳过，不破坏
                logger.warning(f"[AGENT_ROOT] skills/ is a real directory (not junction): {link_skills}")
            else:
                _create_junction(link_skills, source_skills)
        else:
            logger.warning(f"[AGENT_ROOT] Source skills/ not found: {source_skills}")

        # ── 清理项目污染：settings.local.json ──
        project_local_settings = project_root / ".claude" / "settings.local.json"
        if project_local_settings.exists():
            try:
                import json as _json
                data = _json.loads(project_local_settings.read_text(encoding="utf-8"))
                # 含 model 或 apiUrl 说明是 Agent 写入的污染文件
                if "model" in data or "apiUrl" in data:
                    logger.info(
                        f"[AGENT_ROOT] FOUND project contamination: {project_local_settings} "
                        f"content={_json.dumps(data, ensure_ascii=False)}"
                    )
                    project_local_settings.unlink()
                    logger.info(f"[AGENT_ROOT] DELETED contaminated {project_local_settings}")
                else:
                    logger.info(f"[AGENT_ROOT] project settings.local.json exists but no agent keys (OK)")
            except Exception as e:
                logger.warning(f"[AGENT_ROOT] Failed to check/clean project settings.local.json: {e}")
        else:
            logger.info(f"[AGENT_ROOT] No project settings.local.json (clean, OK)")

        import app.config as _config
        _config.resolved_agent_root = str(agent_dir)
        logger.info(f"[AGENT_ROOT] Agent root initialized: {agent_dir}")

    except Exception as e:
        # 失败时回退到项目根目录
        logger.warning(f"Failed to init agent root ({e}), falling back to project root")
        import app.config as _config
        _config.resolved_agent_root = str(project_root)


async def _auto_fix_bridge_config():
    """启动时自动修复 bridge config 中的占位符"""
    from app.services.config_manager import config_manager

    # 如果配置文件不存在，从模板创建
    if not config_manager.bridge_config_exists():
        from pathlib import Path
        import shutil

        project_root = Path(__file__).parent.parent.resolve()
        bridge_dir = project_root / "bridge"
        config_file = bridge_dir / "config.yaml"
        example_file = bridge_dir / "config.yaml.example"

        if example_file.exists():
            try:
                shutil.copy(example_file, config_file)
                logger.info(f"[BRIDGE] Created config.yaml from template: {config_file}")
            except Exception as e:
                logger.warning(f"[BRIDGE] Failed to create config.yaml from template: {e}")
                return
        else:
            logger.warning(f"[BRIDGE] Template file not found: {example_file}")
            return

    config = config_manager.read_bridge_config()
    client = config.get("client", {})
    changed = False

    # 修复 bind_key — 调 Bridge Server 自动生成（带重试）
    bind_key = client.get("bind_key", "")
    if "<YOUR_" in bind_key or not bind_key.strip():
        for attempt in range(2):
            try:
                import re
                import platform
                import httpx

                client_id = (client.get("client_id") or "").strip() or platform.node()
                name_match = re.match(r"([a-zA-Z]+)", client_id)
                user_id = name_match.group(1).lower() if name_match else client_id.lower()

                BRIDGE_SERVER = "http://172.21.11.82/key-bridge"
                ADMIN_TOKEN = "admin123"
                post_url = f"{BRIDGE_SERVER}/api/admin/users"
                logger.info(f"[BRIDGE] Requesting bind_key: POST {post_url} user_id={user_id}")
                async with httpx.AsyncClient(timeout=10) as http:
                    resp = await http.post(
                        post_url,
                        json={"user_id": user_id, "name": client_id},
                        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                    )
                    logger.info(f"[BRIDGE] POST response: {resp.status_code}")
                    if resp.status_code == 409:
                        get_url = f"{BRIDGE_SERVER}/api/admin/users/{user_id}"
                        logger.info(f"[BRIDGE] User exists, querying: GET {get_url}")
                        resp = await http.get(
                            get_url,
                            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                        )
                        logger.info(f"[BRIDGE] GET response: {resp.status_code}")
                    if resp.status_code == 200:
                        data = resp.json()
                        key = data.get("api_key") or data.get("key") or data.get("user", {}).get("api_key")
                        if key:
                            short_key = key[:10] + "..." if len(key) > 10 else key
                            client["bind_key"] = key
                            changed = True
                            logger.info(f"[BRIDGE] Auto-generated bind_key via Bridge Server: {short_key}")
                            break
                        else:
                            logger.warning(f"[BRIDGE] Bridge Server response missing api_key, keys={list(data.keys())}")
                    else:
                        logger.warning(f"[BRIDGE] Bridge Server returned {resp.status_code}: {resp.text[:200]}")
            except httpx.ConnectError as e:
                if attempt == 0:
                    logger.warning(f"[BRIDGE] Cannot connect to Bridge Server (attempt 1), retrying in 2s: {e}")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"[BRIDGE] Cannot connect to Bridge Server: {e}")
            except httpx.TimeoutException as e:
                if attempt == 0:
                    logger.warning(f"[BRIDGE] Bridge Server request timed out (attempt 1), retrying in 2s: {e}")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"[BRIDGE] Bridge Server request timed out: {e}")
            except Exception as e:
                if attempt == 0:
                    logger.info(f"[BRIDGE] bind_key generation attempt 1 failed, retrying in 2s: {e}")
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"[BRIDGE] Failed to auto-generate bind_key: {e}")

    # 修复 http_agent_url
    url = client.get("http_agent_url", "")
    if "<YOUR_" in url or not url.strip():
        client["http_agent_url"] = "http://127.0.0.1:8000/api/v2/chat"
        changed = True
        logger.info("[BRIDGE] Auto-fixed http_agent_url")

    # 修复 http_agent_key
    key = client.get("http_agent_key", "")
    if "<YOUR_" in key or not key.strip():
        try:
            from app.api.api_key_auth import load_api_keys, _key_store
            load_api_keys()
            enabled_keys = [k for k in _key_store.values() if k.enabled]
            if enabled_keys:
                client["http_agent_key"] = enabled_keys[0].key
                changed = True
                logger.info("[BRIDGE] Auto-fixed http_agent_key")
            else:
                logger.warning("[BRIDGE] No enabled API keys, cannot auto-fix http_agent_key")
        except Exception as e:
            logger.warning(f"[BRIDGE] Failed to auto-fix http_agent_key: {e}")

    # 确保 server_url 存在
    if not client.get("server_url"):
        client["server_url"] = "ws://172.21.11.82:80/bridge"
        changed = True
        logger.info("[BRIDGE] Auto-fixed server_url")

    # 确保 backend_type 存在
    if not client.get("backend_type"):
        client["backend_type"] = "http"
        changed = True
        logger.info("[BRIDGE] Auto-fixed backend_type")

    # 确保 http_agent_timeout 存在
    if not client.get("http_agent_timeout"):
        client["http_agent_timeout"] = 300
        changed = True
        logger.info("[BRIDGE] Auto-fixed http_agent_timeout")

    # 确保 reconnect_interval 存在
    if not client.get("reconnect_interval"):
        client["reconnect_interval"] = 5
        changed = True
        logger.info("[BRIDGE] Auto-fixed reconnect_interval")

    # 确保 heartbeat_interval 存在
    if not client.get("heartbeat_interval"):
        client["heartbeat_interval"] = 30
        changed = True
        logger.info("[BRIDGE] Auto-fixed heartbeat_interval")

    # 确保 client_id 字段存在（留空）
    if "client_id" not in client:
        client["client_id"] = ""
        changed = True
        logger.info("[BRIDGE] Auto-fixed client_id")

    if changed:
        config["client"] = client
        config_manager.write_bridge_config(config)
        logger.info("[BRIDGE] Wrote auto-fixed bridge/config.yaml")


def _is_bridge_effectively_configured() -> bool:
    """Bridge 配置是否有效：文件存在 + 关键字段非占位符"""
    from app.services.config_manager import config_manager
    if not config_manager.bridge_config_exists():
        return False
    config = config_manager.read_bridge_config()
    client = config.get("client", {})
    for val in (
        client.get("bind_key", ""),
        client.get("http_agent_url", ""),
        client.get("http_agent_key", ""),
    ):
        if not (val or "").strip() or "<YOUR_" in val:
            return False
    return True


async def _verify_feishu_connection() -> bool:
    """验证飞书连接是否真正可用（通过 API 获取 tenant_access_token）"""
    try:
        from app.channels.feishu.auth import feishu_auth
        token = await asyncio.wait_for(feishu_auth.get_token(), timeout=10)
        return bool(token)
    except Exception:
        return False


async def _channel_monitor(feishu_enabled: bool, bridge_enabled: bool):
    """后台任务：每 2 秒刷新通道连接状态"""
    import threading as _threading
    from app.core.channel_status import ChannelStatus, channel_registry

    while True:
        await asyncio.sleep(2)
        try:
            # ---- 飞书：检查线程存活 + API 验证 ----
            if feishu_enabled:
                alive = any(
                    t.name == "feishu-ws" and t.is_alive()
                    for t in _threading.enumerate()
                )
                current = channel_registry.get("feishu")
                if current:
                    if current.status == ChannelStatus.STARTING and not alive:
                        channel_registry.update(
                            "feishu", ChannelStatus.ERROR, "WS thread failed to start"
                        )
                    elif current.status == ChannelStatus.CONNECTED and not alive:
                        channel_registry.update(
                            "feishu", ChannelStatus.DISCONNECTED, "WS thread exited"
                        )
                    elif current.status == ChannelStatus.STARTING and alive:
                        from app.channels.feishu.ws_client import (
                            _lark_log_connected, _lark_import_done,
                        )
                        if _lark_log_connected:
                            # WS 已连接，API 验证确认
                            if await _verify_feishu_connection():
                                channel_registry.update("feishu", ChannelStatus.CONNECTED)
                                logger.info("[CHANNEL_MONITOR] Feishu verified via API (log signal)")
                        elif _lark_import_done:
                            # 模块加载完成，WS 连接中
                            channel_registry.update(
                                "feishu", ChannelStatus.STARTING,
                                error="Connecting WebSocket...",
                            )
                            # 45s fallback 仅在 import 完成后才允许
                            if time.time() - current.status_since > 45:
                                if await _verify_feishu_connection():
                                    channel_registry.update("feishu", ChannelStatus.CONNECTED)
                                    logger.info("[CHANNEL_MONITOR] Feishu verified via API (45s fallback)")
                        else:
                            # 模块加载中（冷启动）
                            channel_registry.update(
                                "feishu", ChannelStatus.STARTING,
                                error="Loading modules (first startup may take 3-5 min)",
                            )

            # ---- Bridge 动态发现 ----
            if not bridge_enabled:
                # 配置文件存在但启动时未就绪 → 定期重检
                # （Bridge Client 可能已自行注册并更新 config.yaml）
                if _is_bridge_effectively_configured():
                    bridge_enabled = True
                    channel_registry.update("wecom_bridge", ChannelStatus.STARTING, managed=False)
                    logger.info("[CHANNEL_MONITOR] Bridge config became valid, enabling detection")

            # ---- Bridge：通过 TCP 连接检测 ----
            if bridge_enabled:
                try:
                    from app.services.config_manager import config_manager
                    connected = config_manager._check_bridge_ws_connection()
                    current = channel_registry.get("wecom_bridge")
                    if connected:
                        channel_registry.update("wecom_bridge", ChannelStatus.CONNECTED)
                    elif current and current.status == ChannelStatus.CONNECTED:
                        channel_registry.update(
                            "wecom_bridge", ChannelStatus.DISCONNECTED, "TCP connection lost"
                        )
                    # 保持 STARTING 状态直到连接成功
                except Exception:
                    pass

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[CHANNEL_MONITOR] Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting application...")

    # 初始化 Agent CWD 隔离目录（必须在会话管理器启动前）
    _init_agent_root()

    # agent_root 初始化后，重写 settings.local.json 到正确路径并重新诊断
    from app.core.agent_service import agent_service
    agent_service._write_settings_overrides()
    agent_service.diagnose_isolation()

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

    # ---- 通道状态注册 & 启动 ----
    from app.core.channel_status import ChannelStatus, channel_registry

    # 飞书 WebSocket 长连接（需在主循环就绪后）
    if feishu_settings.enabled:
        channel_registry.update("feishu", ChannelStatus.STARTING)

        # 飞书域名加入 NO_PROXY（兜底，防止代理恢复后影响重连）
        _feishu_domains = "open.feishu.cn,open.larksuite.com,msg-frontier.feishu.cn"
        existing = os.environ.get("NO_PROXY", "")
        os.environ["NO_PROXY"] = f"{existing},{_feishu_domains}" if existing else _feishu_domains
        os.environ["no_proxy"] = os.environ["NO_PROXY"]

        from app.channels.feishu.ws_client import start as start_feishu_ws
        start_feishu_ws(asyncio.get_event_loop())
        logger.info("Feishu channel enabled (long connection mode)")
    else:
        if not feishu_settings.app_id and not feishu_settings.app_secret:
            logger.info("Feishu channel disabled (FEISHU_APP_ID and FEISHU_APP_SECRET not configured)")
        elif not feishu_settings.app_id:
            logger.warning("Feishu channel disabled (FEISHU_APP_ID is empty)")
        elif not feishu_settings.app_secret:
            logger.warning("Feishu channel disabled (FEISHU_APP_SECRET is empty)")

    # Bridge：启动时自动修复占位符（兜底）
    await _auto_fix_bridge_config()

    # Bridge 状态：配置文件存在 + 关键字段已填写才视为启用
    _bridge_enabled = _is_bridge_effectively_configured()
    if not _bridge_enabled:
        _has_bridge_file = Path("bridge/config.yaml").exists() or Path("data/bridge/config.yaml").exists()
        if _has_bridge_file:
            from app.services.config_manager import config_manager
            _diag = config_manager.read_bridge_config().get("client", {})
            _chk = lambda v: "SET" if (v or "").strip() and "<YOUR_" not in (v or "") else "MISSING"
            logger.info(f"[BRIDGE] Config diagnosis: bind_key={_chk(_diag.get('bind_key',''))}, "
                        f"http_agent_url={_chk(_diag.get('http_agent_url',''))}, "
                        f"http_agent_key={_chk(_diag.get('http_agent_key',''))}")
    if _bridge_enabled:
        channel_registry.update("wecom_bridge", ChannelStatus.STARTING, managed=False)

    # 启动通道状态监控后台任务
    monitor_task = asyncio.create_task(_channel_monitor(
        feishu_enabled=feishu_settings.enabled,
        bridge_enabled=_bridge_enabled,
    ))

    # 启动 SDK 预热（后台任务，不阻塞启动）
    warmup_task = asyncio.create_task(asyncio.wait_for(_warmup_sdk(), timeout=120))

    logger.info(f"Application started on {settings.host}:{settings.port}")
    logger.info(f"Immediate return mode: {settings.immediate_return_mode}")

    yield

    # 取消预热任务（如果仍在进行）
    if not warmup_task.done():
        warmup_task.cancel()

    # 取消监控任务
    monitor_task.cancel()

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

# 静态文件 Cache-Control：禁止浏览器缓存，确保代码更新后立即生效
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

app.add_middleware(NoCacheStaticMiddleware)

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
app.include_router(config_router)

# 条件注册飞书健康检查路由（WebSocket 长连接在 lifespan 中启动）
from app.config import feishu_settings
if feishu_settings.enabled:
    from app.api.feishu_routes import router as feishu_router
    app.include_router(feishu_router)

# 挂载静态文件（Web 配置 UI）
_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
    logger.info(f"Static files mounted from: {_static_dir}")
else:
    logger.error(f"Static directory NOT FOUND: {_static_dir}")

@app.get("/config")
@app.get("/config/")
async def config_ui(request: Request):
    """Serve the Web configuration UI directly."""
    index_file = _static_dir / "config" / "index.html"
    if index_file.exists():
        from fastapi.responses import HTMLResponse
        from app.core.updater import get_version
        ver = get_version()
        # If no version in query string, redirect to add it — ensures browser
        # fetches fresh JS/CSS even when served by old app.js (chicken-and-egg fix)
        if request.query_params.get("v") != ver:
            return RedirectResponse(url=f"/config?v={ver}")
        html = index_file.read_text(encoding="utf-8")
        # Inject version query string to bust browser cache
        html = html.replace('app.js"', f'app.js?v={ver}"')
        html = html.replace('style.css"', f'style.css?v={ver}"')
        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    return RedirectResponse(url="/static/config/index.html")


# 用于直接运行
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
