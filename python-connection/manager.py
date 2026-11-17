"""Loopback-only configuration UI. No global proxy, shell or service changes."""

import asyncio
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import threading
import time
import urllib.parse
import webbrowser

import profiles
import subscriptions
import components
from resident import Resident
from runner import child_environment
from desktop import DesktopSession

ASSETS = Path(__file__).parent / "web"
FIELDS = {"name", "server_ip", "server_port", "server_name", "interface", "default",
          "direct", "proxy", "block", "company_dns", "china_routing", "routing_mode", "connection_type", "subscription_ref"}


class Manager:
    def __init__(self, loop):
        self.loop = loop
        self.resident = Resident()
        self.token = secrets.token_urlsafe(32)
        self.origin = ""
        self.stop = asyncio.Event()
        self.lock = threading.Lock()
        self.touched = time.monotonic()
        self.diagnostic = {"state": "idle"}
        self.probe_task = None
        self.diagnostics = {}
        self.desktop = DesktopSession()
        self.component_task = None
        self.component_state = "ready" if components.available() else "missing"

    def call(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=45)
        except BaseException:
            future.cancel()
            raise

    async def state(self):
        return {"active": self.resident.snapshot(), "diagnostic": dict(self.diagnostic),
                "desktop": self.desktop.snapshot(), "components": self.component_state, "diagnostics": dict(self.diagnostics)}

    async def install_components(self):
        if self.component_task and not self.component_task.done():
            return {"state": "installing"}
        self.component_state = "installing"
        async def work():
            try:
                await components.install()
                self.component_state = "ready"
            except asyncio.CancelledError:
                self.component_state = "missing"
                raise
            except Exception:
                self.component_state = "failed"
        self.component_task = asyncio.create_task(work())
        return {"state": self.component_state}

    async def session(self, profile):
        if not self.resident.server or self.resident.profile != profile:
            raise ValueError("请先启动所选方案的常驻代理")
        return {"port": self.resident.port, "token": self.resident.relay.token}

    async def begin_probe(self, profile):
        if self.probe_task and not self.probe_task.done():
            raise ValueError("诊断正在进行")
        profiles.load(profile)
        self.diagnostic = {"state": "running", "profile": profile}
        self.probe_task = asyncio.create_task(self.probe(profile))
        return dict(self.diagnostic)

    async def probe(self, profile):
        test = Resident()
        process = None
        started = time.monotonic()
        try:
            state = await test.start(profile)
            curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
            if not curl:
                raise FileNotFoundError()
            # Fixed diagnostic target, bounded subprocess, no credential in argv.
            process = await asyncio.create_subprocess_exec(
                curl, "--connect-timeout", "8", "--max-time", "25", "-sS",
                "-o", os.devnull, "-w", "%{http_code}",
                "https://chatgpt.com/backend-api/models",
                env=child_environment(test.relay.token, state["port"]),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 30)
            status = output.decode("ascii", errors="replace")
            ok = process.returncode == 0 and status in ("200", "401", "403", "404", "405")
            self.diagnostic = {
                "state": "response" if ok else "failed", "profile": profile,
                "http_status": status if status.isdigit() else "000",
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "error": test.relay.last_error,
                "time": time.time(), "model_verified": False,
            }
        except asyncio.CancelledError:
            self.diagnostic = {"state": "cancelled", "profile": profile}
            raise
        except Exception:
            self.diagnostic = {"state": "failed", "profile": profile, "error": "DIAGNOSTIC"}
        finally:
            self.diagnostics[profile] = dict(self.diagnostic)
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            await test.stop()

    async def cancel_probe(self):
        if self.probe_task and not self.probe_task.done():
            self.probe_task.cancel()
            await asyncio.gather(self.probe_task, return_exceptions=True)

    async def quit(self):
        if self.component_task and not self.component_task.done():
            self.component_task.cancel()
            await asyncio.gather(self.component_task, return_exceptions=True)
        if self.resident.server or self.desktop.process:
            raise ValueError("请先停止常驻代理和专用客户端")
        self.stop.set()


