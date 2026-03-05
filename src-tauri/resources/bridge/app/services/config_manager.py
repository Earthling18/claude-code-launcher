"""
Configuration management service.

Provides read/write access to .env, bridge/config.yaml, soul.md,
and skills. Also exposes service management via installer/core/launcher.py.
"""

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------

def _parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a .env file into an ordered dict of key=value pairs.

    Preserves comments as-is; only extracts actual variable lines.
    """
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        result[key.strip()] = value.strip()
    return result


def _write_env_file(path: Path, updates: Dict[str, str]) -> None:
    """Update .env file in-place, preserving comments and structure.

    - If a key already exists (including commented-out), update its value.
    - If a key is new, append it at the end.
    - If a value is empty string, comment out the line.
    """
    if not path.exists():
        # Create from scratch
        lines = []
        for k, v in updates.items():
            lines.append(f"{k}={v}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    original_lines = path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    seen_keys: set[str] = set()

    for line in original_lines:
        stripped = line.strip()

        # Check if this is an active variable line
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                seen_keys.add(key)
                value = updates[key]
                if value == "":
                    # Comment out the line
                    new_lines.append(f"# {key}=")
                else:
                    new_lines.append(f"{key}={value}")
                continue

        # Check if this is a commented-out variable that we want to set
        if stripped.startswith("#"):
            # Match patterns like "# KEY=value" or "#KEY=value"
            match = re.match(r"^#\s*([A-Z_][A-Z0-9_]*)=(.*)$", stripped)
            if match:
                key = match.group(1)
                if key in updates and key not in seen_keys:
                    seen_keys.add(key)
                    value = updates[key]
                    if value == "":
                        new_lines.append(line)  # Keep commented
                    else:
                        new_lines.append(f"{key}={value}")
                    continue

        new_lines.append(line)

    # Append new keys not found in file
    for key, value in updates.items():
        if key not in seen_keys:
            new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ConfigManager:
    """Centralized configuration management."""

    def __init__(self, project_root: Optional[Path] = None):
        self.root = project_root or _PROJECT_ROOT
        # 优先使用 data/ 下的配置文件（Embedded Python 打包模式）
        data_dir = self.root / "data"
        data_env = data_dir / ".env"
        self.env_path = data_env if data_env.exists() else self.root / ".env"
        self.env_example_path = self.root / ".env.example"
        data_bridge = data_dir / "bridge" / "config.yaml"
        self.bridge_config_path = data_bridge if data_bridge.exists() else self.root / "bridge" / "config.yaml"
        self.bridge_config_example = self.root / "bridge" / "config.yaml.example"
        from app.config import settings as _settings
        self.soul_path = _settings.resolved_soul_file
        self.skills_dir = self.root / ".claude" / "skills"

        # Status cache (TTL-based to avoid repeated process scanning)
        self._status_cache: Optional[Dict] = None
        self._status_cache_time: float = 0.0
        self._STATUS_CACHE_TTL = 2.0

    # ---- .env ----

    def read_env(self) -> Dict[str, str]:
        """Read all variables from .env file."""
        return _parse_env_file(self.env_path)

    def write_env(self, updates: Dict[str, str]) -> None:
        """Update .env file with the given key-value pairs.

        Preserves existing structure and comments.
        """
        _write_env_file(self.env_path, updates)
        logger.info(f"[CONFIG] Updated .env with {len(updates)} keys: {list(updates.keys())}")

    def env_exists(self) -> bool:
        return self.env_path.exists()

    # ---- bridge/config.yaml ----

    def read_bridge_config(self) -> Dict[str, Any]:
        """Read bridge/config.yaml as dict."""
        if not self.bridge_config_path.exists():
            return {}
        content = self.bridge_config_path.read_text(encoding="utf-8")
        return yaml.safe_load(content) or {}

    def write_bridge_config(self, data: Dict[str, Any]) -> None:
        """Write bridge/config.yaml from dict.

        Merges into existing structure to preserve comments is not possible
        with pyyaml, so we do a full overwrite with nice formatting.
        """
        self.bridge_config_path.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        self.bridge_config_path.write_text(content, encoding="utf-8")
        logger.info("[CONFIG] Updated bridge/config.yaml")

    def bridge_config_exists(self) -> bool:
        return self.bridge_config_path.exists()

    # ---- soul.md ----

    def read_soul(self) -> str:
        """Read soul.md content."""
        if not self.soul_path.exists():
            return ""
        return self.soul_path.read_text(encoding="utf-8")

    def write_soul(self, content: str) -> None:
        """Write soul.md content."""
        self.soul_path.parent.mkdir(parents=True, exist_ok=True)
        self.soul_path.write_text(content, encoding="utf-8")
        logger.info("[CONFIG] Updated soul.md")

    def soul_exists(self) -> bool:
        return self.soul_path.exists()

    # ---- Skills ----

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all skills from .claude/skills/ directory."""
        skills = []
        if not self.skills_dir.exists():
            return skills

        for skill_path in sorted(self.skills_dir.iterdir()):
            if not skill_path.is_dir() or skill_path.name.startswith("."):
                continue
            skill_md = skill_path / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                meta = self._parse_skill_frontmatter(content)
                body = self._extract_skill_body(content)
                skills.append({
                    "name": skill_path.name,
                    "display_name": meta.get("name", skill_path.name),
                    "description": meta.get("description", ""),
                    "version": meta.get("version", "1.0.0"),
                    "content": body,
                })
            except Exception as e:
                logger.warning(f"Failed to parse skill {skill_path.name}: {e}")
                skills.append({
                    "name": skill_path.name,
                    "display_name": skill_path.name,
                    "description": "",
                    "version": "",
                    "content": "",
                })
        return skills

    def read_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Read a single skill's metadata and content."""
        skill_path = self.skills_dir / skill_name
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            return None
        content = skill_md.read_text(encoding="utf-8")
        meta = self._parse_skill_frontmatter(content)
        body = self._extract_skill_body(content)
        return {
            "name": skill_name,
            "display_name": meta.get("name", skill_name),
            "description": meta.get("description", ""),
            "version": meta.get("version", "1.0.0"),
            "content": body,
        }

    def write_skill(self, skill_name: str, display_name: str, description: str,
                     version: str, content: str) -> None:
        """Create or update a skill."""
        skill_path = self.skills_dir / skill_name
        skill_path.mkdir(parents=True, exist_ok=True)
        skill_md = skill_path / "SKILL.md"

        frontmatter = (
            f"---\n"
            f"name: {display_name}\n"
            f"description: {description}\n"
            f"version: {version}\n"
            f"---\n"
        )
        skill_md.write_text(frontmatter + content, encoding="utf-8")
        logger.info(f"[CONFIG] Wrote skill: {skill_name}")

    def write_skill_from_upload(self, skill_name: str, files) -> None:
        """Create or update a skill from uploaded files (multipart/form-data).

        Args:
            skill_name: The skill directory name.
            files: List of UploadFile objects. Each file's filename may contain
                   a relative path like "my-skill/SKILL.md" from webkitdirectory.
        """
        skill_path = self.skills_dir / skill_name
        # Clean existing skill directory if it exists
        if skill_path.exists():
            shutil.rmtree(skill_path)
        skill_path.mkdir(parents=True, exist_ok=True)

        for upload_file in files:
            # The filename from webkitdirectory includes the relative path
            # e.g., "my-skill/SKILL.md" or "my-skill/scripts/run.py"
            raw_name = upload_file.filename or ""
            # Strip the top-level directory name (it's the skill_name already)
            parts = raw_name.replace("\\", "/").split("/")
            if len(parts) > 1:
                # Remove the first directory component (the skill directory name)
                rel_path = "/".join(parts[1:])
            else:
                rel_path = raw_name

            if not rel_path:
                continue

            dest = skill_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = upload_file.file.read()
            dest.write_bytes(content)
            logger.info(f"[CONFIG] Wrote skill file: {dest}")

        logger.info(f"[CONFIG] Uploaded skill: {skill_name} ({len(files)} files)")

    def delete_skill(self, skill_name: str) -> bool:
        """Delete a skill directory."""
        skill_path = self.skills_dir / skill_name
        if not skill_path.exists():
            return False
        shutil.rmtree(skill_path)
        logger.info(f"[CONFIG] Deleted skill: {skill_name}")
        return True

    # ---- Service status / management ----

    def _invalidate_status_cache(self):
        """Invalidate the service status cache."""
        self._status_cache = None
        self._status_cache_time = 0.0

    @staticmethod
    def _is_port_listening(port: int) -> bool:
        """Check if a TCP port is listening on localhost."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                return s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            return False

    @staticmethod
    def _find_process_by_script(script_name: str) -> Optional[int]:
        """Find a running process whose command line contains the given script name.

        Uses 'wmic' on Windows, 'ps' on Unix. Returns the PID if found.
        """
        try:
            if os.name == "nt":
                # WMIC: list python processes with their command lines
                result = subprocess.run(
                    ["wmic", "process", "where",
                     "name like '%python%'",
                     "get", "ProcessId,CommandLine"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.splitlines():
                    if script_name in line:
                        # Last token on the line is the PID
                        parts = line.strip().split()
                        if parts:
                            try:
                                return int(parts[-1])
                            except ValueError:
                                continue
            else:
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if script_name in line and "grep" not in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                return int(parts[1])
                            except ValueError:
                                continue
        except Exception:
            pass
        return None

    @staticmethod
    def _find_all_processes(script_name: str) -> List[int]:
        """Find all running processes whose command line contains the given script name.

        Uses 'wmic' on Windows, 'ps' on Unix. Returns a list of PIDs.
        """
        pids = []
        try:
            if os.name == "nt":
                # WMIC: list python processes with their command lines
                result = subprocess.run(
                    ["wmic", "process", "where",
                     "name like '%python%'",
                     "get", "ProcessId,CommandLine"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.splitlines():
                    if script_name in line:
                        # Last token on the line is the PID
                        parts = line.strip().split()
                        if parts:
                            try:
                                pids.append(int(parts[-1]))
                            except ValueError:
                                continue
            else:
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if script_name in line and "grep" not in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                pids.append(int(parts[1]))
                            except ValueError:
                                continue
        except Exception:
            pass
        return pids

    @staticmethod
    def _is_feishu_ws_thread_alive() -> bool:
        """Check if the feishu-ws daemon thread is alive."""
        for t in threading.enumerate():
            if t.name == "feishu-ws" and t.is_alive():
                return True
        return False

    def _check_bridge_ws_connection(self) -> bool:
        """Check if there is an active WebSocket connection to the bridge server.

        Parses the server_url from bridge/config.yaml and uses psutil to check
        whether any established TCP connection matches the target host and port.
        """
        try:
            import psutil
        except ImportError:
            return False

        try:
            config = self.read_bridge_config()
            server_url = config.get("client", {}).get("server_url", "")
            if not server_url:
                return False

            # Parse host and port from URL like "ws://host:port/path"
            match = re.search(r"://([^/:]+):?(\d+)?", server_url)
            if not match:
                return False

            target_host = match.group(1)
            target_port = int(match.group(2)) if match.group(2) else 80

            # Resolve hostname to IP for comparison
            try:
                target_ip = socket.gethostbyname(target_host)
            except socket.gaierror:
                target_ip = target_host

            for conn in psutil.net_connections(kind='inet'):
                if conn.status == psutil.CONN_ESTABLISHED:
                    if hasattr(conn, 'raddr') and conn.raddr:
                        if conn.raddr.ip == target_ip and conn.raddr.port == target_port:
                            return True
            return False
        except Exception:
            return False

    def _get_process_start_time(self, pid: int) -> Optional[int]:
        """Get process start time as Unix timestamp."""
        try:
            import psutil
        except ImportError:
            return None
        try:
            proc = psutil.Process(pid)
            return int(proc.create_time())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def get_service_status(self) -> Dict[str, Any]:
        """Get status of Agent, Bridge, and Feishu services.

        Detection strategy per service:

        Agent (port 8000):
            If this API is responding, the agent is running. Also checks the
            port as a fast confirmation. ServiceManager is consulted first when
            available (installer mode) for PID/uptime information.

        Bridge (bridge_clientv3):
            1. ServiceManager (installer launched the process) — authoritative.
            2. Fall back to process scanning for 'bridge_clientv3' in the
               command line, which catches externally started instances.
            3. Fall back to network connection detection: check for an active
               TCP connection to the bridge server_url from config.yaml.

        Feishu (WebSocket long connection):
            1. Check for a live 'feishu-ws' daemon thread in the current process.
            2. Fall back to feishu_settings.enabled configuration flag.
        """
        # Check TTL cache first
        now = time.time()
        if self._status_cache is not None and (now - self._status_cache_time) < self._STATUS_CACHE_TTL:
            return self._status_cache

        agent_status: Dict[str, Any] = {
            "running": False, "pid": None, "uptime": "-", "start_time": None,
        }
        bridge_status: Dict[str, Any] = {
            "running": False, "pid": None,
        }
        feishu_status: Dict[str, Any] = {
            "running": False,
        }

        # --- Agent ---
        # If we are responding to this request, the agent is by definition running.
        # We still try ServiceManager for richer info (uptime, managed PID).
        try:
            from installer.core.launcher import service_manager
            if service_manager.is_agent_running():
                pid = service_manager.agent_pid()
                agent_status = {
                    "running": True,
                    "pid": pid,
                    "uptime": service_manager.agent_uptime(),
                    "start_time": self._get_process_start_time(pid) if pid else None,
                }
            else:
                # ServiceManager says not running, but we ARE running (standalone).
                pid = os.getpid()
                agent_status = {
                    "running": True,
                    "pid": pid,
                    "uptime": "-",
                    "start_time": self._get_process_start_time(pid),
                }
        except ImportError:
            # Standalone mode — we are the agent.
            pid = os.getpid()
            agent_status = {
                "running": True,
                "pid": pid,
                "uptime": "-",
                "start_time": self._get_process_start_time(pid),
            }

        # --- Bridge ---
        bridge_detected = False
        bridge_multiple = False
        try:
            from installer.core.launcher import service_manager
            if service_manager.is_bridge_running():
                bridge_status = {
                    "running": True,
                    "pid": service_manager.bridge_pid(),
                }
                bridge_detected = True
                # Check for additional processes
                all_pids = self._find_all_processes("bridge_clientv3")
                if len(all_pids) > 1:
                    bridge_multiple = True
        except ImportError:
            pass

        if not bridge_detected:
            # Fall back 1: scan for running bridge_clientv3 processes
            all_pids = self._find_all_processes("bridge_clientv3")
            if all_pids:
                bridge_status = {"running": True, "pid": all_pids[0]}
                bridge_detected = True
                if len(all_pids) > 1:
                    bridge_multiple = True

        if not bridge_detected:
            # Fall back 2: check active WebSocket connection to bridge server
            if self._check_bridge_ws_connection():
                bridge_status = {"running": True, "pid": None}

        # Add multiple_processes flag if detected
        if bridge_multiple:
            bridge_status["multiple_processes"] = True

        # --- Feishu ---
        if self._is_feishu_ws_thread_alive():
            feishu_status = {"running": True}
        else:
            # Thread not found — fall back to config flag
            try:
                from app.config import feishu_settings
                if feishu_settings.enabled:
                    # Configured but thread not alive: could be starting or crashed
                    feishu_status = {"running": False}
                else:
                    feishu_status = {"running": False}
            except ImportError:
                feishu_status = {"running": False}

        result = {
            "agent": agent_status,
            "bridge": bridge_status,
            "feishu": feishu_status,
        }
        self._status_cache = result
        self._status_cache_time = now
        return result

    def start_service(self, service: str) -> Tuple[bool, str]:
        """Start a service.

        Accepts: agent, main (alias for agent), bridge, all.
        Returns (success, message).
        """
        self._invalidate_status_cache()

        # Normalize: 'main' is an alias for 'agent'
        if service == "main":
            service = "agent"

        try:
            from installer.core.launcher import service_manager
        except ImportError:
            return False, "Service manager not available in standalone mode"

        if service == "agent":
            ok = service_manager.start_agent()
            return ok, "Agent started" if ok else "Failed to start agent"
        elif service == "bridge":
            ok = service_manager.start_bridge()
            return ok, "Bridge started" if ok else "Failed to start bridge"
        elif service == "all":
            ok1 = service_manager.start_agent()
            ok2 = service_manager.start_bridge()
            ok = ok1 and ok2
            return ok, "All services started" if ok else "Failed to start some services"
        else:
            return False, f"Unknown service: {service}"

    def stop_service(self, service: str) -> Tuple[bool, str]:
        """Stop a service.

        Accepts: agent, main (alias for agent), bridge, all.
        Returns (success, message).
        """
        self._invalidate_status_cache()

        if service == "main":
            service = "agent"

        try:
            from installer.core.launcher import service_manager
        except ImportError:
            return False, "Service manager not available in standalone mode"

        if service == "agent":
            service_manager.stop_agent()
            return True, "Agent stopped"
        elif service == "bridge":
            service_manager.stop_bridge()
            return True, "Bridge stopped"
        elif service == "all":
            service_manager.stop_all()
            return True, "All services stopped"
        else:
            return False, f"Unknown service: {service}"

    def restart_service(self, service: str) -> Tuple[bool, str]:
        """Restart a service.

        Accepts: agent, main (alias for agent), bridge, all.
        Returns (success, message).
        """
        self._invalidate_status_cache()

        if service == "main":
            service = "agent"

        # Try using ServiceManager first (installer mode)
        try:
            from installer.core.launcher import service_manager

            if service == "agent":
                ok = service_manager.restart_agent()
                return ok, "Agent restarted" if ok else "Failed to restart agent"
            elif service == "bridge":
                ok = service_manager.restart_bridge()
                return ok, "Bridge restarted" if ok else "Failed to restart bridge"
            elif service == "all":
                ok = service_manager.restart_all()
                return ok, "All services restarted" if ok else "Failed to restart services"
            else:
                return False, f"Unknown service: {service}"

        except ImportError:
            # Standalone mode fallback: use subprocess to restart
            logger.info(f"ServiceManager not available, using standalone restart for: {service}")

            if service == "agent":
                # Agent重启：先退出当前进程，再启动新进程
                try:
                    import sys
                    import subprocess
                    import threading
                    import time

                    current_pid = os.getpid()
                    python_exe = sys.executable
                    _pyc = _PROJECT_ROOT / "start.pyc"
                    _py = _PROJECT_ROOT / "start.py"
                    script_path = str(_pyc if _pyc.exists() else _py)

                    logger.info(f"Standalone restart initiated: current PID={current_pid}")

                    # 延迟重启逻辑
                    def delayed_restart():
                        try:
                            # 1. 等待1秒确保HTTP响应发送完成
                            time.sleep(1)
                            logger.info("HTTP response sent, starting restart sequence")

                            # 2. 先退出当前进程，释放端口
                            logger.info(f"Exiting current process PID={current_pid}")

                            # 3. 启动新的agent进程（在退出前fork）
                            logger.info(f"Starting new process: {python_exe} {script_path}")

                            if os.name == 'nt':  # Windows
                                # Windows: 使用CREATE_NEW_CONSOLE创建完全独立的进程
                                subprocess.Popen(
                                    [python_exe, script_path],
                                    cwd=str(_PROJECT_ROOT),
                                    creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS,
                                    close_fds=True
                                )
                            else:  # Unix/Linux
                                subprocess.Popen(
                                    [python_exe, script_path],
                                    cwd=str(_PROJECT_ROOT),
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    start_new_session=True
                                )

                            logger.info("New agent process started, exiting current process")

                            # 4. 立即退出当前进程（让新进程有机会绑定端口）
                            os._exit(0)

                        except Exception as e:
                            logger.error(f"Restart sequence failed: {e}")
                            # 重启失败，保持当前进程运行
                            logger.warning("Keeping current process running due to restart failure")
                            return

                    # 启动后台重启线程
                    restart_thread = threading.Thread(target=delayed_restart, daemon=False)
                    restart_thread.start()

                    return True, "Agent restart initiated"

                except Exception as e:
                    logger.error(f"Failed to initiate restart: {e}")
                    return False, f"Restart failed: {e}"

            elif service == "bridge":
                # Bridge重启逻辑保持不变（通过进程扫描）
                return False, "Bridge restart not supported in standalone mode"
            elif service == "all":
                # 递归调用
                ok_agent, msg_agent = self.restart_service("agent")
                return ok_agent, msg_agent
            else:
                return False, f"Unknown service: {service}"

    # ---- OAuth status ----

    def get_oauth_status(self) -> Dict[str, Any]:
        """Check OAuth login status."""
        from app.config import Settings
        s = Settings()
        is_valid, error_msg, expires_at = s.check_oauth_status()
        return {
            "auth_mode": s.claude_auth_mode,
            "is_valid": is_valid,
            "error": error_msg,
            "expires_at": expires_at,
        }

    async def refresh_oauth_token(self) -> Tuple[bool, str]:
        """Trigger OAuth token refresh.

        Delegates to Settings.refresh_oauth_token().
        Returns (success, error_message).
        """
        from app.config import Settings
        s = Settings()
        return await s.refresh_oauth_token()

    # ---- Network helpers ----

    def detect_local_ip(self) -> str:
        """Detect LAN IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ---- Internal helpers ----

    @staticmethod
    def _parse_skill_frontmatter(content: str) -> Dict[str, str]:
        """Parse YAML frontmatter from SKILL.md."""
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        try:
            return yaml.safe_load(parts[1]) or {}
        except Exception:
            return {}

    @staticmethod
    def _extract_skill_body(content: str) -> str:
        """Extract the body content after frontmatter."""
        if not content.startswith("---"):
            return content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return content
        return parts[2].strip()


# Singleton
config_manager = ConfigManager()
