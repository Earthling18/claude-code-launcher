"""One authenticated loopback listener per child CLI; no persistent environment edits."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import sys
from urllib.parse import urlsplit

import profiles
from relay import Relay, ConnectionFailure, close, upstream

WINDOWS = sys.platform == "win32"
_job = None


def own_windows_process_tree():
    """Assign this wrapper before spawning: closing its console kills only its tree.

    Keep the non-inheritable job handle alive until process exit. Closing it early
    would terminate the wrapper itself. Existing parent jobs must permit nesting.
    """
    global _job
    if not WINDOWS or _job:
        return
    import ctypes as c
    from ctypes import wintypes as w

    class Basic(c.Structure):
        _fields_ = [
            ("process_time", c.c_longlong),
            ("job_time", c.c_longlong),
            ("flags", w.DWORD),
            ("min_ws", c.c_size_t),
            ("max_ws", c.c_size_t),
            ("active", w.DWORD),
            ("affinity", c.c_size_t),
            ("priority", w.DWORD),
            ("scheduling", w.DWORD),
        ]

    class IO(c.Structure):
        _fields_ = [
            (name, c.c_ulonglong) for name in ("ro", "wo", "oo", "rb", "wb", "ob")
        ]

    class Extended(c.Structure):
        _fields_ = [
            ("basic", Basic),
            ("io", IO),
            ("process_memory", c.c_size_t),
            ("job_memory", c.c_size_t),
            ("peak_process", c.c_size_t),
            ("peak_job", c.c_size_t),
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not handle or not kernel.SetInformationJobObject(
        handle, 9, c.byref(limits), c.sizeof(limits)
    ):
        if handle:
            kernel.CloseHandle(handle)
        raise RuntimeError("WINDOWS_JOB: 无法建立会话清理机制")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise RuntimeError("WINDOWS_JOB: 当前终端不允许隔离子进程，请换用 PowerShell")
    _job = handle


def child_argv(args):
    if not args:
        raise ValueError("缺少启动命令")
    result = list(args)
    if not WINDOWS:
        if not shutil.which(result[0]):
            raise FileNotFoundError("CLI_NOT_FOUND")
        return result
    name = Path(result[0]).stem.lower()
    resolved = shutil.which(result[0])
    if name in ("claude", "codex"):
        native = shutil.which(name + ".exe")
        if native:
            return [native, *result[1:]]
        shim = shutil.which(name + ".cmd")
        node = shutil.which("node.exe")
        package = "@openai/codex" if name == "codex" else "@anthropic-ai/claude-code"
        root = Path(shim).parent / "node_modules" / package if shim else None
        if root and node and (root / "package.json").is_file():
            metadata = json.loads((root / "package.json").read_text(encoding="utf-8"))
            entry = metadata.get("bin")
            entry = entry.get(name) if isinstance(entry, dict) else entry
            script = (root / entry).resolve() if isinstance(entry, str) else None
            if script and script.is_relative_to(root.resolve()) and script.is_file():
                return [node, str(script), *result[1:]]
        raise FileNotFoundError("CLI_NOT_FOUND: 请检查 CLI 原生版或 npm 安装")
    if not resolved or Path(resolved).suffix.lower() in (".cmd", ".bat", ".ps1"):
        raise FileNotFoundError("CLI_NOT_FOUND: 无法直接启动此命令")
    return [resolved, *result[1:]]


def child_environment(token, port):
    env = {
        k: v
        for k, v in os.environ.items()
        if k.lower()
        not in (
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "ws_proxy",
            "wss_proxy",
            "no_proxy",
        )
    }
    url = f"http://local:{token}@127.0.0.1:{port}"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY"):
        env[key] = env[key.lower()] = url
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    return env


async def isolated_child_argv(args):
    """Codex's shared daemon does not inherit this session's proxy environment.

    Probe the installed CLI instead of pinning a version or changing global
    Codex settings. Both native binaries and Windows npm shims use the same path.
    """
    argv = child_argv(args)
    if Path(args[0]).stem.lower() != "codex":
        return argv
    if any(x == "--remote" or x.startswith("--remote=") for x in args[1:]):
        raise ConnectionFailure(
            "CLI_ISOLATION: 远端后台不会继承本次代理，请移除 --remote 后启动"
        )
    probe = await asyncio.create_subprocess_exec(
        *child_argv([args[0]]),
        "--help",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(probe.communicate(), 10)
    except asyncio.TimeoutError:
        raise ConnectionFailure(
            "CLI_ISOLATION: Codex 环境检测超时，请先检查 CLI 安装"
        ) from None
    finally:
        if probe.returncode is None:
            probe.kill()
            await probe.wait()
    if probe.returncode != 0 or b"--no-daemon" not in output:
        raise ConnectionFailure(
            "CLI_ISOLATION: 此 Codex 不支持 --no-daemon，无法保证会话代理隔离；请更新 CLI"
        )
    if "--no-daemon" not in args[1:]:
        argv = child_argv([args[0], "--no-daemon", *args[1:]])
    # Native macOS routing can prefer the OS proxy over HTTPS_PROXY. Scope these
    # overrides to this invocation so Shadowrocket and direct fallbacks cannot
    # override the explicitly selected loopback proxy.
    argv += ["-c", "features.respect_system_proxy=false", "-c", "features.system_proxy_fallback=false"]
    print("[connection] Codex 使用独立会话与指定代理，不复用共享后台或系统代理。", flush=True)
    return argv


async def diagnose(relay, env, c):
    curl = shutil.which("curl.exe" if WINDOWS else "curl")
    if not curl:
        raise FileNotFoundError("CURL_NOT_FOUND")
    # This is an unauthenticated network test, never a model/account acceptance test.
    target = c.get("diagnostic_url", "https://chatgpt.com/backend-api/models")
    if (
        urlsplit(target).scheme != "https"
        or urlsplit(target).username
        or urlsplit(target).query
    ):
        raise ValueError("诊断地址必须为不含凭据和查询参数的 HTTPS URL")
    p = await asyncio.create_subprocess_exec(
        curl,
        "--max-time",
        "30",
        "--connect-timeout",
        "12",
        "-sS",
        "-o",
        os.devnull,
        "-w",
        "%{http_code}",
        target,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(p.communicate(), 35)
    finally:
        if p.returncode is None:
            p.kill()
            await p.wait()
    status = output.decode("ascii", errors="replace")
    ok = (
        p.returncode == 0
        and status.isdigit()
        and int(status) in (200, 401, 403, 404, 405)
    )
    ok = ok and relay.stats["failed"] == 0
    print(
        f'目标 HTTPS：HTTP {status}；curl={p.returncode}；路由计数 proxy={relay.stats["proxy"]}, direct={relay.stats["direct"]}'
    )
    print(
        "此检查只验证网络响应；401 表示未携带模型账号认证，403 需要进一步检查目标访问权限。"
    )
    print("模型是否可用，仍需在 Codex / Claude Code 中完成一次真实请求。")
    return 0 if ok else 1


async def execute(args, c, creds, base, doctor=False):
    relay = Relay(c, creds, base)
    child = None
    server = None
    handlers = []
    loop = asyncio.get_running_loop()
    interactive = sys.stdin.isatty()
    try:
        argv = [] if doctor else await isolated_child_argv(args)
        # Fail closed before opening the CLI. CONNECT succeeds only after the
        # authenticated TLS ingress has accepted an upstream target connection.
        host = c.get("probe_host", "chatgpt.com")
        if any(ch.isspace() or ch in "/\\\r\n" for ch in host):
            raise ValueError("探测域名无效")
        if not relay.node_transport:
            _, remote = await relay.upstream(host, 443)
            version = remote.get_extra_info("ssl_object").version()
            await close(remote)
            print(f"[connection] 加密入口及上游 CONNECT 已通过（{version}），不代表模型认证成功。", flush=True)
        else:
            print("[connection] 本地节点配置已验证；实际请求连接节点，失败不会直连。", flush=True)
        own_windows_process_tree()
        server = await asyncio.start_server(relay.accept, "127.0.0.1", 0, limit=32768)
        port = server.sockets[0].getsockname()[1]
        env = child_environment(relay.token, port)
        if doctor:
            return await diagnose(relay, env, c)
        print(
            f"[connection] 本次会话已就绪，回环端口 {port}；退出 CLI 后自动结束。",
            flush=True,
        )
        child = await asyncio.create_subprocess_exec(
            *argv, env=env, start_new_session=not WINDOWS and not interactive
        )

        def forward(sig):
            if child.returncode is None:
                try:
                    if not interactive:
                        os.killpg(child.pid, sig)
                    elif sig != signal.SIGINT:
                        child.send_signal(sig)
                except ProcessLookupError:
                    pass

        if WINDOWS:
            old = signal.signal(signal.SIGINT, lambda *_: None)
            handlers.append((signal.SIGINT, old))
        else:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                handlers.append((sig, signal.getsignal(sig)))
                loop.add_signal_handler(sig, forward, sig)
        code = await child.wait()
        return code if code >= 0 else 128 - code
    finally:
        if server:
            server.close()
        if child:
            if not WINDOWS and not interactive:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif child.returncode is None:
                child.terminate()
            if child.returncode is None:
                try:
                    await asyncio.wait_for(child.wait(), 5)
                except asyncio.TimeoutError:
                    child.kill()
                    await child.wait()
        tasks = list(relay.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if server:
            await server.wait_closed()
        await relay.shutdown()
        for sig, previous in handlers:
            if not WINDOWS:
                loop.remove_signal_handler(sig)
            signal.signal(sig, previous)
        print(
            "[connection] " + json.dumps(relay.stats, ensure_ascii=False),
            file=sys.stderr,
        )


def run(profile, args, doctor=False):
    c, creds, base = profiles.load(profile)
    try:
        return asyncio.run(execute(args, c, creds, base, doctor))
    except ConnectionFailure as exc:
        print("[connection] " + str(exc), file=sys.stderr)
        return 1