def profile_view(profile):
    c, _, _ = profiles.load(profile)
    return {"id": profile, "revision": profiles.revision(profile),
            "config": {k: v for k, v in c.items() if k in FIELDS},
            "has_credentials": True}


def handler_for(manager):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Connection"

        def log_message(self, *_):
            pass  # No access URLs, tokens or request bodies in logs.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def reply(self, status, data, mime="application/json; charset=utf-8"):
            content = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(content)

        def authorized(self):
            if self.headers.get("Host") != urllib.parse.urlsplit(manager.origin).netloc:
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != manager.origin:
                return False
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + manager.token)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if self.headers.get("Host") != urllib.parse.urlsplit(manager.origin).netloc:
                self.reply(403, {"error": "请求来源不匹配"})
                return
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if parsed.path in assets:
                name, mime = assets[parsed.path]
                self.reply(200, (ASSETS / name).read_bytes(), mime)
                return
            if not self.authorized():
                self.reply(403, {"error": "管理页已失效，请从启动器重新打开"})
                return
            manager.touched = time.monotonic()
            try:
                with manager.lock:
                    if parsed.path == "/api/state":
                        rows = []
                        for ident in profiles.list_profiles():
                            try:
                                c, _, _ = profiles.load(ident)
                                rows.append({"id": ident, "name": c.get("name") or ident, "type": c.get("connection_type", "cloud"), "subscription_ref": c.get("subscription_ref")})
                            except Exception:
                                rows.append({"id": ident, "name": ident + "（配置需修复）"})
                        self.reply(200, dict(manager.call(manager.state()), profiles=rows))
                    elif parsed.path == "/api/subscriptions":
                        self.reply(200, {"sources": subscriptions.view()})
                    elif parsed.path == "/api/profile":
                        ident = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
                        self.reply(200, profile_view(ident))
                    else:
                        self.reply(404, {"error": "不存在的操作"})
            except Exception:
                self.reply(400, {"error": "读取失败，请检查方案文件和配置格式"})

        def do_POST(self):
            if not self.authorized() or self.headers.get("Origin") != manager.origin:
                self.reply(403, {"error": "请求来源或管理凭据无效"})
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError()
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 3 * 1024 * 1024:
                    raise ValueError()
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError()
                manager.touched = time.monotonic()
                with manager.lock:
                    path = urllib.parse.urlsplit(self.path).path
                    if path == "/api/components/install":
                        self.reply(200, manager.call(manager.install_components()))
                    elif path == "/api/subscriptions/import":
                        self.reply(200, subscriptions.import_source(data.get("name", ""), data.get("text", ""), data.get("url", ""), data.get("id")))
                    elif path == "/api/subscriptions/select":
                        self.reply(200, subscriptions.select(data["source"], data["node"]))
                    elif path == "/api/save":
                        ident = data.get("id") or "connection-" + secrets.token_hex(6)
                        old, creds = {}, {}
                        if ident in profiles.list_profiles():
                            old, creds, _ = profiles.load(ident)
                            if data.get("revision") != profiles.revision(ident):
                                self.reply(409, {"error": "方案已被修改，请重新载入再编辑"})
                                return
                        edited = data.get("config", {})
                        if not isinstance(edited, dict) or set(edited) - FIELDS:
                            raise ValueError()
                        if old and (edited.get("connection_type", old.get("connection_type", "cloud")) != old.get("connection_type", "cloud") or edited.get("subscription_ref", old.get("subscription_ref")) != old.get("subscription_ref")):
                            raise ValueError()
                        c = dict(old, **edited)
                        replacement = data.get("credentials")
                        if replacement:
                            creds = replacement
                        profiles.save(ident, c, creds, data.get("revision"))
                        self.reply(200, profile_view(ident))
                    elif path == "/api/start":
                        port = data.get("port", 0)
                        if type(port) is not int or not 0 <= port <= 65535:
                            raise ValueError()
                        self.reply(200, manager.call(manager.resident.start(data["id"], port)))
                    elif path == "/api/stop":
                        manager.call(manager.resident.stop())
                        self.reply(200, {"state": "stopped"})
                    elif path == "/api/diagnose":
                        self.reply(200, manager.call(manager.begin_probe(data["id"])))
                    elif path == "/api/cancel-diagnostic":
                        manager.call(manager.cancel_probe())
                        self.reply(200, {"ok": True})
                    elif path == "/api/session":
                        self.reply(200, manager.call(manager.session(data["id"])))
                    elif path == "/api/desktop/start":
                        try:
                            result = manager.call(manager.desktop.start(data["id"], data.get("mode", "existing")))
                        except ValueError as exc:
                            if str(exc) == "DESKTOP_QUIT_REQUIRED":
                                self.reply(409, {"error": "请先在 Codex 菜单中选择“退出”（Mac：⌘Q，含之前的试用窗口），再回来点击打开。仅关闭窗口不够；我们不会强制退出或修改你的记录。", "code": "DESKTOP_QUIT_REQUIRED"})
                                return
                            raise
                        self.reply(200, result)
                    elif path == "/api/desktop/stop":
                        manager.call(manager.desktop.stop())
                        self.reply(200, {"state": "stopped"})
                    elif path == "/api/desktop/credential":
                        self.reply(200, manager.call(manager.desktop.local_credential()))
                    elif path == "/api/quit":
                        manager.call(manager.quit())
                        self.reply(200, {"ok": True})
                    else:
                        self.reply(404, {"error": "不存在的操作"})
            except ValueError as exc:
                path = urllib.parse.urlsplit(self.path).path
                if path.startswith("/api/subscriptions/"):
                    self.reply(400, {"error": "订阅操作失败：检查格式和有效期。若更新后只剩不支持的协议，保留原节点；也可粘贴 SS / AnyTLS 配置。原连接不变。"})
                else:
                    self.reply(400, {"error": "操作未完成，请检查配置；已有客户端或常驻连接请先停止。"})
            except Exception:
                message = ("客户端未打开：检查官方客户端安装；已有专用窗口时请先退出它再试。原客户端未修改。"
                           if urllib.parse.urlsplit(self.path).path.startswith("/api/desktop/") else
                           "操作未完成：检查配置、认证信息和端口；退出管理前需先关闭专用客户端并停止常驻代理。")
                self.reply(400, {"error": message})
    return Handler


