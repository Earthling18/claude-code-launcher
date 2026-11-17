#!/usr/bin/env python3
"""CC Launcher connection interface v1. Python 3.11+, cloud mode uses the standard library; node libraries are optional."""

import argparse
import json
import sys


def main():
    if sys.version_info < (3, 11):
        raise RuntimeError("需要 Python 3.11 或以上")
    import profiles

    parser = argparse.ArgumentParser(description="按需 CLI 或常驻回环代理；不修改系统网络设置")
    parser.add_argument("--profile", default="default")
    sub = parser.add_subparsers(dest="action", required=True)
    listing = sub.add_parser("profiles")
    listing.add_argument("--json", action="store_true")
    sub.add_parser("menu")
    sub.add_parser("doctor")
    web = sub.add_parser("web")
    web.add_argument("--no-open", action="store_true")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=0)
    attach = sub.add_parser("attach")
    attach.add_argument("command", nargs=argparse.REMAINDER)
    launch = sub.add_parser("run")
    launch.add_argument("command", nargs=argparse.REMAINDER)
    importer = sub.add_parser("import-legacy")
    importer.add_argument("directory")
    args = parser.parse_args()
    if args.action == "profiles":
        print(
            json.dumps(
                {"protocol": 1, "profiles": profiles.list_profiles(),
                 "profile_labels": profiles.labels(),
                 "capabilities": ["web", "resident", "attach", "subscriptions", "ss", "anytls"]},
                ensure_ascii=False,
            )
        )
        return 0
    if args.action == "menu":
        profiles.menu(args.profile)
        return 0
    if args.action == "import-legacy":
        profiles.import_legacy(args.directory, args.profile)
        print("导入成功。原配置未修改。")
        return 0
    if args.action == "web":
        import manager
        manager.main(args.profile, not args.no_open)
        return 0
    if args.action == "serve":
        import manager
        if not 0 <= args.port <= 65535:
            raise ValueError("端口无效")
        manager.main(args.profile, open_browser=False, start_resident=True, port=args.port)
        return 0
    import runner

    command = getattr(args, "command", [])
    if command[:1] == ["--"]:
        command = command[1:]
    if args.action == "attach":
        import manager
        return manager.attach(args.profile, command)
    return runner.run(args.profile, command, doctor=args.action == "doctor")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        sys.exit(130)
    except Exception as exc:
        # Do not leak JSON, paths with embedded credentials or upstream text.
        print(
            f"[connection] {type(exc).__name__}: 启动未完成；请检查 Python、CLI 安装及所选方案，使用 menu / doctor 诊断。",
            file=sys.stderr,
        )
        sys.exit(1)
