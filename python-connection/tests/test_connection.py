import asyncio
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import signal
import ssl
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import profiles
import relay
import routing
import runner


def config(port=1):
    return {
        "server_ip": "127.0.0.1",
        "server_port": port,
        "server_name": "localhost",
        "interface": "",
        "default": "proxy",
        "proxy": [],
        "direct": [],
        "block": [],
        "company_dns": {"domains": [], "servers": []},
        "china_routing": {"enabled": False},
    }


class StoreTests(unittest.TestCase):
    def test_legacy_import_preserves_source_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="连接 包 ' ") as tmp:
            root = Path(tmp)
            source = root / "old"
            source.mkdir()
            c = config()
            c["interface"] = "en0"
            profiles.atomic_json(source / "config.json", c)
            profiles.atomic_json(
                source / "credentials.json", {"username": "test", "password": "secret"}
            )
            before = (source / "config.json").read_bytes()
            with patch.object(profiles, "ROOT", root / "profiles"):
                profiles.import_legacy(source, "imported")
                current, _, _ = profiles.load("imported")
                self.assertEqual(current["interface"], "")
                self.assertEqual(profiles.list_profiles(), ["imported"])
                with self.assertRaises(ValueError):
                    profiles.import_legacy(source, "imported")
                with self.assertRaises(ValueError):
                    profiles.directory("../escape")
            self.assertEqual(before, (source / "config.json").read_bytes())

    def test_environment_is_child_only_and_clears_all_stale_proxy_variants(self):
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "old",
                "https_proxy": "old2",
                "NO_PROXY": "*",
                "WSS_PROXY": "old3",
            },
        ):
            env = runner.child_environment("new-token", 12345)
            self.assertEqual(env["HTTP_PROXY"], env["https_proxy"])
            self.assertNotIn("*", env["NO_PROXY"])
            self.assertEqual(os.environ["HTTP_PROXY"], "old")

    def test_windows_native_and_npm_shims_without_shell_interpolation(self):
        for name, package in [
            ("codex", "@openai/codex"),
            ("claude", "@anthropic-ai/claude-code"),
        ]:
            with tempfile.TemporaryDirectory(prefix="用户 项目 ' ") as tmp:
                root = Path(tmp)
                package_root = root / "node_modules" / package
                package_root.mkdir(parents=True)
                (package_root / "entry.js").write_text("")
                (package_root / "package.json").write_text(
                    json.dumps({"bin": {name: "entry.js"}})
                )
                mapping = {
                    name + ".cmd": str(root / (name + ".cmd")),
                    "node.exe": "node.exe",
                }
                with patch.object(runner, "WINDOWS", True), patch.object(
                    runner.shutil, "which", side_effect=mapping.get
                ):
                    argv = runner.child_argv([name, 'hello & $x " world'])
                    self.assertEqual(
                        argv,
                        [
                            "node.exe",
                            str((package_root / "entry.js").resolve()),
                            'hello & $x " world',
                        ],
                    )
                mapping[name + ".exe"] = str(root / (name + ".exe"))
                with patch.object(runner, "WINDOWS", True), patch.object(
                    runner.shutil, "which", side_effect=mapping.get
                ):
                    self.assertEqual(
                        runner.child_argv([name])[0], mapping[name + ".exe"]
                    )


class CliIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_session_cannot_attach_to_existing_daemon(self):
        probe = AsyncMock()
        probe.returncode = 0
        probe.communicate.return_value = (b"Options: --no-daemon", b"")
        with patch.object(
            runner, "child_argv", side_effect=lambda x: list(x)
        ), patch.object(
            runner.asyncio, "create_subprocess_exec", return_value=probe
        ) as spawn:
            args = ["codex", "--model", "test-model", "hello world"]
            self.assertEqual(
                await runner.isolated_child_argv(args),
                ["codex", "--no-daemon", *args[1:], "-c", "features.respect_system_proxy=false", "-c", "features.system_proxy_fallback=false"],
            )
            self.assertEqual(
                (await runner.isolated_child_argv(["codex", "--no-daemon"])).count(
                    "--no-daemon"
                ),
                1,
            )
            with self.assertRaisesRegex(relay.ConnectionFailure, "CLI_ISOLATION"):
                await runner.isolated_child_argv(["codex", "--remote", "unix://"])
            probe.communicate.return_value = (b"Legacy CLI without isolation", b"")
            with self.assertRaisesRegex(relay.ConnectionFailure, "CLI_ISOLATION"):
                await runner.isolated_child_argv(["codex"])
            spawn.reset_mock()
            self.assertEqual(
                await runner.isolated_child_argv(["claude", "-p", "hello"]),
                ["claude", "-p", "hello"],
            )
            spawn.assert_not_called()

    async def test_windows_npm_codex_probes_and_runs_same_entry(self):
        probe = AsyncMock()
        probe.returncode = 0
        probe.communicate.return_value = (b"--no-daemon", b"")
        resolve = lambda x: ["node.exe", "C:/Space Path/codex.js", *x[1:]]
        with patch.object(runner, "child_argv", side_effect=resolve), patch.object(
            runner.asyncio, "create_subprocess_exec", return_value=probe
        ) as spawn:
            result = await runner.isolated_child_argv(["codex.cmd", "--model", "test"])
            self.assertEqual(
                result,
                [
                    "node.exe",
                    "C:/Space Path/codex.js",
                    "--no-daemon",
                    "--model",
                    "test", "-c", "features.respect_system_proxy=false",
                    "-c", "features.system_proxy_fallback=false",
                ],
            )
            self.assertEqual(
                spawn.call_args.args, ("node.exe", "C:/Space Path/codex.js", "--help")
            )


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_all_skips_local_dns_preserves_rules_and_blocks(self):
        c = config()
        c.update(routing_mode="proxy_all", direct=["192.168.0.0/16", "*.direct.test"],
                 block=["blocked.test"], company_dns={"domains": ["*.company.test"], "servers": ["10.0.0.1"]})
        router = routing.Router(c, Path("."), None)
        with patch.object(router, "lookup", new_callable=AsyncMock, side_effect=AssertionError("DNS must not run")) as lookup:
            for host in ["192.168.1.2", "x.direct.test", "x.company.test", "example.org"]:
                self.assertEqual(await router.resolve_route(host), ("proxy", None))
            self.assertEqual(await router.resolve_route("blocked.test"), ("block", None))
            lookup.assert_not_called()
        c["routing_mode"] = "rules"
        self.assertEqual(await router.resolve_route("192.168.1.2"), ("direct", "192.168.1.2"))
        self.assertEqual(c["company_dns"]["servers"], ["10.0.0.1"])

    async def test_unknown_mode_and_boolean_port_rejected(self):
        for change in [{"routing_mode": "bad"}, {"server_port": True}]:
            with self.assertRaises(ValueError):
                profiles.validate(dict(config(), **change))

    async def test_priority_and_private_dns_fail_closed(self):
        c = config()
        c.update(
            block=["blocked.example"],
            proxy=["proxy.example"],
            direct=["*.example", "10.0.0.0/8"],
        )
        lookup = lambda *_: "10.0.0.10"
        router = routing.Router(c, Path("."), lookup)
        self.assertEqual(await router.resolve_route("blocked.example"), ("block", None))
        self.assertEqual(await router.resolve_route("proxy.example"), ("proxy", None))
        self.assertEqual(
            await router.resolve_route("foo.example"), ("direct", "10.0.0.10")
        )
        self.assertEqual(await router.resolve_route("10.1.1.2"), ("direct", "10.1.1.2"))
        self.assertEqual(await router.resolve_route("external.test"), ("proxy", None))
        c["company_dns"] = {"domains": ["*.company.test"], "servers": ["10.0.0.53"]}
        with patch.object(
            routing, "query_private_dns", side_effect=OSError("offline")
        ) as private:
            with self.assertRaises(OSError):
                await router.resolve_route("host.company.test")
            private.assert_called_once()

    async def test_cn_lists_and_disabled_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "cn-domains.txt").write_text("+.example.cn\n")
            (base / "cn-ip.txt").write_text("1.0.1.0/24\n")
            c = config()
            c["china_routing"] = {
                "enabled": True,
                "domains_file": "cn-domains.txt",
                "ip_file": "cn-ip.txt",
            }
            router = routing.Router(c, base, lambda *_: "1.0.1.2")
            self.assertEqual(
                await router.resolve_route("a.example.cn"), ("direct", "1.0.1.2")
            )
            self.assertEqual(
                await router.resolve_route("1.0.1.3"), ("direct", "1.0.1.3")
            )
            c["china_routing"]["enabled"] = False
            router = routing.Router(c, base, None)
            self.assertEqual(
                await router.resolve_route("a.example.cn"), ("proxy", None)
            )


class RelayTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        base = Path(cls.temp.name)
        cls.cert, cls.key = base / "cert.pem", base / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(cls.key),
                "-out",
                str(cls.cert),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def asyncSetUp(self):
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert, self.key)
        self.context = ssl.create_default_context(cafile=str(self.cert))
        self.context_patch = patch.object(relay, "CTX", self.context)
        self.context_patch.start()
        self.connections = 0
        self.server = await asyncio.start_server(
            self.ingress, "127.0.0.1", 0, ssl=server_context
        )
        self.c = config(self.server.sockets[0].getsockname()[1])
        self.creds = {"username": "test", "password": "test-password"}

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        self.context_patch.stop()

    async def ingress(self, reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            self.connections += 1
            if b"Basic " + base64.b64encode(b"test:test-password") not in head:
                writer.write(b"HTTP/1.1 407 Unauthorized\r\n\r\n")
            else:
                writer.write(b"HTTP/1.1 200 OK\r\n\r\n")
                await writer.drain()
                while chunk := await reader.read(1024):
                    writer.write(chunk)
                    await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            await relay.close(writer)

    async def test_authenticated_tls_and_local_auth_streaming(self):
        proxy = relay.Relay(self.c, self.creds)
        server = await asyncio.start_server(proxy.accept, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"CONNECT target.test:443 HTTP/1.1\r\n\r\n")
            self.assertIn(b"407", await r.readuntil(b"\r\n\r\n"))
            await relay.close(w)
            self.assertEqual(self.connections, 0)
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(
                f"CONNECT target.test:443 HTTP/1.1\r\nProxy-Authorization: {proxy.local_auth}\r\n\r\n".encode()
            )
            self.assertIn(b"200", await r.readuntil(b"\r\n\r\n"))
            for chunk in [b"first-token", b"next-token", b"last-token"]:
                w.write(chunk)
                await w.drain()
                self.assertEqual(await r.readexactly(len(chunk)), chunk)
            await relay.close(w)
            self.assertEqual(proxy.stats["proxy"], 1)
            self.assertTrue(proxy.stats["tls_versions"])
        finally:
            server.close()
            await server.wait_closed()
            for task in list(proxy.tasks):
                task.cancel()
            await asyncio.gather(*list(proxy.tasks), return_exceptions=True)

    async def test_direct_http_strips_local_credentials(self):
        received = asyncio.get_running_loop().create_future()

        async def origin(reader, writer):
            try:
                head = await reader.readuntil(b"\r\n\r\n")
                received.set_result(head)
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
                )
                await writer.drain()
            finally:
                await relay.close(writer)

        origin_server = await asyncio.start_server(origin, "127.0.0.1", 0)
        origin_port = origin_server.sockets[0].getsockname()[1]
        proxy = relay.Relay(dict(self.c, direct=["127.0.0.0/8"]), self.creds)
        server = await asyncio.start_server(proxy.accept, "127.0.0.1", 0)
        try:
            r, w = await asyncio.open_connection(
                "127.0.0.1", server.sockets[0].getsockname()[1]
            )
            w.write(
                (
                    f"GET http://127.0.0.1:{origin_port}/test HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    f"Proxy-Authorization: {proxy.local_auth}\r\nConnection: keep-alive\r\n\r\n"
                ).encode()
            )
            await w.drain()
            self.assertIn(b"200 OK", await r.read())
            head = await received
            self.assertNotIn(b"Proxy-Authorization", head)
            self.assertIn(b"Connection: close", head)
            self.assertTrue(head.startswith(b"GET /test HTTP/1.1"))
            self.assertEqual(proxy.stats["direct"], 1)
            self.assertEqual(self.connections, 0)
            await relay.close(w)
        finally:
            server.close()
            origin_server.close()
            await server.wait_closed()
            await origin_server.wait_closed()

    async def test_wrong_credentials_do_not_launch_child_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "never.txt"
            with self.assertRaisesRegex(relay.ConnectionFailure, "UPSTREAM_AUTH"):
                await runner.execute(
                    [sys.executable, "-c", f'open({str(marker)!r},"w").write("bad")'],
                    self.c,
                    {"username": "test", "password": "wrong"},
                    Path(tmp),
                )
            self.assertFalse(marker.exists())

    async def test_certificate_mismatch_fails_closed(self):
        c = dict(self.c, server_name="wrong.test")
        with self.assertRaisesRegex(relay.ConnectionFailure, "TLS_CERTIFICATE"):
            await relay.upstream(c, "Basic unused", "target.test", 443)

    async def test_ipv6_upstream_still_requires_tls(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)
        try:
            server = await asyncio.start_server(self.ingress, "::1", 0, ssl=ctx)
        except OSError:
            self.skipTest("IPv6 loopback unavailable")
        try:
            c = dict(
                self.c, server_ip="::1", server_port=server.sockets[0].getsockname()[1]
            )
            auth = "Basic " + base64.b64encode(b"test:test-password").decode()
            _, writer = await relay.upstream(c, auth, "target.test", 443)
            self.assertIsNotNone(writer.get_extra_info("ssl_object"))
            await relay.close(writer)
        finally:
            server.close()
            await server.wait_closed()

    @unittest.skipIf(
        sys.platform == "win32",
        "POSIX signal test; Windows job requires native validation",
    )
    async def test_interrupt_stops_child_and_listener(self):
        with tempfile.TemporaryDirectory(prefix="连接 中断 ") as tmp:
            base = Path(tmp)
            script = base / "worker.py"
            ready = base / "ready"
            command = (
                "import os,time; from pathlib import Path; Path("
                + repr(str(ready))
                + ').write_text(os.environ["HTTP_PROXY"]); time.sleep(60)'
            )
            script.write_text(
                "import sys; from pathlib import Path; sys.path.insert(0, "
                + repr(str(Path(runner.__file__).parent))
                + ")\n"
                + "import asyncio,runner\nasyncio.run(runner.execute("
                + repr([sys.executable, "-c", command])
                + ","
                + repr(self.c)
                + ","
                + repr(self.creds)
                + ",Path("
                + repr(str(base))
                + ")))\n",
                encoding="utf-8",
            )
            env = dict(os.environ, SSL_CERT_FILE=str(self.cert))
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                for _ in range(100):
                    if ready.exists():
                        break
                    await asyncio.sleep(0.05)
                self.assertTrue(ready.exists(), "child did not start")
                from urllib.parse import urlsplit

                port = urlsplit(ready.read_text()).port
                proc.send_signal(signal.SIGINT)
                await asyncio.wait_for(proc.communicate(), 8)
                with self.assertRaises(OSError):
                    await asyncio.open_connection("127.0.0.1", port)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

    async def test_parallel_sessions_use_distinct_ports_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="中文 ' ") as tmp:

            async def session(index):
                path = Path(tmp) / f"env{index}.json"
                code = (
                    "import os,json,time; from pathlib import Path; Path("
                    + repr(str(path))
                    + ').write_text(json.dumps({k:os.environ[k] for k in ["HTTP_PROXY","HTTPS_PROXY","NO_PROXY"]})); time.sleep(.1)'
                )
                result = await runner.execute(
                    [sys.executable, "-c", code], self.c, self.creds, Path(tmp)
                )
                self.assertEqual(result, 0)
                return json.loads(path.read_text())

            with patch.object(runner, "own_windows_process_tree"):
                one, two = await asyncio.gather(session(1), session(2))
            from urllib.parse import urlsplit

            first, second = urlsplit(one["HTTP_PROXY"]), urlsplit(two["HTTP_PROXY"])
            self.assertNotEqual(first.port, second.port)
            self.assertNotEqual(first.password, second.password)
            for port in (first.port, second.port):
                with self.assertRaises(OSError):
                    await asyncio.open_connection("127.0.0.1", port)


if __name__ == "__main__":
    unittest.main()
