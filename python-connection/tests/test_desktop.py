import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop
import profiles
from test_connection import config


@unittest.skipIf(os.name == "nt", "Mac desktop adapter; Windows GUI not yet supported")
class DesktopLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="客户端 空格 ' ")
        self.root = Path(self.tmp.name)
        self.store = patch.object(profiles, "ROOT", self.root / "profiles")
        self.store.start()
        profiles.save("test", config(), {"username": "user", "password": "CLOUD_SECRET"})
        self.original = self.root / "original"; self.original.mkdir()
        profiles.atomic_json(self.original / "auth.json", {"test_only": "AUTH_SECRET"})
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.original), "HTTPS_PROXY": "http://old.invalid:9"})
        self.env.start()
        self.exe = self.root / "Fake Codex"
        self.exe.write_text('#!' + sys.executable + '\n'
            'import os,pathlib,time,json,sys\n'
            'home=pathlib.Path(os.environ["CODEX_HOME"])\n'
            '(home/"ready").write_text(json.dumps({"isolated":os.environ.get("CODEX_ELECTRON_USER_DATA_PATH", ""),"force_cli":os.environ["CODEX_APP_SERVER_FORCE_CLI"],"argv":sys.argv}))\n'
            'while not (home/"exit-now").exists(): time.sleep(.02)\n')
        self.exe.chmod(0o700)
        with patch.object(desktop, "discover", return_value={"available": True, "message": "test", "executable": str(self.exe)}):
            self.session = desktop.DesktopSession()

    async def asyncTearDown(self):
        await self.session.stop()
        self.env.stop(); self.store.stop(); self.tmp.cleanup()

    async def test_isolated_env_duplicate_guard_and_cleanup(self):
        before = (self.original / "auth.json").read_bytes()
        state = await self.session.start("test", "isolated")
        self.assertEqual(state["state"], "running")
        self.assertFalse(state["model_verified"])
        home = profiles.ROOT / ".desktop/test/codex-home"
        self.assertTrue((home / "ready").exists())
        self.assertIn('127.0.0.1', (home / ".env").read_text())
        self.assertNotIn('old.invalid', (home / ".env").read_text())
        self.assertEqual((home / ".env").stat().st_mode & 0o777, 0o600)
        self.assertEqual((home / "auth.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("SECRET", json.dumps(state))
        credential = await self.session.local_credential()
        self.assertNotEqual(credential["password"], "CLOUD_SECRET")
        self.assertNotIn(credential["password"], json.dumps(state))
        self.assertEqual(os.environ["HTTPS_PROXY"], "http://old.invalid:9")
        with self.assertRaises(ValueError):
            await self.session.start("test", "isolated")
        port = state["connection"]["port"]
        await self.session.stop()
        self.assertFalse((home / ".env").exists())
        self.assertTrue((home / "auth.json").exists())
        with self.assertRaises(ValueError):
            await self.session.local_credential()
        self.assertFalse((home.parent / "owner.json").exists())
        self.assertEqual(before, (self.original / "auth.json").read_bytes())
        with self.assertRaises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

    async def test_early_exit_releases_proxy_and_credentials(self):
        self.session.capability["executable"] = "/usr/bin/true"
        with self.assertRaisesRegex(ValueError, "EARLY_EXIT"):
            await self.session.start("test", "isolated")
        self.assertEqual(self.session.snapshot()["connection"]["state"], "stopped")
        self.assertIsNone(self.session.process)
        self.assertFalse((profiles.ROOT / ".desktop/test/codex-home/.env").exists())

    async def test_normal_app_exit_cleans_relay_and_preserves_login(self):
        await self.session.start("test", "isolated")
        home = profiles.ROOT / ".desktop/test/codex-home"
        (home / "exit-now").touch()
        await asyncio.wait_for(self.session.monitor, 5)
        self.assertEqual(self.session.snapshot()["state"], "stopped")
        self.assertEqual(self.session.snapshot()["connection"]["state"], "stopped")
        self.assertFalse((home / ".env").exists())
        self.assertTrue((home / "auth.json").exists())

    async def test_live_previous_owner_is_never_killed_or_reused(self):
        owner = profiles.ROOT / ".desktop/test/owner.json"
        profiles.atomic_json(owner, {"pid": os.getpid()})
        with self.assertRaisesRegex(ValueError, "PREVIOUS_WINDOW"):
            await self.session.start("test", "isolated")
        self.assertIsNone(self.session.process)
        self.assertIsNone(self.session.relay.server)

    async def test_default_reuses_home_without_writing_shared_settings(self):
        original_env = self.original / ".env"
        original_env.write_text("MY_SETTING=keep\n")
        original_config = self.original / "config.toml"
        original_config.write_text('model = "original-model"\n')
        before = {p.name: p.read_bytes() for p in self.original.iterdir()}
        with patch.object(desktop, "running_app_pids", new_callable=AsyncMock, return_value=[]):
            state = await self.session.start("test")
        self.assertEqual(state["mode"], "existing")
        ready = json.loads((self.original / "ready").read_text())
        self.assertEqual(ready["isolated"], "")
        self.assertFalse(any(x.startswith("--user-data-dir") for x in ready["argv"]))
        self.assertFalse((profiles.ROOT / ".desktop-live/codex-home").exists())
        await self.session.stop()
        for name, content in before.items():
            self.assertEqual((self.original / name).read_bytes(), content)

    async def test_existing_client_requires_user_quit_before_proxy_or_writes(self):
        with patch.object(desktop, "running_app_pids", new_callable=AsyncMock, return_value=[os.getpid()]):
            with self.assertRaisesRegex(ValueError, "DESKTOP_QUIT_REQUIRED"):
                await self.session.start("test")
        self.assertIsNone(self.session.process)
        self.assertIsNone(self.session.relay.server)
        self.assertFalse((profiles.ROOT / ".desktop-live").exists())


class DesktopDiscoveryTests(unittest.TestCase):
    def test_windows_does_not_claim_verified_gui_support(self):
        with patch.object(desktop.sys, "platform", "win32"):
            self.assertFalse(desktop.discover()["available"])