@contextlib.contextmanager
def single_manager():
    """OS lock is released on crashes; no stale PID guessing or process killing."""
    profiles.ROOT.mkdir(parents=True, exist_ok=True)
    stream = (profiles.ROOT / ".manager.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()


async def run(profile, open_browser=True, start_resident=False, port=0):
    manager = Manager(asyncio.get_running_loop())
    if start_resident:
        await manager.resident.start(profile, port)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(manager))
    server.daemon_threads = True
    manager.origin = f"http://127.0.0.1:{server.server_port}"
    runtime = profiles.ROOT / ".manager.json"
    profiles.atomic_json(runtime, {"origin": manager.origin, "token": manager.token})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = manager.origin + "/#" + urllib.parse.urlencode({"token": manager.token, "profile": profile})
    print(f"[connection] 管理页 {manager.origin}；关闭网页不会关闭常驻代理。", flush=True)
    print("[connection] 退出管理请先停止常驻连接，再点击“退出管理”。", flush=True)
    if open_browser:
        await asyncio.to_thread(webbrowser.open, url)
    registered = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            manager.loop.add_signal_handler(sig, manager.stop.set)
            registered.append(sig)
        except NotImplementedError:
            pass
    try:
        while not manager.stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(manager.stop.wait(), 5)
            # No proxy ownership => stale management page may exit. Active
            # residents deliberately remain alive until explicitly stopped.
            if not manager.resident.server and not manager.desktop.process and time.monotonic() - manager.touched > 900:
                manager.stop.set()
    finally:
        if manager.component_task and not manager.component_task.done():
            manager.component_task.cancel()
            await asyncio.gather(manager.component_task, return_exceptions=True)
        await manager.cancel_probe()
        await manager.desktop.stop()
        await manager.resident.stop()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        runtime.unlink(missing_ok=True)
        for sig in registered:
            manager.loop.remove_signal_handler(sig)


