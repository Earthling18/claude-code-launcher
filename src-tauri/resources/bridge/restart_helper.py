#!/usr/bin/env python
"""
Detached restart helper — orchestrates Agent (and optionally Bridge) restart.

Spawned by the config API as a fully detached process so the old Agent
can exit cleanly while this script brings up the new one.

Usage:
    python restart_helper.py --old-pid 12345 --project-root /path/to/project [--restart-bridge] [--port 8000]
"""

import argparse
import logging
import os
import socket
import subprocess
import sys
import time

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "restart.log")


def setup_logging(project_root: str):
    log_dir = os.path.join(project_root, LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(project_root, LOG_FILE)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s [restart] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def kill_pid(pid: int):
    """Kill a process by PID (without tree kill to avoid killing helper itself)."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            logging.warning(f"taskkill failed for PID {pid}: {e}")
    else:
        import signal as _signal
        try:
            os.kill(pid, _signal.SIGTERM)
            time.sleep(2)
            try:
                os.kill(pid, _signal.SIGKILL)
            except OSError:
                pass  # already dead
        except OSError:
            pass


def kill_process_tree(pid: int, exclude_pid: int):
    """Kill a process and all its descendants, excluding exclude_pid."""
    try:
        import psutil
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        # Kill parent first
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass
        # Kill all children (except ourselves)
        for child in children:
            if child.pid == exclude_pid:
                continue
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        logging.info(f"Killed process tree: root={pid}, children={len(children)}")
    except ImportError:
        logging.warning("psutil not available, falling back to taskkill")
        kill_pid(pid)
    except psutil.NoSuchProcess:
        logging.info(f"Process {pid} already dead")


def _iter_processes():
    """Yield (pid, cmdline_str) for all running processes."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
                yield proc.info["pid"], " ".join(cmdline)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return
    except ImportError:
        pass

    # Fallback: wmic on Windows
    if os.name == "nt":
        try:
            r = subprocess.run(
                ["wmic", "process", "get", "ProcessId,CommandLine", "/FORMAT:CSV"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in r.stdout.strip().splitlines()[1:]:
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    cmdline_str = ",".join(parts[1:-1])
                    try:
                        pid = int(parts[-1])
                        yield pid, cmdline_str
                    except ValueError:
                        pass
        except Exception as e:
            logging.warning(f"wmic fallback failed: {e}")


def cleanup_orphan_claude_processes(own_pid: int, project_root: str):
    """Kill orphan claude.exe and node.exe processes left by previous runs.

    Targets:
    - claude.exe whose cmdline references mobot-bridge paths, or whose parent is dead
    - node.exe children of such claude.exe (usually cleaned by OS, but do a sweep)

    Bridge cleanup is NOT done here — bridge processes are handled exclusively by
    _kill_all_bridge_processes() (called only when --restart-bridge is set).
    The parent-dead heuristic doesn't work for bridge because restart_helper (its
    launcher) always exits after restart, making every bridge look like an orphan.

    Optimized: single process_iter scan + batch PID set lookup (vs two scans + per-pid exists).
    """
    try:
        import psutil
    except ImportError:
        logging.warning("psutil not available, skipping orphan claude/node cleanup")
        return

    project_root_lower = project_root.replace("\\", "/").lower()
    killed_count = 0

    # 1. Snapshot all alive PIDs once (fast, <100ms vs per-pid psutil.pid_exists)
    all_pids = set(psutil.pids())

    # 2. Two-phase scan: filter by name first (fast, no WMI cmdline query),
    #    then fetch cmdline/ppid only for matching processes (on-demand).
    #    On Windows, requesting cmdline in process_iter triggers a slow WMI
    #    query for EVERY process; this avoids that for the vast majority.
    claude_targets = []
    node_candidates = []

    for proc in psutil.process_iter(["pid", "name"]):
        if proc.info["pid"] == own_pid:
            continue
        try:
            name = (proc.info.get("name") or "").lower()
            if name in ("claude.exe", "claude"):
                try:
                    info = proc.as_dict(attrs=["pid", "name", "cmdline", "ppid"])
                    claude_targets.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            elif name in ("node.exe", "node"):
                try:
                    info = proc.as_dict(attrs=["pid", "name", "cmdline", "ppid"])
                    node_candidates.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 3. Process claude targets (same logic, but using all_pids set)
    for info in claude_targets:
        try:
            cmdline = " ".join(info.get("cmdline") or [])
            cmdline_lower = cmdline.replace("\\", "/").lower()

            # Check if this claude.exe is related to our project
            is_ours = project_root_lower in cmdline_lower

            # Also check if parent process is dead (orphan)
            if not is_ours:
                ppid = info.get("ppid")
                if ppid and ppid not in all_pids:
                    is_ours = True

            if is_ours:
                logging.info(f"Killing orphan claude process: PID={info['pid']}, cmd={cmdline[:120]}")
                try:
                    p = psutil.Process(info["pid"])
                    children = p.children(recursive=True)
                    for child in children:
                        try:
                            child.kill()
                            killed_count += 1
                            logging.info(f"  Killed child: PID={child.pid}, name={child.name()}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                    p.kill()
                    killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logging.warning(f"  Failed to kill PID={info['pid']}: {e}")

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 4. Sweep orphan node.exe whose parent is dead (using all_pids set)
    for info in node_candidates:
        try:
            ppid = info.get("ppid")
            if ppid and ppid not in all_pids:
                cmdline = " ".join(info.get("cmdline") or [])
                logging.info(f"Killing orphan node process (parent dead): PID={info['pid']}, cmd={cmdline[:120]}")
                try:
                    psutil.Process(info["pid"]).kill()
                    killed_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if killed_count:
        logging.info(f"Orphan cleanup: killed {killed_count} processes")
    else:
        logging.info("Orphan cleanup: no orphans found")


def wait_port_free(port: int, timeout: float = 15.0) -> bool:
    """Wait until the given port is free."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.5)
    return False


def read_proxy_from_env(project_root: str) -> str:
    """Read proxy setting from .env file."""
    env_file = os.path.join(project_root, ".env")
    if not os.path.exists(env_file):
        return ""
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("WECOM_CLAUDE_HTTP_PROXY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _kill_all_bridge_processes(own_pid: int):
    """Kill ALL bridge_clientv3 processes (not just orphans). Used before restarting bridge."""
    try:
        import psutil
    except ImportError:
        logging.warning("psutil not available, skipping bridge cleanup")
        return

    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info["pid"] == own_pid:
            continue
        try:
            name = (proc.info.get("name") or "").lower()
            if name.startswith("python"):
                cmdline_str = " ".join(proc.info.get("cmdline") or [])
                if "bridge_clientv3" in cmdline_str:
                    logging.info(f"Killing bridge process before restart: PID={proc.info['pid']}")
                    try:
                        psutil.Process(proc.info["pid"]).kill()
                        killed += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    logging.info(f"Bridge pre-restart cleanup: killed {killed} processes")


def start_agent(project_root: str) -> int | None:
    """Start the Agent service, return new PID or None."""
    start_py = os.path.join(project_root, "start.py")
    start_pyc = os.path.join(project_root, "start.pyc")
    script = start_py if os.path.exists(start_py) else start_pyc
    if not os.path.exists(script):
        logging.error(f"Agent script not found: {start_py} / {start_pyc}")
        return None

    env = os.environ.copy()
    proxy = read_proxy_from_env(project_root)
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy

    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, script],
            cwd=project_root,
            env=env,
            creationflags=flags,
        )
        logging.info(f"Agent started: PID={proc.pid}")
        return proc.pid
    except Exception as e:
        logging.error(f"Failed to start Agent: {e}")
        return None


def start_bridge(project_root: str) -> int | None:
    """Start the Bridge client, return new PID or None."""
    bridge_dir = os.path.join(project_root, "bridge")
    script = os.path.join(bridge_dir, "bridge_clientv3.py")
    if not os.path.exists(script):
        script = os.path.join(bridge_dir, "bridge_clientv3.pyc")
    if not os.path.exists(script):
        logging.warning("Bridge script not found, skipping")
        return None

    env = os.environ.copy()
    # Bridge must NOT use proxy
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)

    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, script],
            cwd=bridge_dir,
            env=env,
            creationflags=flags,
        )
        logging.info(f"Bridge started: PID={proc.pid}")
        return proc.pid
    except Exception as e:
        logging.error(f"Failed to start Bridge: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Restart helper")
    parser.add_argument("--old-pid", type=int, required=True)
    parser.add_argument("--project-root", type=str, required=True)
    parser.add_argument("--restart-bridge", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Early diagnostic: write marker file before logging setup
    own_pid = os.getpid()
    try:
        marker = os.path.join(args.project_root, "logs", "restart_helper_alive.txt")
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w") as f:
            f.write(f"PID={own_pid} at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    except Exception:
        pass

    setup_logging(args.project_root)
    logging.info(f"=== Restart helper started (PID={own_pid}) ===")
    logging.info(f"Old Agent PID: {args.old_pid}, port: {args.port}, bridge: {args.restart_bridge}")

    # 1. Wait for HTTP response to finish
    time.sleep(2)

    # 2. Kill old Agent and ALL its child processes (claude.exe, MCP tools, etc.)
    logging.info(f"Killing old Agent process tree (root PID={args.old_pid})")
    kill_process_tree(args.old_pid, exclude_pid=own_pid)
    time.sleep(1)

    # 2.5 Clean up orphan claude.exe / node.exe from previous runs
    logging.info("Scanning for orphan claude.exe / node.exe processes...")
    cleanup_orphan_claude_processes(own_pid, args.project_root)
    time.sleep(1)

    # 3. Wait for port to be released
    logging.info(f"Waiting for port {args.port} to be free...")
    if not wait_port_free(args.port, timeout=15):
        logging.error(f"Port {args.port} still occupied after 15s, aborting")
        return

    logging.info(f"Port {args.port} is free")

    # 4. Start new Agent
    new_pid = start_agent(args.project_root)
    if not new_pid:
        logging.error("Failed to start new Agent")
        return

    # 5. Start Bridge if requested
    if args.restart_bridge:
        _kill_all_bridge_processes(own_pid)
        time.sleep(1)
        start_bridge(args.project_root)

    logging.info(f"=== Restart complete: old PID={args.old_pid} -> new PID={new_pid} ===")


if __name__ == "__main__":
    main()
