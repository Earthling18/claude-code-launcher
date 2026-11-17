"""Desktop entry with normal user data by default and opt-in isolation."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import plistlib
import signal
import sys

import profiles
from resident import Resident
from runner import child_environment


def discover():
    if sys.platform != "darwin":
        return {"available": False, "message": "客户端专用入口目前仅开放 Mac 试用；Windows 的 CLI 模式可继续使用。"}
    for folder in (Path("/Applications"), Path.home() / "Applications"):
        for name in ("Codex.app", "ChatGPT.app"):
            bundle = folder / name
            try:
                info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
                executable = bundle / "Contents/MacOS" / info["CFBundleExecutable"]
                if info.get("CFBundleIdentifier") != "com.openai.codex":
                    continue
                if not executable.resolve().is_relative_to(bundle.resolve()) or not os.access(executable, os.X_OK):
                    continue
                return {"available": True, "executable": str(executable),
                        "version": str(info.get("CFBundleShortVersionString", "未知"))[:80],
                        "message": "沿用本机 Codex；打开前需完整退出已运行的客户端。"}
            except (OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
                continue
    return {"available": False, "message": "未找到 Mac Codex 客户端。请先安装官方客户端。"}


async def running_app_pids(executable):
    process = await asyncio.create_subprocess_exec(
        "/bin/ps", "-ww", "-axo", "pid=,comm=", stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 3)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0:
        raise ValueError("DESKTOP_PROCESS_CHECK_FAILED")
    target = Path(executable).resolve()
    found = []
    for line in output.decode(errors="replace").splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdigit():
            command = fields[1]
            if command == target.name or Path(command).resolve() == target:
                found.append(int(fields[0]))
    return found


class DesktopSession:
    def __init__(self):
        self.capability = discover()
        self.relay = Resident()
        self.process = None
        self.monitor = None
        self.profile = None
        self.error = None
        self.owner_file = None
        self.env_file = None
        self.guard = asyncio.Lock()
        self.mode = "existing"

    def snapshot(self):
        running = self.process is not None and self.process.returncode is None
        return {"available": self.capability["available"], "message": self.capability["message"],
                "version": self.capability.get("version"), "state": "running" if running else "stopped",
                "profile": self.profile, "error": self.error, "connection": self.relay.snapshot(),
                "model_verified": False, "mode": self.mode}

    async def local_credential(self):
        if not self.process or self.process.returncode is not None or not self.relay.relay:
            raise ValueError("DESKTOP_NOT_RUNNING")
        return {"username": "local", "password": self.relay.relay.token, "port": self.relay.port}

    async def start(self, profile, mode="existing"):
        async with self.guard:
            if mode not in ("existing", "isolated"):
                raise ValueError("DESKTOP_MODE_INVALID")
            if not self.capability["available"]:
                raise ValueError("DESKTOP_UNAVAILABLE")
            if self.process is not None:
                raise ValueError("DESKTOP_ALREADY_RUNNING")
            if mode == "existing" and await running_app_pids(self.capability["executable"]):
                self.error = "DESKTOP_QUIT_REQUIRED"
                raise ValueError("DESKTOP_QUIT_REQUIRED")
            self.mode = mode
            profiles.directory(profile)  # Validate ID before building any paths.
            base = (profiles.ROOT / ".desktop" / profile if mode == "isolated"
                    else profiles.ROOT / ".desktop-live")
            home, user_data = base / "codex-home", base / "app-data"
            for path in ((base.parent, base, home, user_data) if mode == "isolated" else (base,)):
                if path.is_symlink():
                    raise ValueError("DESKTOP_DIRECTORY")
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                path.chmod(0o700)
            owner = base / "owner.json"
            if owner.exists():
                previous = json.loads(owner.read_text())
                pid = previous.get("pid")
                if type(pid) is not int or pid <= 0:
                    raise ValueError("DESKTOP_OWNER_INVALID")
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    owner.unlink()
                else:
                    # Never guess that a stale PID can be killed safely.
                    raise ValueError("DESKTOP_PREVIOUS_WINDOW")
            source = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
            target = home / "auth.json"
            if mode == "isolated" and not target.exists() and source.is_file() and source.stat().st_size <= 1024 * 1024:
                profiles.atomic_json(target, json.loads(source.read_text()))
            config = home / "config.toml"
            if mode == "isolated" and not config.exists():
                with config.open("x", encoding="utf-8") as stream:
                    stream.write('[features]\nrespect_system_proxy = false\nsystem_proxy_fallback = false\n')
                config.chmod(0o600)
            self.error = None
            try:
                state = await self.relay.start(profile)
                env = child_environment(self.relay.relay.token, state["port"])
                env.update(CODEX_APP_SERVER_FORCE_CLI="1", CODEX_APP_SERVER_USE_LOCAL_DAEMON="0")
                args = []
                # Native runtime rereads this private, isolated home after shell
                # environment loading. No shared ~/.codex or shell edits.
                if mode == "isolated":
                    env.update(CODEX_HOME=str(home), CODEX_ELECTRON_USER_DATA_PATH=str(user_data))
                    args.append("--user-data-dir=" + str(user_data))
                    self.env_file = home / ".env"
                    fd = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "w") as stream:
                        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY", "NO_PROXY"):
                            stream.write(key + "=" + env[key] + "\n")
                else:
                    # Retain the normal home/login/history. In particular, do
                    # not create, replace or merge shared databases or .env.
                    env.pop("CODEX_ELECTRON_USER_DATA_PATH", None)
                self.process = await asyncio.create_subprocess_exec(
                    self.capability["executable"], *args,
                    "--proxy-server=http://127.0.0.1:" + str(state["port"]), "--disable-quic",
                    env=env, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
                self.profile = profile
                self.owner_file = owner
                profiles.atomic_json(owner, {"pid": self.process.pid})
                try:
                    await asyncio.wait_for(self.process.wait(), 1)
                except asyncio.TimeoutError:
                    pass
                else:
                    raise ValueError("DESKTOP_EARLY_EXIT")
                self.monitor = asyncio.create_task(self._watch())
                return self.snapshot()
            except BaseException:
                self.error = "DESKTOP_START_FAILED"
                await self._cleanup()
                raise

    async def _watch(self):
        try:
            code = await self.process.wait()
            async with self.guard:
                if code:
                    self.error = "DESKTOP_EXITED"
                await self._cleanup()
        except asyncio.CancelledError:
            pass

    async def _cleanup(self):
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()
        await self.relay.stop()
        if self.env_file:
            self.env_file.unlink(missing_ok=True)
        if self.owner_file:
            self.owner_file.unlink(missing_ok=True)
        self.process = self.profile = self.owner_file = self.env_file = None

    async def stop(self):
        async with self.guard:
            if self.monitor:
                self.monitor.cancel()
                await asyncio.gather(self.monitor, return_exceptions=True)
                self.monitor = None
            await self._cleanup()
