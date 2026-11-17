"""Per-proxy-request CN routing and private DNS. Does not alter system DNS/routes."""

import asyncio
import bisect
import fnmatch
import ipaddress
import secrets
import socket
import struct
import time


def matches(host, pattern):
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network(pattern, strict=False)
    except ValueError:
        return fnmatch.fnmatchcase(host, pattern.lower()) or (
            pattern.startswith("*.") and host == pattern[2:].lower()
        )


def dns_name(data, pos):
    labels, end, visited = [], None, set()
    while True:
        if pos in visited or pos >= len(data):
            raise ValueError("Invalid DNS name")
        visited.add(pos)
        n = data[pos]
        if n & 0xC0 == 0xC0:
            if pos + 1 >= len(data):
                raise ValueError("Truncated DNS pointer")
            if end is None:
                end = pos + 2
            pos = ((n & 63) << 8) | data[pos + 1]
            continue
        if n & 0xC0 or n > 63 or pos + 1 + n > len(data):
            raise ValueError("Invalid DNS label")
        pos += 1
        if not n:
            return ".".join(labels).lower(), end if end is not None else pos
        labels.append(data[pos : pos + n].decode("ascii"))
        pos += n


def parse_dns(data, ident, hostname):
    if len(data) < 12:
        raise ValueError("Truncated DNS reply")
    tx, flags, qd, an, _, _ = struct.unpack("!6H", data[:12])
    if tx != ident or not flags & 0x8000 or flags & 0x7800 or flags & 15 or qd != 1:
        raise OSError("DNS reply rejected")
    question, pos = dns_name(data, 12)
    if question != hostname or data[pos : pos + 4] != struct.pack("!HH", 1, 1):
        raise OSError("DNS question mismatch")
    pos += 4
    if flags & 0x0200:
        return None
    addresses, aliases, ttls = {}, {}, []
    for _ in range(an):
        owner, pos = dns_name(data, pos)
        typ, cls, ttl, size = struct.unpack("!HHIH", data[pos : pos + 10])
        pos += 10
        if pos + size > len(data):
            raise ValueError("Truncated DNS record")
        if cls == 1 and typ == 1 and size == 4:
            addresses.setdefault(owner, []).append(
                str(ipaddress.IPv4Address(data[pos : pos + size]))
            )
            ttls.append(ttl)
        elif cls == 1 and typ == 5:
            aliases[owner] = dns_name(data, pos)[0]
            ttls.append(ttl)
        pos += size
    current, seen = hostname, set()
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return addresses.get(current, []), current, min(ttls or [30])


def recv_exact(sock, n):
    result = b""
    while len(result) < n:
        chunk = sock.recv(n - len(result))
        if not chunk:
            raise OSError("DNS TCP connection closed")
        result += chunk
    return result


def query_private_dns(hostname, server, port=53, timeout=1.5):
    """Use only this explicitly selected resolver, including all CNAME hops."""
    current, seen, min_ttl = hostname.encode("idna").decode("ascii").lower(), set(), 300
    for _ in range(8):
        if current in seen:
            raise OSError("DNS alias loop")
        seen.add(current)
        ident = secrets.randbelow(65536)
        labels = current.split(".")
        if any(not x or len(x) > 63 for x in labels):
            raise ValueError("Invalid DNS hostname")
        question = (
            b"".join(bytes([len(x)]) + x.encode("ascii") for x in labels)
            + b"\0"
            + struct.pack("!HH", 1, 1)
        )
        packet = struct.pack("!6H", ident, 0x100, 1, 0, 0, 0) + question
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            # A connected UDP socket accepts replies only from the specified resolver.
            sock.connect((server, port))
            sock.send(packet)
            parsed = parse_dns(sock.recv(65535), ident, current)
        if parsed is None:
            with socket.create_connection((server, port), timeout=timeout) as sock:
                sock.sendall(struct.pack("!H", len(packet)) + packet)
                data = recv_exact(sock, struct.unpack("!H", recv_exact(sock, 2))[0])
                parsed = parse_dns(data, ident, current)
            if parsed is None:
                raise OSError("Truncated TCP DNS reply")
        ips, canonical, ttl = parsed
        min_ttl = min(min_ttl, ttl)
        if ips:
            return ips[0], max(1, min_ttl)
        if canonical == current:
            raise OSError("No company IPv4 answer")
        current = canonical
    raise OSError("Too many DNS aliases")


