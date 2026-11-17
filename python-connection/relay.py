#!/usr/bin/env python3
"""Scoped terminal proxy. No global routes, TUN, login items, or system proxy edits."""

from routing import Router
import asyncio
import base64
import hmac
import http.client
import ipaddress
import json
import pathlib
import secrets
import socket
import ssl
import sys
import time
import urllib.parse

BASE = pathlib.Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
CTX = ssl.create_default_context()
CTX.minimum_version = ssl.TLSVersion.TLSv1_2
CTX.set_alpn_protocols(["http/1.1"])


def doh(host, interface):
    conn = http.client.HTTPSConnection("dns.alidns.com", timeout=8, context=CTX)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(8)
    try:
        if sys.platform == "darwin" and interface:
            s.setsockopt(socket.IPPROTO_IP, 25, socket.if_nametoindex(interface))
        s.connect(("223.5.5.5", 443))
        conn.sock = CTX.wrap_socket(s, server_hostname="dns.alidns.com")
        conn.request(
            "GET", "/resolve?" + urllib.parse.urlencode({"name": host, "type": "A"})
        )
        resp = conn.getresponse()
        if resp.status != 200:
            raise OSError("Direct DNS lookup failed")
        data = json.loads(resp.read(65536))
        for answer in data.get("Answer", []):
            if answer.get("type") == 1:
                return str(ipaddress.IPv4Address(answer["data"]))
        raise OSError("No direct IPv4 address")
    finally:
        conn.close()
        s.close()


async def socket_open(ip, port, interface="", tls_host=None):
    addr = ipaddress.ip_address(ip)
    s = socket.socket(
        socket.AF_INET6 if addr.version == 6 else socket.AF_INET, socket.SOCK_STREAM
    )
    s.setblocking(False)
    try:
        if sys.platform == "darwin" and interface and not addr.is_loopback:
            level, opt = (
                (socket.IPPROTO_IPV6, 125)
                if addr.version == 6
                else (socket.IPPROTO_IP, 25)
            )
            s.setsockopt(level, opt, socket.if_nametoindex(interface))
        await asyncio.wait_for(
            asyncio.get_running_loop().sock_connect(s, (ip, port)), 12
        )
        kw = {"sock": s}
        if tls_host:
            kw.update(ssl=CTX, server_hostname=tls_host, ssl_handshake_timeout=12)
        return await asyncio.open_connection(**kw)
    except BaseException:
        s.close()
        raise


class ConnectionFailure(Exception):
    pass


async def upstream(c, auth, host, port):
    remote = None
    try:
        try:
            rr, remote = await socket_open(
                c["server_ip"],
                c["server_port"],
                c.get("interface", ""),
                c["server_name"],
            )
        except ssl.SSLError:
            raise ConnectionFailure(
                "TLS_CERTIFICATE: 请检查服务器名称、证书和系统时间"
            ) from None
        except (OSError, asyncio.TimeoutError):
            raise ConnectionFailure(
                "UPSTREAM_TCP_TLS: 加密入口连接失败或超时"
            ) from None
        target = (f"[{host}]" if ":" in host else host) + ":" + str(port)
        remote.write(
            f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\nProxy-Authorization: {auth}\r\n\r\n".encode()
        )
        await remote.drain()
        try:
            reply = await asyncio.wait_for(rr.readuntil(b"\r\n\r\n"), 25)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            raise ConnectionFailure("UPSTREAM_RESPONSE: 加密入口未完成响应") from None
        status = reply.split(b" ", 2)[1]
        if status == b"407":
            raise ConnectionFailure("UPSTREAM_AUTH: 代理凭据未通过，请检查所选方案")
        if status != b"200":
            raise ConnectionFailure("UPSTREAM_CONNECT: 入口拒绝连接或出口不可用")
        return rr, remote
    except BaseException:
        await close(remote)
        raise


async def close(w):
    if w:
        w.close()
        try:
            await asyncio.wait_for(w.wait_closed(), 2)
        except Exception:
            pass


async def pump(r, w, on_data=None):
    while True:
        # Silence can mean model reasoning or tool execution, not an unused
        # connection. The owner closes this stream on EOF/cancel/shutdown.
        data = await r.read(65536)
        if not data:
            return
        w.write(data)
        await w.drain()
        if on_data:
            on_data(len(data))


