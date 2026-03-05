#!/usr/bin/env python
"""
MobotAgentService self-update CLI.

Downloads code-only update packages from PyPI (preferred) or GitHub Releases
and applies them in-place. User data (skills, .env, workspace, etc.) is
never touched.

Usage:
    python update.py              # Check + confirm + update
    python update.py --check      # Only check, print version and changelog
    python update.py --force      # Skip version comparison, force reinstall latest
    python update.py --backend pypi   # Use PyPI backend only
    python update.py --repo owner/repo  # Use custom GitHub repo
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def _print_progress(downloaded: int, total: int):
    """Print download progress bar."""
    if total <= 0:
        print(f"\r  Downloaded: {downloaded / 1024:.0f} KB", end="", flush=True)
        return
    pct = downloaded / total * 100
    bar_len = 40
    filled = int(bar_len * downloaded / total)
    bar = "=" * filled + "-" * (bar_len - filled)
    print(f"\r  [{bar}] {pct:.1f}% ({downloaded / 1024:.0f}/{total / 1024:.0f} KB)", end="", flush=True)


async def run_check(updater):
    """Check for updates and print info."""
    from app.core.updater import get_version
    print(f"Current version: {get_version()}")
    print(f"Backend: {updater._backend}")

    try:
        info = await updater.check()
    except Exception as e:
        print(f"\nError checking for updates: {e}")
        return None

    if info is None:
        print("No update package found.")
        return None

    if info.has_update:
        print(f"\nUpdate available: {info.current_version} -> {info.latest_version}")
    else:
        print(f"\nAlready up to date: {info.current_version}")

    print(f"Source: {info.source}")
    if info.published_at:
        print(f"Published: {info.published_at}")
    if info.asset_size:
        print(f"Package size: {info.asset_size / 1024:.0f} KB")
    if info.changelog:
        print(f"\nChangelog:\n{info.changelog}")

    return info


async def run_update(updater, force: bool = False, yes: bool = False):
    """Full update flow: check -> confirm -> download -> apply."""
    info = await run_check(updater)
    if info is None:
        return

    if not info.has_update and not force:
        print("\nNo update needed.")
        return

    if not info.has_update and force:
        print("\n--force specified, proceeding with reinstall...")

    # Confirm
    if not yes:
        print()
        try:
            answer = input("Proceed with update? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return

        if answer not in ("y", "yes"):
            print("Cancelled.")
            return

    # Check dependencies before download
    deps_changed = False

    # Download
    print("\nDownloading update package...")
    try:
        staging = await updater.download(info, progress_callback=_print_progress)
        print()  # newline after progress bar
    except ValueError as e:
        print(f"\nChecksum verification failed:\n{e}")
        print("Update aborted. The download may be corrupted.")
        return
    except Exception as e:
        print(f"\nDownload failed: {e}")
        return

    # Check deps before applying (staging still has original requirements.txt)
    deps_changed = updater.check_deps(staging)

    # Apply
    print("Applying update...")
    try:
        updater.apply(staging)
    except Exception as e:
        print(f"\nUpdate failed: {e}")
        print("You can re-run 'python update.py' to try again.")
        return

    from app.core.updater import get_version
    print(f"\nUpdate complete! Version: {get_version()}")

    if deps_changed:
        print("\n*** Dependencies have changed ***")
        print("Please run:  pip install -r requirements.txt")

    print("\nPlease restart the service:  python start.py")


def main():
    parser = argparse.ArgumentParser(
        description="MobotAgentService self-update",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python update.py              Check and install updates (auto: PyPI first, GitHub fallback)
  python update.py --check      Only check for updates
  python update.py --force      Force reinstall latest version
  python update.py --backend pypi     Use PyPI backend only
  python update.py --backend github   Use GitHub backend only
  python update.py --repo owner/repo  Use custom GitHub repo
        """,
    )
    parser.add_argument("--check", action="store_true", help="Only check for updates, don't install")
    parser.add_argument("--force", action="store_true", help="Force reinstall even if already up to date")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--repo", type=str, default=None, help="GitHub repo (owner/repo)")
    parser.add_argument("--backend", choices=["auto", "pypi", "github"],
                        default=None, help="Update backend (default: auto)")
    args = parser.parse_args()

    from app.core.updater import Updater
    updater = Updater(project_root=PROJECT_ROOT, repo=args.repo, backend=args.backend)

    if args.check:
        asyncio.run(run_check(updater))
    else:
        asyncio.run(run_update(updater, force=args.force, yes=args.yes))


if __name__ == "__main__":
    main()
