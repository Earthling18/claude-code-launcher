import asyncio
import base64
import http.client
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import manager
import profiles
import relay
from resident import Resident
from test_connection import config


class ProfileBundleTests(unittest.TestCase):
    def test_atomic_endpoint_credentials_and_old_files_preserved(self):
        with tempfile.TemporaryDirectory(prefix="连接 ' 包 ") as tmp, patch.object(profiles, "ROOT", Path(tmp)):
            base = profiles.directory("old")
            c = config()
            creds = {"username": "user", "password": "secret"}
            profiles.atomic_json(base / "config.json", c)
            profiles.atomic_json(base / "credentials.json", creds)
            previous = (base / "config.json").read_bytes()
            rev = profiles.revision("old")
            profiles.save("old", dict(c, server_port=2345, name="中文 方案"), dict(creds, password="changed"), rev)
            current, current_creds, _ = profiles.load("old")
            self.assertEqual(current["server_port"], 2345)
            self.assertEqual(current_creds["password"], "changed")
            self.assertEqual(previous, (base / "config.json").read_bytes())
            with self.assertRaises(ValueError):
                profiles.save("old", c, creds, rev)
            self.assertNotIn("changed", json.dumps(manager.profile_view("old")))
            if os.name != "nt":
                self.assertEqual((base / "connection.json").stat().st_mode & 0o777, 0o600)

    def test_bad_save_does_not_replace_working_bundle(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profiles, "ROOT", Path(tmp)):
            c, creds = config(), {"username": "u", "password": "p"}
            rev = profiles.save("new", c, creds)
            before = (profiles.directory("new") / "connection.json").read_bytes()
            with self.assertRaises(ValueError):
                profiles.save("new", dict(c, server_port=70000), creds, rev)
            self.assertEqual(before, (profiles.directory("new") / "connection.json").read_bytes())
            with patch.object(profiles.os, "replace", side_effect=OSError("full")):
                with self.assertRaises(OSError):
                    profiles.save("new", dict(c, server_port=2), creds, rev)
            self.assertEqual(before, (profiles.directory("new") / "connection.json").read_bytes())

    def test_only_one_manager_owns_store(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(profiles, "ROOT", Path(tmp)):
            with manager.single_manager():
                with self.assertRaises(OSError):
                    with manager.single_manager():
                        self.fail("second manager acquired lock")
            with manager.single_manager():
                pass


class ResidentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = patch.object(profiles, "ROOT", Path(self.temp.name))
        self.store.start()
        profiles.save("test", config(), {"username": "u", "password": "p"})
        self.resident = Resident()

    async def asyncTearDown(self):
        await self.resident.stop()
        self.store.stop()
        self.temp.cleanup()

    async def test_waiting_opens_no_upstream_and_conflict_keeps_running(self):
        with patch.object(relay, "upstream", new_callable=AsyncMock) as upstream:
            state = await self.resident.start("test")
            await asyncio.sleep(.03)
            upstream.assert_not_called()
            self.assertEqual(state["state"], "waiting")
            second = Resident()
            with self.assertRaises(OSError):
                await second.start("test", state["port"])
            self.assertIsNone(second.server)
            self.assertEqual(self.resident.snapshot()["port"], state["port"])
        await self.resident.stop()
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", state["port"])

    async def test_proxy_failure_does_not_try_direct(self):
        state = await self.resident.start("test")
        with patch.object(relay, "upstream", new_callable=AsyncMock, side_effect=relay.ConnectionFailure("UPSTREAM_AUTH: failed")), patch.object(relay, "socket_open", new_callable=AsyncMock) as direct:
            r, w = await asyncio.open_connection("127.0.0.1", state["port"])
            auth = self.resident.relay.local_auth
            w.write(f"CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: {auth}\r\n\r\n".encode())
            await w.drain()
            self.assertIn(b"502", await r.read())
            await relay.close(w)
            direct.assert_not_called()
            self.assertEqual(self.resident.snapshot()["last_error"], "UPSTREAM_AUTH")

    async def test_stream_activity_is_distinct_from_waiting_and_stop_cleans_clients(self):
        async def echo(r, w):
            try:
                while b := await r.read(1024):
                    w.write(b)
                    await w.drain()
            finally:
                await relay.close(w)
        target = await asyncio.start_server(echo, "127.0.0.1", 0)
        target_port = target.sockets[0].getsockname()[1]
        c, creds, _ = profiles.load("test")
        c["direct"] = ["127.0.0.0/8"]
        profiles.save("test", c, creds, profiles.revision("test"))
        state = await self.resident.start("test")
        r, w = await asyncio.open_connection("127.0.0.1", state["port"])
        try:
            auth = self.resident.relay.local_auth
            w.write(f"CONNECT 127.0.0.1:{target_port} HTTP/1.1\r\nProxy-Authorization: {auth}\r\n\r\n".encode())
            await w.drain()
            self.assertIn(b"200", await r.readuntil(b"\r\n\r\n"))
            self.assertEqual(self.resident.snapshot()["state"], "connected")
            w.write(b"hello")
            await w.drain()
            self.assertEqual(await r.readexactly(5), b"hello")
            await asyncio.sleep(.01)
            snap = self.resident.snapshot()
            self.assertEqual(snap["state"], "transferring")
            self.assertEqual(snap["upload_bytes"], 5)
            self.assertEqual(snap["download_bytes"], 5)
            await asyncio.wait_for(self.resident.stop(), 5)
            self.assertEqual(await r.read(), b"")
        finally:
            await relay.close(w)
            target.close()
            await target.wait_closed()


class ManagerHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = patch.object(profiles, "ROOT", Path(self.temp.name))
        self.store.start()
        profiles.save("test", config(), {"username": "PRIVATE_USER", "password": "PRIVATE_PASSWORD"})
        self.manager = manager.Manager(asyncio.get_running_loop())
        self.server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.handler_for(self.manager))
        self.manager.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    async def asyncTearDown(self):
        await self.manager.cancel_probe()
        await self.manager.desktop.stop()
        await self.manager.resident.stop()
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join()
        self.store.stop()
        self.temp.cleanup()

    async def request(self, path, body=None, headers=None, auth=True):
        h = {"Authorization": "Bearer " + self.manager.token} if auth else {}
        if body is not None:
            h.update({"Origin": self.manager.origin, "Content-Type": "application/json"})
        h.update(headers or {})
        def perform():
            conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
            try:
                conn.request("GET" if body is None else "POST", path, None if body is None else json.dumps(body), h)
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()
        return await asyncio.to_thread(perform)

    async def test_missing_auth_cross_origin_and_rebinding_rejected(self):
        for kwargs in ({"auth": False}, {"headers": {"Origin": "https://evil.example"}}, {"headers": {"Host": "evil.example"}}):
            self.assertEqual((await self.request("/api/state", **kwargs))[0], 403)
        self.assertEqual((await self.request("/api/start", {"id": "test"}, headers={"Origin": "null"}))[0], 403)
        self.assertIsNone(self.manager.resident.server)
        with patch.object(self.manager.desktop, "start", new_callable=AsyncMock) as start:
            self.assertEqual((await self.request("/api/desktop/start", {"id": "test"}, auth=False))[0], 403)
            start.assert_not_called()
        self.assertEqual((await self.request("/api/desktop/credential", {}, auth=False))[0], 403)

    async def test_profile_response_and_state_never_expose_credentials(self):
        for path in ("/api/state", "/api/profile?id=test"):
            status, raw = await self.request(path)
            self.assertEqual(status, 200)
            self.assertNotIn(b"PRIVATE", raw)
            self.assertNotIn(self.manager.token.encode(), raw)
        self.assertEqual((await self.request("/api/profile?id=..%2F.."))[0], 400)

    async def test_start_stop_and_explicit_attachment_are_scoped(self):
        self.assertEqual((await self.request("/api/session", {"id": "test"}))[0], 400)
        status, raw = await self.request("/api/start", {"id": "test"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["state"], "waiting")
        self.assertEqual((await self.request("/api/start", {"id": "test"}))[0], 400)
        self.assertEqual((await self.request("/api/quit", {}))[0], 400)
        self.assertEqual((await self.request("/api/session", {"id": "other"}))[0], 400)
        status, raw = await self.request("/api/session", {"id": "test"})
        self.assertEqual(status, 200)
        self.assertIn("token", json.loads(raw))
        self.assertEqual((await self.request("/api/stop", {}))[0], 200)
        self.assertEqual((await self.request("/api/quit", {}))[0], 200)

    async def test_save_stale_revision_and_invalid_config_fail_safely(self):
        before = profiles.revision("test")
        payload = {"id": "test", "revision": before, "config": {"name": "新名称"}}
        self.assertEqual((await self.request("/api/save", payload))[0], 200)
        self.assertEqual((await self.request("/api/save", payload))[0], 409)
        payload["revision"] = profiles.revision("test")
        payload["config"] = {"server_port": -1}
        self.assertEqual((await self.request("/api/save", payload))[0], 400)
        self.assertEqual(profiles.load("test")[0]["server_port"], 1)

    async def test_desktop_restart_requirement_has_actionable_response(self):
        with patch.object(self.manager.desktop, "start", new_callable=AsyncMock,
                          side_effect=ValueError("DESKTOP_QUIT_REQUIRED")) as start:
            status, raw = await self.request("/api/desktop/start", {"id": "test"})
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(raw)["code"], "DESKTOP_QUIT_REQUIRED")
            start.assert_awaited_once_with("test", "existing")

    @unittest.skipIf(os.name == "nt", "POSIX signal acceptance; Windows requires a real console")
    async def test_attach_parent_termination_cleans_child_but_keeps_resident(self):
        await self.manager.resident.start("test")
        profiles.atomic_json(profiles.ROOT / ".manager.json", {
            "origin": self.manager.origin, "token": self.manager.token,
        })
        ready = profiles.ROOT / "child.pid"
        child_code = "import os,time,pathlib; pathlib.Path(%r).write_text(str(os.getpid())); time.sleep(60)" % str(ready)
        code = (
            "import sys,pathlib; sys.path.insert(0,%r); import profiles,manager; "
            "profiles.ROOT=pathlib.Path(%r); sys.exit(manager.attach('test',%r))"
        ) % (str(Path(manager.__file__).parent), str(profiles.ROOT), [sys.executable, "-c", child_code])
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", code,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE)
        child_pid = None
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and process.returncode is None and time.monotonic() < deadline:
                await asyncio.sleep(.02)
            self.assertTrue(ready.exists(), "attachment child did not start")
            child_pid = int(ready.read_text())
            process.send_signal(signal.SIGTERM)
            _, error = await asyncio.wait_for(process.communicate(), 8)
            self.assertEqual(process.returncode, 143, error.decode(errors="replace"))
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertEqual(self.manager.resident.snapshot()["state"], "waiting")
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            if child_pid:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

