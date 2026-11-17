"""Portable profile store. Only this tool reads/writes connection credentials."""

import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import hashlib

ROOT = Path(__file__).resolve().parent / "profiles"
PROFILE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def directory(profile):
    if not PROFILE_ID.fullmatch(profile):
        raise ValueError("方案 ID 只能包含字母、数字、横线和下划线")
    return ROOT / profile


def list_profiles():
    return sorted(
        p.name
        for p in ROOT.glob("*")
        if p.is_dir() and PROFILE_ID.fullmatch(p.name) and (
            (p / "config.json").is_file() or (p / "connection.json").is_file()
        )
    )


def labels():
    result = {}
    for ident in list_profiles():
        try:result[ident] = load(ident)[0].get("name") or ident
        except Exception:result[ident] = ident + "（需修复）"
    return result


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".save-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate(c):
    if c.get("routing_mode", "rules") not in ("rules", "proxy_all"):
        raise ValueError("分流模式无效")
    if c.get("connection_type", "cloud") not in ("cloud", "node"):
        raise ValueError("连接类型无效")
    if c.get("connection_type") == "node":
        validate_rules(c)
        return
    ipaddress.ip_address(c["server_ip"])
    if type(c["server_port"]) is not int or not 1 <= c["server_port"] <= 65535:
        raise ValueError("服务器端口无效")
    name = c.get("server_name", "")
    if not name or any(ch.isspace() or ch in "/\\\r\n" for ch in name):
        raise ValueError("TLS 证书名称无效")
    validate_rules(c)


def validate_rules(c):
    if c.get("default") not in ("proxy", "direct", "block"):
        raise ValueError("默认分流规则无效")
    for key in ("block", "proxy", "direct"):
        if not isinstance(c.get(key, []), list):
            raise ValueError("规则必须是列表")
        for rule in c.get(key, []):
            if not isinstance(rule, str) or not rule or any(x.isspace() for x in rule):
                raise ValueError("域名规则无效")
            if "/" in rule:
                ipaddress.ip_network(rule, strict=False)
    dns = c.get("company_dns", {})
    if dns.get("domains") and not dns.get("servers"):
        raise ValueError("公司域名必须同时指定公司 DNS")
    for server in dns.get("servers", []):
        ipaddress.IPv4Address(server)
    for domain in dns.get("domains", []):
        if (
            not isinstance(domain, str)
            or not domain
            or any(x.isspace() for x in domain)
        ):
            raise ValueError("公司域名规则无效")
    cn = c.get("china_routing", {})
    if cn.get("enabled"):
        for key in ("domains_file", "ip_file"):
            path = Path(cn[key])
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("国内规则文件必须位于方案目录内")


def load(profile):
    base = directory(profile)
    bundle = base / "connection.json"
    if not bundle.is_file() and not (base / "config.json").is_file():
        raise ValueError("方案不存在，请先在“管理连接与分流”中创建或导入旧包")
    if bundle.is_file():
        data = json.loads(bundle.read_text(encoding="utf-8-sig"))
        if data.get("version") != 1:
            raise ValueError("连接方案版本不支持")
        c, creds = data["config"], data["credentials"]
    else:
        c = json.loads((base / "config.json").read_text(encoding="utf-8-sig"))
        creds = json.loads((base / "credentials.json").read_text(encoding="utf-8-sig"))
    validate(c)
    # Automatic OS routing by default; old hard-coded en0 is not portable.
    c.setdefault("interface", "")
    if c.get("connection_type") == "node":
        from nodes import validate as validate_node
        validate_node(creds.get("node"))
        return c, creds, base
    if not all(
        isinstance(creds.get(k), str) and creds[k] for k in ("username", "password")
    ):
        raise ValueError("缺少代理凭据")
    if ":" in creds["username"] or any(
        ch in creds["username"] + creds["password"] for ch in "\r\n"
    ):
        raise ValueError("代理凭据格式无效")
    return c, creds, base


def revision(profile):
    c, creds, _ = load(profile)
    return hashlib.sha256(json.dumps([c, creds], sort_keys=True).encode()).hexdigest()


def save(profile, c, creds, expected_revision=None):
    """One commit for endpoint + credentials. Legacy files remain a rollback copy.

    The manager serializes saves. An expected revision rejects stale browser tabs.
    """
    base = directory(profile)
    if profile in list_profiles():
        if expected_revision != revision(profile):
            raise ValueError("方案已被修改，请重新载入后再保存")
    elif base.exists():
        raise ValueError("目标目录已存在，不会覆盖")
    validate(c)
    if c.get("connection_type") == "node":
        from nodes import validate as validate_node
        validate_node(creds.get("node"))
    elif not all(isinstance(creds.get(k), str) and creds[k] for k in ("username", "password")):
        raise ValueError("请填写用户名和密码")
    if c.get("connection_type") != "node" and (":" in creds["username"] or any(ch in creds["username"] + creds["password"] for ch in "\r\n")):
        raise ValueError("认证信息格式无效")
    if len(c.get("name", "")) > 80:
        raise ValueError("方案名称不能超过 80 个字符")
    from routing import Router
    Router(c, base, None)
    atomic_json(base / "connection.json", {"version": 1, "config": c, "credentials": creds})
    return revision(profile)