class Router:
    def __init__(self, config, base, public_lookup):
        self.c, self.public_lookup = config, public_lookup
        self.cache = {}
        self.exact, self.suffixes = set(), set()
        self.ranges, self.starts = {}, {}
        cn = config.get("china_routing", {})
        self.enabled = bool(cn.get("enabled", False))
        if self.enabled:
            for line in (base / cn["domains_file"]).read_text().splitlines():
                line = line.strip().lower()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("+."):
                    self.suffixes.add(line[2:])
                elif "*" in line or "?" in line:
                    raise ValueError("Unsupported CN domain rule")
                else:
                    self.exact.add(line)
            networks = [
                ipaddress.ip_network(x.strip(), strict=False)
                for x in (base / cn["ip_file"]).read_text().splitlines()
                if x.strip() and not x.strip().startswith("#")
            ]
            for version in [4, 6]:
                spans = sorted(
                    (int(n.network_address), int(n.broadcast_address))
                    for n in networks
                    if n.version == version
                )
                merged = []
                for start, end in spans:
                    if merged and start <= merged[-1][1] + 1:
                        merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                    else:
                        merged.append((start, end))
                self.ranges[version] = merged
                self.starts[version] = [x[0] for x in merged]
            if not self.suffixes or not self.ranges[4]:
                raise ValueError("Empty CN rule database")

    def company(self, host):
        return any(
            matches(host, p) for p in self.c.get("company_dns", {}).get("domains", [])
        )

    def cn_domain(self, host):
        if host in self.exact:
            return True
        labels = host.split(".")
        return any(".".join(labels[i:]) in self.suffixes for i in range(len(labels)))

    def cn_ip(self, value):
        if not self.enabled:
            return False
        ip = ipaddress.ip_address(value)
        i = bisect.bisect_right(self.starts[ip.version], int(ip)) - 1
        return i >= 0 and int(ip) <= self.ranges[ip.version][i][1]

    async def lookup(self, host):
        cached = self.cache.get(host)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        if self.company(host):
            answer = None
            for server in self.c["company_dns"]["servers"]:
                try:
                    answer, ttl = await asyncio.to_thread(
                        query_private_dns, host, server
                    )
                    break
                except (OSError, ValueError, struct.error):
                    continue
            if answer is None:
                # No public/system-DNS fallback for private corporate names.
                raise OSError("Company DNS unavailable")
        elif host == "localhost" or host.endswith(".localhost"):
            answer, ttl = "127.0.0.1", 60
        elif host.endswith(".local") or "." not in host:
            results = await asyncio.get_running_loop().getaddrinfo(
                host, None, family=socket.AF_INET, type=socket.SOCK_STREAM
            )
            answer, ttl = results[0][4][0], 60
        else:
            answer, ttl = (
                await asyncio.to_thread(self.public_lookup, host, self.c["interface"]),
                60,
            )
        if len(self.cache) > 4096:
            self.cache.clear()
        self.cache[host] = answer, time.monotonic() + ttl
        return answer

    async def resolve_route(self, host):
        host = host.lower().rstrip(".").encode("idna").decode("ascii")
        if self.c.get("routing_mode", "rules") == "proxy_all":
            # Keep explicit blocks, but never resolve destination names locally.
            # The saved direct/company rules remain intact for switching back.
            action = "block" if any(matches(host, p) for p in self.c.get("block", [])) else "proxy"
            return action, None
        try:
            literal = str(ipaddress.ip_address(host))
        except ValueError:
            literal = None
        action = None
        for kind in ["block", "proxy", "direct"]:
            if any(matches(host, p) for p in self.c.get(kind, [])):
                action = kind
                break
        if action is None and self.company(host):
            action = "direct"
        if action is None and self.enabled:
            if literal:
                action = (
                    "direct" if self.cn_ip(literal) else self.c.get("default", "proxy")
                )
            elif self.cn_domain(host):
                action = "direct"
            else:
                try:
                    resolved = await self.lookup(host)
                except OSError:
                    resolved = None
                if resolved:
                    for kind in ["block", "proxy", "direct"]:
                        if any(matches(resolved, p) for p in self.c.get(kind, [])):
                            return kind, resolved if kind == "direct" else None
                    if self.cn_ip(resolved):
                        return "direct", resolved
        action = action or self.c.get("default", "proxy")
        if action == "direct":
            return action, literal or await self.lookup(host)
        return action, None
