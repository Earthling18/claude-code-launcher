#!/usr/bin/env python
"""
启动脚本
"""
import os
import sys
os.environ.pop("CLAUDECODE", None)

import uvicorn
from app.config import settings


def kill_port_holder(port: int):
    """检测并杀掉占用指定端口的进程"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return  # 端口空闲

    print(f"Port {port} is occupied, killing old process...")
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                old_pid = conn.pid
                if old_pid and old_pid != os.getpid():
                    proc = psutil.Process(old_pid)
                    children = proc.children(recursive=True)
                    proc.kill()
                    for child in children:
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    print(f"Killed old process tree: PID={old_pid}, children={len(children)}")
                    import time
                    time.sleep(2)
                    return
    except ImportError:
        # psutil 不可用，用 netstat + taskkill
        import subprocess
        r = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        for line in r.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                old_pid = int(parts[-1])
                if old_pid != os.getpid():
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(old_pid)],
                                   capture_output=True, timeout=10)
                    print(f"Killed old process: PID={old_pid}")
                    import time
                    time.sleep(2)
                    return
    except Exception as e:
        print(f"Warning: failed to kill old process: {e}")


if __name__ == "__main__":
    kill_port_holder(settings.port)

    print(f"Starting server on {settings.host}:{settings.port}")
    print(f"Debug mode: {settings.debug}")
    print(f"Skills directory: {settings.skills_dir}")
    print(f"Workspace directory: {settings.workspace_dir}")
    print()
    print(f"Web Config UI:     http://localhost:{settings.port}/config")
    print(f"API Documentation: http://localhost:{settings.port}/docs")
    print()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        # http="httptools",  # Windows上使用默认的h11更稳定
    )
