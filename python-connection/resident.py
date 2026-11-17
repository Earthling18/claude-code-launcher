"""Manually owned loopback proxy; no system settings or autostart changes."""

import asyncio
import time

import profiles
from relay import Relay


class Resident:
    def __init__(self):
        self.server = None
        self.relay = None
        self.profile = None
        self.port = None
        self.started_at = None

    async def start(self, profile, port=0):
        if self.server:
            raise ValueError("请先停止当前常驻连接；不会中途切换正在使用的方案")
        c, creds, base = profiles.load(profile)
        relay = Relay(c, creds, base)
        # Deliberately no preflight: waiting must not itself produce traffic.
        server = await asyncio.start_server(relay.accept, "127.0.0.1", port, limit=32768)
        self.server, self.relay = server, relay
        self.profile = profile
        self.port = server.sockets[0].getsockname()[1]
        self.started_at = time.time()
        return self.snapshot()

    async def stop(self):
        if self.server:
            self.server.close()
            tasks = list(self.relay.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.server.wait_closed()
            await self.relay.shutdown()
        self.server = self.relay = None
        self.port = self.profile = self.started_at = None

    def snapshot(self):
        if not self.server:
            return {"state": "stopped"}
        return dict(
            self.relay.snapshot(), profile=self.profile, port=self.port,
            started_at=self.started_at,
        )