class Relay:
    def __init__(self, c, creds, base=BASE):
        self.c = c
        self.auth = (
            "Basic "
            + base64.b64encode(
                (creds.get("username", "") + ":" + creds.get("password", "")).encode()
            ).decode()
        )
        self.node_transport = None
        if c.get("connection_type") == "node":
            from nodes import NodeTransport
            self.node_transport = NodeTransport(creds["node"], c.get("interface", ""))
        self.token = secrets.token_urlsafe(24)
        self.local_auth = (
            "Basic " + base64.b64encode(("local:" + self.token).encode()).decode()
        )
        self.stats = {
            "proxy": 0,
            "direct": 0,
            "blocked": 0,
            "failed": 0,
            "tls_versions": [],
        }
        self.tasks = set()
        self.cache = {}
        self.router = Router(c, base, doh)
        self.active = 0
        self.upload_bytes = 0
        self.download_bytes = 0
        self.last_activity = None
        self.last_error = None
        self.auth_rejections = 0

    async def upstream(self, host, port):
        if self.node_transport:
            try:
                return await self.node_transport.open(host, port)
            except ssl.SSLError:
                raise ConnectionFailure("NODE_TLS: 节点证书验证失败") from None
            except ImportError:
                raise ConnectionFailure("NODE_COMPONENTS: 请安装节点支持组件") from None
            except Exception:
                raise ConnectionFailure("NODE_CONNECT: 节点连接失败，未转为直连") from None
        return await upstream(self.c, self.auth, host, port)

    async def shutdown(self):
        if self.node_transport:
            await self.node_transport.close()

    def transferred(self, direction, count):
        if direction == "upload":
            self.upload_bytes += count
        else:
            self.download_bytes += count
        self.last_activity = time.time()

    def snapshot(self):
        recent = self.last_activity and time.time() - self.last_activity < 3
        return {
            "state": "transferring" if self.active and recent else (
                "connected" if self.active else "waiting"
            ),
            "active_connections": self.active,
            "pending_connections": len(self.tasks) - self.active,
            "upload_bytes": self.upload_bytes,
            "download_bytes": self.download_bytes,
            "last_activity": self.last_activity,
            "last_error": self.last_error,
            "auth_rejections": self.auth_rejections,
            "counts": dict(self.stats, tls_versions=list(self.stats["tls_versions"])),
        }

    async def accept(self, r, w):
        task = asyncio.current_task()
        self.tasks.add(task)
        remote = None
        parts = []
        pipes = []
        sent = False
        stage = "LOCAL_REQUEST"
        connected = False
        try:
            head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 10)
            lines = head.decode("iso-8859-1").split("\r\n")
            parts = lines[0].split()
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.lower()] = v.strip()
            if not hmac.compare_digest(
                headers.get("proxy-authorization", ""), self.local_auth
            ):
                self.auth_rejections += 1
                w.write(
                    b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="Local"\r\nContent-Length: 0\r\n\r\n'
                )
                await w.drain()
                return
            if len(parts) != 3:
                raise ValueError("Invalid request")
            tunnel = parts[0] == "CONNECT"
            u = urllib.parse.urlsplit(("https://" if tunnel else "") + parts[1])
            host = (u.hostname or "").lower().rstrip(".")
            port = u.port or (443 if tunnel else 80)
            if not host or (not tunnel and u.scheme != "http"):
                raise ValueError("Unsupported request")
            stage = "ROUTING_DNS"
            action, ip = await self.router.resolve_route(host)
            if action == "block":
                self.stats["blocked"] += 1
                raise PermissionError("Blocked by local rule")
            if action == "direct":
                stage = "DIRECT_CONNECT"
                rr, remote = await socket_open(ip, port, self.c.get("interface", ""))
                self.stats["direct"] += 1
            else:
                stage = "UPSTREAM"
                rr, remote = await self.upstream(host, port)
                tls = remote.get_extra_info("ssl_object")
                v = tls.version() if tls else None
                if v and v not in self.stats["tls_versions"]:
                    self.stats["tls_versions"].append(v)
                self.stats["proxy"] += 1
            self.active += 1
            connected = True
            self.last_error = None
            if tunnel:
                w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await w.drain()
                sent = True
            else:
                path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
                new = [f"{parts[0]} {path} {parts[2]}"] + [
                    l
                    for l in lines[1:]
                    if l
                    and l.split(":", 1)[0].lower()
                    not in ["proxy-authorization", "proxy-connection", "connection"]
                ]
                new.append("Connection: close")
                remote.write(("\r\n".join(new) + "\r\n\r\n").encode("iso-8859-1"))
                await remote.drain()
                sent = True
            pipes = [
                asyncio.create_task(pump(r, remote, lambda n: self.transferred("upload", n))),
                asyncio.create_task(pump(rr, w, lambda n: self.transferred("download", n))),
            ]
            done, _ = await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                finished.result()
        except Exception as exc:
            # Store only a stage/code, never the target, URL or exception payload.
            self.last_error = str(exc).split(":", 1)[0] if isinstance(exc, ConnectionFailure) else stage
            print(
                "[connection] "
                + (
                    str(exc)
                    if isinstance(exc, ConnectionFailure)
                    else stage + ": " + type(exc).__name__
                ),
                file=sys.stderr,
                flush=True,
            )
            self.stats["failed"] += 1
            if not sent:
                try:
                    w.write(
                        b"HTTP/1.1 502 Proxy connection failed\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    )
                    await w.drain()
                except Exception:
                    pass
        finally:
            if connected:
                self.active -= 1
            for p in pipes:
                p.cancel()
            if pipes:
                await asyncio.gather(*pipes, return_exceptions=True)
            await close(remote)
            await close(w)
            self.tasks.discard(task)