def import_legacy(source, profile):
    source = Path(source).expanduser().resolve()
    dest = directory(profile)
    if dest.exists():
        raise ValueError("方案已存在，请使用新的方案 ID；旧文件不会覆盖")
    c = json.loads((source / "config.json").read_text(encoding="utf-8-sig"))
    creds = json.loads((source / "credentials.json").read_text(encoding="utf-8-sig"))
    c["interface"] = ""
    validate(c)
    ROOT.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".import-", dir=ROOT))
    try:
        cn = c.get("china_routing", {})
        if cn.get("enabled"):
            for key in ("domains_file", "ip_file"):
                rel = Path(cn[key])
                origin = (source / rel).resolve()
                if not origin.is_relative_to(source):
                    raise ValueError("规则文件超出旧包目录")
                (stage / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origin, stage / rel)
        atomic_json(stage / "credentials.json", creds)
        atomic_json(stage / "config.json", c)
        from routing import Router

        Router(c, stage, None)
        if not all(
            isinstance(creds.get(k), str) and creds[k] for k in ("username", "password")
        ):
            raise ValueError("缺少代理凭据")
        os.rename(stage, dest)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def new_profile(profile):
    dest = directory(profile)
    if dest.exists():
        raise ValueError("方案已存在")
    c = {
        "server_ip": input("服务器 IP：").strip(),
        "server_port": int(input("TLS 端口：").strip()),
        "server_name": input("TLS 证书域名：").strip(),
        "interface": "",
        "default": "proxy",
        "block": [],
        "proxy": [],
        "direct": [
            "localhost",
            "127.0.0.0/8",
            "::1/128",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ],
        "company_dns": {"domains": [], "servers": []},
        "china_routing": {"enabled": False},
    }
    creds = {
        "username": input("代理用户名：").strip(),
        "password": getpass.getpass("代理密码（不显示）："),
    }
    validate(c)
    if not creds["username"] or not creds["password"]:
        raise ValueError("用户名和密码不能为空")
    atomic_json(dest / "credentials.json", creds)
    atomic_json(dest / "config.json", c)


def menu(profile):
    while True:
        print(f"\n连接与分流 · 当前方案 {profile}")
        print(
            "1 选择方案  2 导入旧代理包  3 新建连接  4 编辑分流  5 公司 DNS  6 诊断  7 更新连接凭据  0 退出"
        )
        choice = input("选择：").strip()
        try:
            if choice == "0":
                return
            if choice == "1":
                print("可选方案：" + ", ".join(list_profiles()))
                name = input("方案 ID：").strip()
                load(name)
                profile = name
            elif choice == "2":
                source = (
                    input("旧包目录（包含 config.json 和 credentials.json）：")
                    .strip()
                    .strip('"')
                )
                name = input("新方案 ID [default]：").strip() or "default"
                import_legacy(source, name)
                profile = name
                print("导入成功，旧包未修改。请在启动器重新检测并选择此方案。")
            elif choice == "3":
                name = input("新方案 ID：").strip()
                new_profile(name)
                profile = name
            elif choice in ("4", "5", "7"):
                c, creds, base = load(profile)
                before = revision(profile)
                if choice == "4":
                    print(
                        "规则优先级：阻止 → 强制代理 → 直连 → 公司 DNS → 国内规则 → 默认。"
                    )
                    print(
                        "当前："
                        + json.dumps(
                            {
                                k: c.get(k)
                                for k in (
                                    "block",
                                    "proxy",
                                    "direct",
                                    "default",
                                    "china_routing",
                                )
                            },
                            ensure_ascii=False,
                        )
                    )
                    print("逗号分隔；回车保持；输入 - 清空。修改只影响之后启动的会话。")
                    for key, label in [
                        ("block", "阻止"),
                        ("proxy", "强制代理"),
                        ("direct", "直连"),
                    ]:
                        raw = input(label + "：").strip()
                        if raw:
                            c[key] = (
                                []
                                if raw == "-"
                                else [
                                    v.strip().lower()
                                    for v in raw.split(",")
                                    if v.strip()
                                ]
                            )
                    default = input("默认 [proxy/direct/block，回车保持]：").strip()
                    if default:
                        c["default"] = default
                    if c.get("china_routing", {}).get("domains_file"):
                        enabled = input("国内规则 [on/off，回车保持]：").strip()
                        if enabled in ("on", "off"):
                            c["china_routing"]["enabled"] = enabled == "on"
                elif choice == "5":
                    print(
                        "当前："
                        + json.dumps(c.get("company_dns", {}), ensure_ascii=False)
                    )
                    print(
                        "公司域名仅使用指定 DNS，失败时不会转向公共 DNS。空输入清空。"
                    )
                    c["company_dns"] = {
                        "domains": [
                            x.strip().lower()
                            for x in input("公司域名，逗号分隔：").split(",")
                            if x.strip()
                        ],
                        "servers": [
                            x.strip()
                            for x in input("公司 DNS IPv4，逗号分隔：").split(",")
                            if x.strip()
                        ],
                    }
                else:
                    creds = {
                        "username": input("代理用户名：").strip(),
                        "password": getpass.getpass("代理密码（不显示）："),
                    }
                    if not all(creds.values()) or ":" in creds["username"]:
                        raise ValueError("凭据格式无效")
                    save(profile, c, creds, before)
                    print("凭据已更新。")
                    continue
                validate(c)
                from routing import Router

                Router(c, base, None)
                save(profile, c, creds, before)
                print("已保存，下次启动生效。")
            elif choice == "6":
                import runner

                runner.run(profile, [], doctor=True)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            # Config/parser error text can contain file contents: never echo it.
            print(
                f"操作未完成（{type(exc).__name__}）；请检查方案、路径、端口和规则格式。原配置保持不变。"
            )