def main(profile="default", open_browser=True, start_resident=False, port=0):
    lock = single_manager()
    try:
        lock.__enter__()
    except (BlockingIOError, PermissionError):
        # Reopen this installation's existing manager, never start a second one.
        import http.client
        data = json.loads((profiles.ROOT / ".manager.json").read_text())
        address = urllib.parse.urlsplit(data["origin"])
        if address.scheme != "http" or address.hostname != "127.0.0.1" or not address.port:
            raise ValueError("管理页地址无效")
        conn = http.client.HTTPConnection(address.hostname, address.port, timeout=3)
        try:
            conn.request("GET", "/api/state", headers={"Authorization": "Bearer " + data["token"]})
            response = conn.getresponse()
            if response.status != 200:
                raise ValueError("管理页验证失败")
            state = json.loads(response.read())
            if start_resident:
                active = state["active"]
                if active["state"] != "stopped":
                    if active["profile"] != profile or (port and active["port"] != port):
                        raise ValueError("已有其他常驻连接，请先在管理页停止")
                else:
                    conn.request("POST", "/api/start", json.dumps({"id": profile, "port": port}), headers={
                        "Authorization": "Bearer " + data["token"], "Origin": data["origin"],
                        "Content-Type": "application/json",
                    })
                    response = conn.getresponse()
                    response.read()
                    if response.status != 200:
                        raise ValueError("常驻启动失败，请检查管理页")
        finally:
            conn.close()
        if open_browser:
            webbrowser.open(data["origin"] + "/#" + urllib.parse.urlencode({"token": data["token"], "profile": profile}))
        return
    try:
        asyncio.run(run(profile, open_browser, start_resident, port))
    finally:
        lock.__exit__(None, None, None)


def attach(profile, args):
    """Explicit terminal attachment. Secrets travel only in local HTTP/env."""
    import http.client
    import subprocess
    import sys
    import runner
    data = json.loads((profiles.ROOT / ".manager.json").read_text())
    address = urllib.parse.urlsplit(data["origin"])
    if address.scheme != "http" or address.hostname != "127.0.0.1" or not address.port:
        raise ValueError("管理页地址无效")
    conn = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
    try:
        conn.request("POST", "/api/session", json.dumps({"id": profile}), headers={
            "Authorization": "Bearer " + data["token"], "Origin": data["origin"],
            "Content-Type": "application/json",
        })
        reply = conn.getresponse()
        if reply.status != 200:
            raise ValueError("请先在管理页启动所选方案的常驻代理")
        session = json.loads(reply.read(8192))
    finally:
        conn.close()
    argv = asyncio.run(runner.isolated_child_argv(args))
    runner.own_windows_process_tree()
    interactive = sys.stdin.isatty()
    grouped = os.name != "nt" and not interactive
    child = subprocess.Popen(argv, env=child_environment(session["token"], session["port"]),
                             start_new_session=grouped)
    handlers = []
    terminating = False

    def signal_group(sig):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # macOS can report EPERM for a group whose last member just exited.
            # A live child still means cleanup really failed: do not hide it.
            if child.poll() is None:
                raise

    def forward(sig, _frame):
        nonlocal terminating
        if child.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                if grouped:
                    signal_group(sig)
                elif sig != signal.SIGINT:
                    child.send_signal(sig)
        if sig != signal.SIGINT:
            terminating = True
            raise SystemExit(128 + sig)

    print("[connection] 使用常驻代理；退出此次 CLI 不会停止常驻代理。", flush=True)
    try:
        for sig in ([signal.SIGINT] if os.name == "nt" else [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]):
            handlers.append((sig, signal.signal(sig, forward)))
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        if grouped and not terminating:
            signal_group(signal.SIGTERM)
        elif not grouped and not terminating and child.poll() is None:
            child.terminate()
        if child.poll() is None:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if grouped:
                    signal_group(signal.SIGKILL)
                else:
                    child.kill()
                child.wait()
        for sig, previous in handlers:
            signal.signal(sig, previous)

