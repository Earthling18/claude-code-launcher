"""
Web configuration API routes.

Provides REST endpoints for managing .env, bridge/config.yaml,
soul.md, skills, service status, and OAuth status.
"""

import logging
import os
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services.config_manager import config_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["Configuration"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class EnvResponse(BaseModel):
    """Response for GET /env."""
    env: Dict[str, str] = Field(default_factory=dict)
    exists: bool = True


class EnvUpdateRequest(BaseModel):
    """Request for POST /env."""
    env: Dict[str, str] = Field(..., description="Key-value pairs to set in .env")


class BridgeConfigResponse(BaseModel):
    """Response for GET /bridge."""
    config: Dict[str, Any] = Field(default_factory=dict)
    exists: bool = True


class BridgeConfigUpdateRequest(BaseModel):
    """Request for POST /bridge."""
    config: Dict[str, Any] = Field(..., description="Full bridge config.yaml content")


class SoulResponse(BaseModel):
    """Response for GET /soul."""
    content: str = ""
    exists: bool = True


class SoulUpdateRequest(BaseModel):
    """Request for POST /soul."""
    content: str = Field(..., description="Soul prompt markdown content")


class SkillItem(BaseModel):
    """A single skill entry."""
    id: str = ""
    name: str = ""
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    content: str = ""


class SkillsResponse(BaseModel):
    """Response for GET /skills."""
    skills: List[SkillItem] = Field(default_factory=list)
    count: int = 0


class ServiceDetail(BaseModel):
    """Detailed service status."""
    status: str  # 'running', 'stopped', 'unknown'
    pid: Optional[int] = None
    uptime: str = "-"
    start_time: Optional[int] = None  # Unix timestamp
    channel_status: Optional[str] = None  # channel_registry 状态: connected, starting, etc.

class ServiceStatusResponse(BaseModel):
    """Response for GET /services/status.

    Returns detailed service status information.
    """
    services: Dict[str, Union[str, ServiceDetail]] = Field(default_factory=dict)
    any_online: bool = False  # True if any service is running


class ServiceActionRequest(BaseModel):
    """Request for POST /services/{action}."""
    service: str = Field("all", description="Service to act on: main, agent, bridge, feishu, or all")


class OAuthStatusResponse(BaseModel):
    """Response for GET /oauth/status."""
    auth_mode: str = ""
    valid: bool = False
    error: str = ""
    expires_at: int = 0


class WhitelistResponse(BaseModel):
    """Response for GET /whitelist."""
    user_whitelist: str = ""
    admin_whitelist: str = ""
    feishu_user_whitelist: str = ""


class WhitelistUpdateRequest(BaseModel):
    """Request for POST /whitelist."""
    user_whitelist: str = Field("", description="Comma-separated user IDs")
    admin_whitelist: str = Field("", description="Comma-separated admin user IDs (wecom: user_name, feishu: user_id)")
    feishu_user_whitelist: str = Field("", description="Comma-separated Feishu open_ids")


class LogsResponse(BaseModel):
    """Response for GET /logs."""
    content: str = ""
    lines: int = 0


class GenericResponse(BaseModel):
    """Generic success/failure response."""
    success: bool
    message: str = ""


class CronJobItem(BaseModel):
    """A single cron job entry for the UI."""
    id: str
    cron: str
    cron_desc: str
    task_type: str  # "message" | "skill" | "command"
    task_content: str
    target: str
    context_type: str
    owner_name: str
    created_at: Optional[str] = None
    enabled: bool
    delete_after_run: bool
    next_run_time: Optional[str] = None


class CronJobsResponse(BaseModel):
    """Response for GET /cron/jobs."""
    jobs: List[CronJobItem]


# ---------------------------------------------------------------------------
# .env endpoints
# ---------------------------------------------------------------------------

@router.get("/env", response_model=EnvResponse)
async def get_env():
    """Read all environment variables from .env file."""
    data = config_manager.read_env()
    return EnvResponse(
        env=data,
        exists=config_manager.env_exists(),
    )


@router.post("/env", response_model=GenericResponse)
async def update_env(req: EnvUpdateRequest):
    """Update .env file with provided key-value pairs.

    Only the specified keys are updated; other keys are preserved.
    """
    try:
        config_manager.write_env(req.env)

        # 追踪配置变更
        from app.services.config_change_tracker import tracker
        tracker.mark_changed("model")

        return GenericResponse(success=True, message=f"Updated {len(req.env)} keys")
    except Exception as e:
        logger.error(f"[CONFIG] Failed to update .env: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# bridge/config.yaml endpoints
# ---------------------------------------------------------------------------

def _auto_fill_agent_key(data: Dict[str, Any]) -> Dict[str, Any]:
    """Fill http_agent_key from _key_store if empty."""
    client = data.get("client", {})
    if not client.get("http_agent_key"):
        from app.api.api_key_auth import _key_store
        enabled_keys = [k for k in _key_store.values() if k.enabled]
        if enabled_keys:
            client["http_agent_key"] = enabled_keys[0].key
            data["client"] = client
    return data


@router.get("/bridge", response_model=BridgeConfigResponse)
async def get_bridge_config():
    """Read bridge/config.yaml."""
    data = config_manager.read_bridge_config()
    data = _auto_fill_agent_key(data)
    return BridgeConfigResponse(
        config=data,
        exists=config_manager.bridge_config_exists(),
    )


@router.post("/bridge", response_model=GenericResponse)
async def update_bridge_config(req: BridgeConfigUpdateRequest):
    """Write bridge/config.yaml (full replace)."""
    try:
        data = _auto_fill_agent_key(req.config)
        config_manager.write_bridge_config(data)

        # 追踪配置变更
        from app.services.config_change_tracker import tracker
        tracker.mark_changed("bridge")

        return GenericResponse(success=True, message="Bridge config updated")
    except Exception as e:
        logger.error(f"[CONFIG] Failed to update bridge config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Bridge bind-key endpoints
# ---------------------------------------------------------------------------

@router.get("/bridge/bind-key-status")
async def get_bind_key_status():
    """Check whether a bind key exists and return the avatar command."""
    bridge_config = config_manager.read_bridge_config()
    client = bridge_config.get("client", {})
    bind_key = (client.get("bind_key") or "").strip()
    client_id = (client.get("client_id") or "").strip() or platform.node()
    has_key = bool(bind_key) and not bind_key.startswith("<")

    command = ""
    if has_key:
        command = f"/变身 bridge:{client_id}:{bind_key}"

    return {
        "has_key": has_key,
        "client_id": client_id,
        "bind_key": bind_key if has_key else "",
        "command": command,
    }


@router.post("/bridge/generate-bind-key")
async def generate_bind_key():
    """Generate a bind key via Bridge Server API and save to config.yaml."""
    import httpx

    BRIDGE_SERVER = "http://172.21.11.82/key-bridge"
    ADMIN_TOKEN = "admin123"

    # Read current bridge config
    bridge_config = config_manager.read_bridge_config()
    client = bridge_config.get("client", {})
    client_id = (client.get("client_id") or "").strip() or platform.node()

    # Extract English name prefix from hostname (e.g. "YANBINMO01" -> "yanbinmo")
    import re
    name_match = re.match(r"([a-zA-Z]+)", client_id)
    user_id = name_match.group(1).lower() if name_match else client_id.lower()
    name = client_id

    # Call Bridge Server admin API
    post_url = f"{BRIDGE_SERVER}/api/admin/users"
    logger.info(f"[BIND_KEY] Requesting: POST {post_url} user_id={user_id}")
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                post_url,
                json={"user_id": user_id, "name": name},
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            )
            logger.info(f"[BIND_KEY] POST response: {resp.status_code}")
            if resp.status_code == 409:
                # User already exists, query existing api_key
                get_url = f"{BRIDGE_SERVER}/api/admin/users/{user_id}"
                logger.info(f"[BIND_KEY] User exists, querying: GET {get_url}")
                get_resp = await http.get(
                    get_url,
                    headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                )
                logger.info(f"[BIND_KEY] GET response: {get_resp.status_code}")
                if get_resp.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"User exists but failed to retrieve key: {get_resp.status_code}")
                resp = get_resp
    except httpx.ConnectError as e:
        logger.error(f"[BIND_KEY] Cannot connect to Bridge Server {BRIDGE_SERVER}: {e}")
        raise HTTPException(status_code=502, detail=f"Cannot connect to Bridge Server: {e}")
    except httpx.TimeoutException as e:
        logger.error(f"[BIND_KEY] Bridge Server request timed out: {e}")
        raise HTTPException(status_code=504, detail="Bridge Server request timed out")
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Bridge Server returned {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    api_key = data.get("api_key") or data.get("key") or data.get("user", {}).get("api_key")
    if not api_key:
        raise HTTPException(status_code=502, detail="Bridge Server response missing api_key")

    # Update bind_key and auto-fill other required fields
    bridge_config.setdefault("client", {})
    bridge_config["client"]["bind_key"] = api_key

    # Auto-fill http_agent_url (fixed value for same-machine deployment)
    cur_url = bridge_config["client"].get("http_agent_url", "")
    if not cur_url.strip() or "<YOUR_" in cur_url:
        bridge_config["client"]["http_agent_url"] = "http://127.0.0.1:8000/api/v2/chat"

    # Auto-fill http_agent_key from existing API keys
    cur_key = bridge_config["client"].get("http_agent_key", "")
    if "<YOUR_" in cur_key:
        bridge_config["client"]["http_agent_key"] = ""  # clear placeholder so _auto_fill works
    bridge_config = _auto_fill_agent_key(bridge_config)

    # Ensure server_url is present
    if not bridge_config["client"].get("server_url"):
        bridge_config["client"]["server_url"] = "ws://172.21.11.82:80/bridge"

    config_manager.write_bridge_config(bridge_config)

    command = f"/变身 bridge:{client_id}:{api_key}"

    return {
        "success": True,
        "bind_key": api_key,
        "client_id": client_id,
        "command": command,
        "message": "Bind key generated and saved to bridge/config.yaml",
    }


# ---------------------------------------------------------------------------
# soul.md endpoints
# ---------------------------------------------------------------------------

@router.get("/soul", response_model=SoulResponse)
async def get_soul():
    """Read soul.md (identity/personality prompt)."""
    content = config_manager.read_soul()
    return SoulResponse(
        content=content,
        exists=config_manager.soul_exists(),
    )


@router.post("/soul", response_model=GenericResponse)
async def update_soul(req: SoulUpdateRequest):
    """Write soul.md content."""
    try:
        config_manager.write_soul(req.content)
        return GenericResponse(success=True, message="Soul prompt updated")
    except Exception as e:
        logger.error(f"[CONFIG] Failed to update soul: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Skills endpoints
# ---------------------------------------------------------------------------

@router.get("/skills", response_model=SkillsResponse)
async def get_skills():
    """List all skills."""
    skills_raw = config_manager.list_skills()
    skills = [
        SkillItem(id=s["name"], **s)
        for s in skills_raw
    ]
    return SkillsResponse(skills=skills, count=len(skills))


@router.post("/skills", response_model=GenericResponse)
async def upload_skill(
    files: List[UploadFile] = File(...),
    skill_name: str = Form(...),
):
    """Upload a skill directory (multipart/form-data).

    Accepts multiple files with their relative paths (from webkitdirectory).
    The skill_name form field provides the skill directory name.
    """
    try:
        config_manager.write_skill_from_upload(skill_name, files)
        return GenericResponse(success=True, message=f"Skill '{skill_name}' uploaded")
    except Exception as e:
        logger.error(f"[CONFIG] Failed to upload skill: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/skills/{skill_name}", response_model=GenericResponse)
async def delete_skill(skill_name: str):
    """Delete a skill by name."""
    ok = config_manager.delete_skill(skill_name)
    if ok:
        return GenericResponse(success=True, message=f"Skill '{skill_name}' deleted")
    raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")


# ---------------------------------------------------------------------------
# Service status / management endpoints
# ---------------------------------------------------------------------------

def _status_string(running: bool) -> str:
    """Convert boolean running state to status string."""
    return "running" if running else "stopped"


@router.get("/services/status", response_model=ServiceStatusResponse)
async def get_service_status():
    """Get running status of all services.

    Returns detailed service status information including pid, uptime, and start_time.
    """
    status = config_manager.get_service_status()

    # Inject channel_registry status for bridge/feishu
    from app.core.channel_status import channel_registry
    ch_all = channel_registry.to_dict()

    # Return detailed status information
    services = {}
    channel_key_map = {"bridge": "wecom_bridge", "feishu": "feishu"}
    for key, service_key in [("main", "agent"), ("bridge", "bridge"), ("feishu", "feishu")]:
        svc = status.get(service_key, {})
        ch_status = None
        if key in channel_key_map and channel_key_map[key] in ch_all:
            ch_status = ch_all[channel_key_map[key]].get("status")
        services[key] = ServiceDetail(
            status=_status_string(svc.get("running", False)),
            pid=svc.get("pid"),
            uptime=svc.get("uptime", "-"),
            start_time=svc.get("start_time"),
            channel_status=ch_status,
        )

    # Calculate if any service is online
    any_online = any(
        status.get(k, {}).get("running", False)
        for k in ["agent", "bridge", "feishu"]
    )

    return ServiceStatusResponse(services=services, any_online=any_online)


@router.post("/services/start", response_model=GenericResponse)
async def start_service(req: ServiceActionRequest):
    """Start a service."""
    ok, msg = config_manager.start_service(req.service)
    if ok:
        return GenericResponse(success=True, message=msg)
    raise HTTPException(status_code=500, detail=msg)


@router.post("/services/stop", response_model=GenericResponse)
async def stop_service(req: ServiceActionRequest):
    """Stop a service."""
    ok, msg = config_manager.stop_service(req.service)
    if ok:
        return GenericResponse(success=True, message=msg)
    raise HTTPException(status_code=500, detail=msg)


@router.post("/services/restart", response_model=GenericResponse)
async def restart_service(req: ServiceActionRequest):
    """Restart a service (main, agent, bridge, feishu, or all)."""
    ok, msg = config_manager.restart_service(req.service)
    if ok:
        return GenericResponse(success=True, message=msg)
    raise HTTPException(status_code=500, detail=msg)


# ---------------------------------------------------------------------------
# OAuth status / refresh endpoints
# ---------------------------------------------------------------------------

@router.get("/oauth/status", response_model=OAuthStatusResponse)
async def get_oauth_status():
    """Check OAuth login status."""
    status = config_manager.get_oauth_status()
    return OAuthStatusResponse(
        auth_mode=status.get("auth_mode", ""),
        valid=status.get("is_valid", False),
        error=status.get("error", ""),
        expires_at=status.get("expires_at", 0),
    )


@router.post("/oauth/refresh", response_model=GenericResponse)
async def refresh_oauth():
    """Trigger OAuth token refresh."""
    ok, msg = await config_manager.refresh_oauth_token()
    if ok:
        return GenericResponse(success=True, message="OAuth token refreshed")
    raise HTTPException(status_code=500, detail=msg)


# ---------------------------------------------------------------------------
# Whitelist endpoints
# ---------------------------------------------------------------------------

@router.get("/whitelist", response_model=WhitelistResponse)
async def get_whitelist():
    """获取白名单配置"""
    env = config_manager.read_env()
    return WhitelistResponse(
        user_whitelist=env.get("WECOM_USER_WHITELIST", ""),
        admin_whitelist=env.get("WECOM_ADMIN_WHITELIST", "") or env.get("WECOM_AVATAR_WHITELIST", ""),
        feishu_user_whitelist=env.get("FEISHU_USER_WHITELIST", ""),
    )


@router.post("/whitelist", response_model=GenericResponse)
async def update_whitelist(req: WhitelistUpdateRequest):
    """更新白名单配置"""
    config_manager.write_env({
        "WECOM_USER_WHITELIST": req.user_whitelist,
        "WECOM_ADMIN_WHITELIST": req.admin_whitelist,
        "FEISHU_USER_WHITELIST": req.feishu_user_whitelist,
    })
    from app.services.config_change_tracker import tracker
    tracker.mark_changed("whitelist")
    return GenericResponse(success=True, message="Whitelist updated")


# ---------------------------------------------------------------------------
# Config change tracking endpoints
# ---------------------------------------------------------------------------

@router.get("/config-changes/status")
async def get_config_change_status():
    """获取配置变更状态"""
    from app.services.config_change_tracker import tracker
    return tracker.get_status()


@router.post("/config-changes/clear")
async def clear_config_changes():
    """清空配置变更标记"""
    from app.services.config_change_tracker import tracker
    tracker.clear()
    return GenericResponse(success=True, message="Config changes cleared")


# ---------------------------------------------------------------------------
# Cron jobs endpoints
# ---------------------------------------------------------------------------

def _describe_cron(expr: str) -> str:
    """将5段 cron 表达式转为简洁中文描述"""
    try:
        m, h, d, mo, wd = expr.split()
        # 工作日
        if wd == "1-5" and d == "*" and mo == "*":
            hh = h.zfill(2) if h != "*" else "??"
            mm = m.zfill(2) if m != "*" else "00"
            return f"每工作日 {hh}:{mm}"
        # 每天
        if d == "*" and mo == "*" and wd == "*":
            if h != "*" and m != "*":
                return f"每天 {h.zfill(2)}:{m.zfill(2)}"
            return "每天"
        # 每周 X
        if d == "*" and mo == "*" and wd != "*":
            wd_names = {"0": "日", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六"}
            wd_str = wd_names.get(wd, wd)
            if h != "*" and m != "*":
                return f"每周{wd_str} {h.zfill(2)}:{m.zfill(2)}"
            return f"每周{wd_str}"
        # 每月 X 日
        if d != "*" and mo == "*" and wd == "*":
            if h != "*" and m != "*":
                return f"每月{d}日 {h.zfill(2)}:{m.zfill(2)}"
            return f"每月{d}日"
        # 每年 X 月 Y 日
        if d != "*" and mo != "*" and wd == "*":
            if h != "*" and m != "*":
                return f"每年{mo}月{d}日 {h.zfill(2)}:{m.zfill(2)}"
            return f"每年{mo}月{d}日"
        # 具体时间
        if h != "*" and m != "*":
            return f"{h.zfill(2)}:{m.zfill(2)}"
        return expr
    except Exception:
        return expr


def _format_cron_job(job: dict) -> CronJobItem:
    """将 cron_service job dict 格式化为 CronJobItem"""
    job_id = job.get("id", "")
    cron_expr = job.get("cron", "")
    context_type = job.get("context_type", "private")

    # 推断任务类型
    if job.get("skill"):
        task_type = "skill"
        task_content = job["skill"]
    elif job.get("command"):
        task_type = "command"
        task_content = job["command"]
    else:
        task_type = "message"
        task_content = job.get("message", "")

    # 格式化目标
    target_type = job.get("target_type", "self")
    if target_type == "group":
        group_name = job.get("group_name") or job.get("group_conversation_id", "")
        target = f"群聊：{group_name}" if group_name else "群聊"
    else:
        owner = job.get("owner_name") or job.get("target_name", "")
        target = f"私聊（{owner}）" if owner else "私聊（自己）"

    return CronJobItem(
        id=job_id,
        cron=cron_expr,
        cron_desc=_describe_cron(cron_expr),
        task_type=task_type,
        task_content=task_content,
        target=target,
        context_type=context_type,
        owner_name=job.get("owner_name") or "",
        created_at=job.get("created_at"),
        enabled=job.get("enabled", True),
        delete_after_run=job.get("delete_after_run", False),
    )


@router.get("/cron/jobs", response_model=CronJobsResponse)
async def get_cron_jobs():
    """列出所有定时任务"""
    from app.core.cron_service import cron_service
    raw_jobs = cron_service.list_jobs()
    items = [_format_cron_job(j) for j in raw_jobs]
    # 按创建时间倒序，无创建时间的放最后
    items.sort(key=lambda x: x.created_at or "", reverse=True)
    # 从 APScheduler 注入 next_run_time
    try:
        sj_map = {sj.id: sj for sj in cron_service.scheduler.get_jobs()}
        for item in items:
            sj = sj_map.get(item.id)
            if sj and sj.next_run_time:
                item.next_run_time = sj.next_run_time.isoformat()
    except Exception:
        pass
    return CronJobsResponse(jobs=items)


@router.delete("/cron/jobs/{job_id}", response_model=GenericResponse)
async def delete_cron_job(job_id: str):
    """删除指定定时任务"""
    from app.core.cron_service import cron_service
    ok = await cron_service.remove_job(job_id)
    if ok:
        return GenericResponse(success=True, message=f"任务 '{job_id}' 已删除")
    raise HTTPException(status_code=404, detail=f"任务未找到: {job_id}")


# ---------------------------------------------------------------------------
# Logs endpoint
# ---------------------------------------------------------------------------

def _find_log_file(project_root: Path, filename: str) -> Optional[Path]:
    """Locate a log file in data/logs/ or logs/ directory."""
    for d in (project_root / "data" / "logs", project_root / "logs"):
        f = d / filename
        if f.exists():
            return f
    return None


def _read_tail(log_file: Path, n: int) -> list[str]:
    """Read last *n* lines from a log file."""
    try:
        all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return all_lines[-n:] if n < len(all_lines) else all_lines
    except Exception:
        return []


@router.get("/logs", response_model=LogsResponse)
async def get_logs(lines: int = 200, filter: str = "", source: str = "all"):
    """Read tail of log files for remote diagnostics.

    *source* selects which logs to return:
    - ``all``     – merge service.log + bridge.log (default)
    - ``service`` – service.log only
    - ``bridge``  – bridge.log only
    """
    project_root = Path(__file__).resolve().parent.parent.parent

    try:
        parts: list[str] = []

        if source in ("all", "service"):
            f = _find_log_file(project_root, "service.log")
            if f:
                parts.extend(_read_tail(f, lines))

        if source in ("all", "bridge"):
            f = _find_log_file(project_root, "bridge.log")
            if f:
                parts.extend(_read_tail(f, lines))

        # When merging both sources, sort by timestamp then keep last N lines
        if source == "all" and parts:
            parts.sort()
            parts = parts[-lines:]

        if filter:
            filter_upper = filter.upper()
            parts = [l for l in parts if filter_upper in l.upper()]

        return LogsResponse(content="\n".join(parts), lines=len(parts))
    except Exception as e:
        logger.error(f"[CONFIG] Failed to read logs: {e}")
        return LogsResponse(content=f"Error reading log file: {e}", lines=0)


# ---------------------------------------------------------------------------
# Update endpoints
# ---------------------------------------------------------------------------

@router.get("/updates/check")
async def check_for_updates():
    """Check PyPI / GitHub for available updates."""
    from app.core.updater import Updater, get_version

    try:
        updater = Updater()
        info = await updater.check()
        if info is None:
            return {
                "available": False,
                "current_version": get_version(),
                "latest_version": get_version(),
                "changelog": "",
                "asset_size": 0,
                "source": "",
            }
        return {
            "available": info.has_update,
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "changelog": info.changelog,
            "asset_size": info.asset_size,
            "source": info.source,
        }
    except Exception as e:
        logger.error(f"[UPDATE] Check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/updates/apply", response_model=GenericResponse)
async def apply_update():
    """Download, apply update, and restart services."""
    import subprocess
    import sys

    from app.core.updater import Updater

    try:
        updater = Updater()
        info = await updater.check()
        if not info or not info.has_update:
            return GenericResponse(success=False, message="No update available")

        # Download and verify
        staging = await updater.download(info)

        # Apply in-place
        updater.apply(staging)

        logger.info("[UPDATE] Update applied, triggering restart...")
    except Exception as e:
        logger.error(f"[UPDATE] Apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Restart via restart_helper (same logic as restart-all)
    old_pid = os.getpid()
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    helper_pyc = os.path.join(project_root, "restart_helper.pyc")
    helper_py = os.path.join(project_root, "restart_helper.py")
    helper_script = helper_pyc if os.path.exists(helper_pyc) else helper_py

    if not os.path.exists(helper_script):
        raise HTTPException(status_code=500, detail="restart_helper.py not found")

    bridge_config = config_manager.read_bridge_config()
    bind_key = (bridge_config.get("client", {}).get("bind_key") or "").strip()
    bridge_configured = bool(bind_key) and "<YOUR_" not in bind_key

    from app.config import settings
    port = settings.port

    cmd = [
        sys.executable, helper_script,
        "--old-pid", str(old_pid),
        "--project-root", project_root,
        "--port", str(port),
    ]
    if bridge_configured:
        cmd.append("--restart-bridge")

    try:
        log_dir = os.path.join(project_root, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "restart.log"), "w", encoding="utf-8")

        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                cmd, creationflags=flags, close_fds=True,
                stdout=log_file, stderr=log_file,
            )
        else:
            subprocess.Popen(
                cmd, start_new_session=True, close_fds=True,
                stdout=log_file, stderr=log_file,
            )

        logger.info(f"[UPDATE] Restart helper spawned after update, old PID={old_pid}")
    except Exception as e:
        logger.error(f"[UPDATE] Failed to spawn restart helper: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to restart: {e}")

    return GenericResponse(success=True, message=str(old_pid))


# ---------------------------------------------------------------------------
# Restart all services endpoint
# ---------------------------------------------------------------------------

@router.post("/services/restart-all", response_model=GenericResponse)
async def restart_all_services():
    """重启所有已配置的服务（通过外部脱管进程编排）"""
    import subprocess
    import sys

    old_pid = os.getpid()
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    helper_pyc = os.path.join(project_root, "restart_helper.pyc")
    helper_py = os.path.join(project_root, "restart_helper.py")
    helper_script = helper_pyc if os.path.exists(helper_pyc) else helper_py

    if not os.path.exists(helper_script):
        raise HTTPException(status_code=500, detail="restart_helper.py not found")

    # 检测 Bridge 是否已配置
    bridge_config = config_manager.read_bridge_config()
    bind_key = (bridge_config.get("client", {}).get("bind_key") or "").strip()
    bridge_configured = bool(bind_key) and "<YOUR_" not in bind_key

    # 读取端口
    from app.config import settings
    port = settings.port

    # 构建命令
    cmd = [
        sys.executable, helper_script,
        "--old-pid", str(old_pid),
        "--project-root", project_root,
        "--port", str(port),
    ]
    if bridge_configured:
        cmd.append("--restart-bridge")

    # 以脱管进程启动 restart_helper
    try:
        log_dir = os.path.join(project_root, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = open(os.path.join(log_dir, "restart.log"), "w", encoding="utf-8")

        if os.name == "nt":
            # DETACHED_PROCESS 和 CREATE_NO_WINDOW 不应同时使用（行为未定义）
            flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
            subprocess.Popen(
                cmd, creationflags=flags, close_fds=True,
                stdout=log_file, stderr=log_file,
            )
        else:
            subprocess.Popen(
                cmd, start_new_session=True, close_fds=True,
                stdout=log_file, stderr=log_file,
            )

        logger.info(f"Restart helper spawned, old PID={old_pid}")
    except Exception as e:
        logger.error(f"Failed to spawn restart helper: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to spawn restart helper: {e}")

    # 清空变更标记
    from app.services.config_change_tracker import tracker
    tracker.clear()

    return GenericResponse(success=True, message=str(old_pid))
