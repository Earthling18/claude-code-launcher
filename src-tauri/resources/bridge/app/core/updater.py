"""
Self-update engine for MobotAgentService.

Downloads code-only update packages from PyPI (preferred) or GitHub Releases
and applies them in-place, replacing application code while preserving all
user data (skills, .env, workspace, cron_jobs.json, etc.).

Usage:
    from app.core.updater import Updater
    updater = Updater()
    info = await updater.check()
    if info:
        staging = await updater.download(info)
        updater.apply(staging)
"""

import hashlib
import logging
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


def get_version() -> str:
    """Read current version from VERSION file."""
    version_file = _PROJECT_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


@dataclass
class UpdateInfo:
    """Information about an available update."""
    current_version: str
    latest_version: str
    download_url: str
    changelog: str = ""
    published_at: str = ""
    checksums_url: str = ""
    asset_size: int = 0
    source: str = "github"   # "github" | "pypi"
    sha256: str = ""         # PyPI provides inline sha256

    @property
    def has_update(self) -> bool:
        return self.current_version != self.latest_version


def _extract_changelog(description: str) -> str:
    """Extract Changelog section from PyPI package description."""
    match = re.search(
        r'^##\s+Changelog\s*\n(.*?)(?=^##\s|\Z)',
        description, re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else description[:1000]


class Updater:
    """Core update engine.

    Checks PyPI (preferred) or GitHub Releases for new versions, downloads
    code-only update packages, and applies them in-place.
    """

    GITHUB_REPO = "eggypi/mobot-bridge-release"
    PYPI_PACKAGE = "mobot-bridge-update"
    STAGING_DIR = "_update_staging"

    # Directories to replace during update
    CODE_DIRS = ["app", "installer"]

    # Individual files to replace during update
    CODE_FILES = [
        "start.py", "start.pyc",
        "restart_helper.py", "restart_helper.pyc",
        "update.py", "update.pyc",
        "VERSION", "requirements.txt",
        ".env.example", ".mcp.json.example", "cron_jobs.example.json",
    ]

    # Bridge code files (inside bridge/ directory)
    BRIDGE_CODE = ["bridge_clientv3.py", "bridge_clientv3.pyc", "requirements.txt"]

    # Paths that must NEVER be modified during update
    NEVER_TOUCH = [
        ".claude/",
        "data/",
        "workspace/",
        ".env",
        ".mcp.json",
        "cron_jobs.json",
        "api_keys.json",
        "bridge/config.yaml",
        "bridge/config.yaml.bak",
        "python/",
        "lib/",
        "logs/",
    ]

    # Files inside CODE_DIRS that contain user data and must be preserved
    # These are saved before directory replacement and restored after
    PRESERVE_IN_CODE_DIRS = [
        "app/prompts/soul.md",
    ]

    def __init__(self, project_root: Optional[Path] = None, repo: Optional[str] = None,
                 backend: Optional[str] = None):
        self.project_root = project_root or _PROJECT_ROOT
        if repo:
            self.GITHUB_REPO = repo
        # Allow override via environment variable
        env_repo = os.environ.get("MOBOT_GITHUB_REPO")
        if env_repo:
            self.GITHUB_REPO = env_repo
        self._backend = (backend or os.environ.get("MOBOT_UPDATE_BACKEND", "auto")).lower()
        self.staging_path = self.project_root / self.STAGING_DIR
        self._gh_token = self._get_gh_token()

    @staticmethod
    def _get_gh_token() -> str:
        """Get GitHub token for private repo access.

        Priority: GITHUB_TOKEN env var > gh auth token (gh CLI).
        """
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            return token
        try:
            import subprocess
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ""

    def _auth_headers(self) -> dict:
        """Build HTTP headers with auth if token available."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"MobotAgentService/{get_version()}",
        }
        if self._gh_token:
            headers["Authorization"] = f"token {self._gh_token}"
        return headers

    async def check(self) -> Optional[UpdateInfo]:
        """Check for the latest version using the configured backend.

        Returns UpdateInfo if a newer version is available, None if up to date.
        Raises on network errors.
        """
        if self._backend == "pypi":
            return await self._check_pypi()
        elif self._backend == "github":
            return await self._check_github()
        else:  # "auto": PyPI first, GitHub fallback
            try:
                result = await self._check_pypi()
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"[UPDATE] PyPI check failed, trying GitHub: {e}")
            return await self._check_github()

    async def _check_pypi(self) -> Optional[UpdateInfo]:
        """Check PyPI for the latest version."""
        import httpx

        current = get_version()
        url = f"https://pypi.org/pypi/{self.PYPI_PACKAGE}/json"
        logger.info(f"[UPDATE] Checking PyPI: {url}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()

        latest = data["info"]["version"]
        description = data["info"].get("description", "")

        # Find wheel file from releases or urls
        files = data.get("releases", {}).get(latest, []) or data.get("urls", [])
        whl = next((f for f in files if f.get("packagetype") == "bdist_wheel"), None)
        if not whl:
            logger.warning("[UPDATE] No wheel found in PyPI release")
            return None

        info = UpdateInfo(
            current_version=current,
            latest_version=latest,
            download_url=whl["url"],
            changelog=_extract_changelog(description),
            asset_size=whl.get("size", 0),
            source="pypi",
            sha256=whl.get("digests", {}).get("sha256", ""),
        )

        if info.has_update:
            logger.info(f"[UPDATE] Update available (PyPI): {current} -> {latest}")
        else:
            logger.info(f"[UPDATE] Already up to date (PyPI): {current}")

        return info

    async def _check_github(self) -> Optional[UpdateInfo]:
        """Check GitHub Releases for the latest version."""
        import httpx

        current = get_version()
        api_url = f"https://api.github.com/repos/{self.GITHUB_REPO}/releases/latest"

        logger.info(f"[UPDATE] Checking GitHub: {api_url}")

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(api_url, headers=self._auth_headers())
            resp.raise_for_status()
            release = resp.json()

        tag = release.get("tag_name", "").lstrip("v")
        body = release.get("body", "")
        published_at = release.get("published_at", "")

        # Find update.zip asset
        # For private repos, use the API download URL (with token auth)
        # instead of browser_download_url (which requires browser login)
        download_url = ""
        checksums_url = ""
        asset_size = 0
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.endswith("-update.zip"):
                download_url = asset["url"]  # API URL, works with token auth
                asset_size = asset.get("size", 0)
            elif name == "checksums.sha256":
                checksums_url = asset["url"]

        if not download_url:
            logger.warning("[UPDATE] No update.zip asset found in latest release")
            return None

        info = UpdateInfo(
            current_version=current,
            latest_version=tag,
            download_url=download_url,
            changelog=body,
            published_at=published_at,
            checksums_url=checksums_url,
            asset_size=asset_size,
            source="github",
        )

        if info.has_update:
            logger.info(f"[UPDATE] Update available (GitHub): {current} -> {tag}")
        else:
            logger.info(f"[UPDATE] Already up to date (GitHub): {current}")

        return info

    async def download(self, info: UpdateInfo, progress_callback=None) -> Path:
        """Download the update package to staging directory.

        Routes to PyPI or GitHub backend based on info.source.

        Args:
            info: UpdateInfo from check()
            progress_callback: Optional callable(downloaded_bytes, total_bytes)

        Returns:
            Path to staging directory with extracted update contents.

        Raises:
            ValueError: If checksum verification fails.
            httpx.HTTPError: On network errors.
        """
        if info.source == "pypi":
            return await self._download_pypi(info, progress_callback)
        return await self._download_github(info, progress_callback)

    async def _download_pypi(self, info: UpdateInfo, progress_callback=None) -> Path:
        """Download update package from PyPI wheel."""
        import httpx

        if self.staging_path.exists():
            shutil.rmtree(self.staging_path)
        self.staging_path.mkdir(parents=True)

        whl_path = self.staging_path / "package.whl"
        sha256_hash = hashlib.sha256()
        downloaded = 0

        # Stream download wheel (direct HTTP, no pip needed)
        logger.info(f"[UPDATE] Downloading from PyPI: {info.download_url}")
        async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
            async with client.stream("GET", info.download_url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                with open(whl_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)
                        sha256_hash.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)

        # Verify SHA256
        actual = sha256_hash.hexdigest()
        if info.sha256:
            if actual != info.sha256:
                shutil.rmtree(self.staging_path)
                raise ValueError(
                    f"Checksum mismatch!\n"
                    f"  Expected: {info.sha256}\n"
                    f"  Actual:   {actual}"
                )
            logger.info(f"[UPDATE] Checksum verified: {actual[:16]}...")

        # Extract update.zip from wheel (wheel is a zip file)
        update_zip_path = self.staging_path / "update.zip"
        with zipfile.ZipFile(whl_path, "r") as whl:
            names = [n for n in whl.namelist() if n.endswith("update.zip")]
            if not names:
                shutil.rmtree(self.staging_path)
                raise ValueError("update.zip not found inside wheel")
            with whl.open(names[0]) as src, open(update_zip_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        whl_path.unlink()

        # Extract update.zip (result is identical to GitHub download)
        logger.info(f"[UPDATE] Extracting update package ({downloaded} bytes)")
        with zipfile.ZipFile(update_zip_path, "r") as zf:
            zf.extractall(self.staging_path)
        update_zip_path.unlink()

        logger.info(f"[UPDATE] Download complete (PyPI): {self.staging_path}")
        return self.staging_path

    async def _download_github(self, info: UpdateInfo, progress_callback=None) -> Path:
        """Download update package from GitHub Releases."""
        import httpx

        # Clean staging area
        if self.staging_path.exists():
            shutil.rmtree(self.staging_path)
        self.staging_path.mkdir(parents=True)

        zip_path = self.staging_path / "update.zip"
        expected_checksum = None

        # For GitHub API asset downloads, we need Accept: application/octet-stream
        def _asset_headers(accept="application/octet-stream"):
            h = self._auth_headers()
            h["Accept"] = accept
            return h

        # Download checksums file first (if available)
        if info.checksums_url:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                resp = await client.get(info.checksums_url, headers=_asset_headers())
                if resp.status_code == 200:
                    for line in resp.text.strip().splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 2 and parts[1].endswith("-update.zip"):
                            expected_checksum = parts[0]
                            break

        # Stream download the update package
        logger.info(f"[UPDATE] Downloading from GitHub: {info.download_url}")
        sha256 = hashlib.sha256()
        downloaded = 0

        async with httpx.AsyncClient(follow_redirects=True, timeout=300) as client:
            async with client.stream("GET", info.download_url, headers=_asset_headers()) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                with open(zip_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        sha256.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)

        # Verify checksum
        actual_checksum = sha256.hexdigest()
        if expected_checksum:
            if actual_checksum != expected_checksum:
                shutil.rmtree(self.staging_path)
                raise ValueError(
                    f"Checksum mismatch!\n"
                    f"  Expected: {expected_checksum}\n"
                    f"  Actual:   {actual_checksum}"
                )
            logger.info(f"[UPDATE] Checksum verified: {actual_checksum[:16]}...")
        else:
            logger.warning("[UPDATE] No checksum available, skipping verification")

        # Extract zip
        logger.info(f"[UPDATE] Extracting update package ({downloaded} bytes)")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(self.staging_path)

        # Remove the zip to save space
        zip_path.unlink()

        logger.info(f"[UPDATE] Download complete (GitHub): {self.staging_path}")
        return self.staging_path

    @staticmethod
    def _on_rmtree_error(func, path, exc_info):
        """Handle rmtree errors: log and retry after removing read-only flag."""
        import stat
        logger.warning(f"[UPDATE] rmtree failed: {path} ({exc_info[1]})")
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception as e2:
            logger.error(f"[UPDATE] rmtree retry failed: {path} ({e2})")

    def apply(self, staging: Path) -> None:
        """Apply the update from staging directory.

        Replaces code directories and files. Never touches user data.
        This is a direct replacement — no backup is created (the update.zip
        itself serves as the recovery mechanism).

        Args:
            staging: Path to staging directory (from download()).
        """
        logger.info("[UPDATE] Applying update...")

        # Detect if staging contains a nested directory (e.g., MobotAgentService/)
        # Some zip tools create a wrapper directory
        content_root = staging
        subdirs = [d for d in staging.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and not (staging / "app").exists():
            content_root = subdirs[0]
            logger.info(f"[UPDATE] Detected nested staging root: {content_root.name}")

        # Save user files that live inside code directories
        preserved = {}
        for rel_path in self.PRESERVE_IN_CODE_DIRS:
            full_path = self.project_root / rel_path
            if full_path.exists():
                content = full_path.read_bytes()
                if content.strip():  # only preserve non-empty files
                    preserved[rel_path] = content
                    logger.info(f"[UPDATE] Preserved: {rel_path}")

        # Replace code directories
        for dir_name in self.CODE_DIRS:
            src = content_root / dir_name
            dst = self.project_root / dir_name
            if src.exists():
                if dst.exists():
                    if sys.version_info >= (3, 12):
                        shutil.rmtree(dst, onexc=self._on_rmtree_error)
                    else:
                        shutil.rmtree(dst, onerror=self._on_rmtree_error)
                shutil.copytree(src, dst)
                logger.info(f"[UPDATE] Replaced: {dir_name}/")

        # Restore preserved user files
        for rel_path, content in preserved.items():
            full_path = self.project_root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(content)
            logger.info(f"[UPDATE] Restored: {rel_path}")

        # Replace individual code files
        for file_name in self.CODE_FILES:
            src = content_root / file_name
            dst = self.project_root / file_name
            if src.exists():
                shutil.copy2(src, dst)
                logger.info(f"[UPDATE] Replaced: {file_name}")

        # Replace bridge code files (not config)
        for file_name in self.BRIDGE_CODE:
            src = content_root / "bridge" / file_name
            dst = self.project_root / "bridge" / file_name
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                logger.info(f"[UPDATE] Replaced: bridge/{file_name}")

        # Post-apply verification: check critical files exist
        _critical_files = [
            "app/core/agent_service.pyc",
            "app/main.pyc",
            "app/core/updater.pyc",
        ]
        for cf in _critical_files:
            p = self.project_root / cf
            if p.exists():
                st = p.stat()
                logger.info(f"[UPDATE] Verified: {cf} size={st.st_size} mtime={st.st_mtime:.0f}")
            else:
                logger.warning(f"[UPDATE] Missing after apply: {cf}")

        # Hash-based verification: compare staging vs actual for key files
        _verify_modules = [
            "app/core/agent_service.pyc",
            "app/main.pyc",
            "app/api/routes.pyc",
            "app/static/config/app.js",
            "app/static/config/style.css",
        ]
        mismatches = []
        for vm in _verify_modules:
            src = content_root / vm
            dst = self.project_root / vm
            if src.exists() and dst.exists():
                src_hash = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
                dst_hash = hashlib.sha256(dst.read_bytes()).hexdigest()[:12]
                if src_hash != dst_hash:
                    mismatches.append(vm)
                    logger.error(f"[UPDATE] MISMATCH: {vm} (staging={src_hash}, actual={dst_hash})")
                else:
                    logger.info(f"[UPDATE] Verified: {vm} hash={dst_hash}")
            elif src.exists() and not dst.exists():
                mismatches.append(vm)
                logger.error(f"[UPDATE] MISSING after apply: {vm}")

        if mismatches:
            logger.error(f"[UPDATE] {len(mismatches)} file(s) failed verification: {mismatches}")

        # Cleanup staging
        if self.staging_path.exists():
            shutil.rmtree(self.staging_path)

        new_version = get_version()
        logger.info(f"[UPDATE] Update applied successfully. Version: {new_version}")

    def check_deps(self, staging: Path) -> bool:
        """Check if requirements.txt has changed (needs pip install).

        Args:
            staging: Path to staging directory (from download()).

        Returns:
            True if dependencies changed and pip install is needed.
        """
        # Detect nested staging root
        content_root = staging
        subdirs = [d for d in staging.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and not (staging / "app").exists():
            content_root = subdirs[0]

        old_req = self.project_root / "requirements.txt"
        new_req = content_root / "requirements.txt"

        if not new_req.exists():
            return False
        if not old_req.exists():
            return True

        old_hash = hashlib.sha256(old_req.read_bytes()).hexdigest()
        new_hash = hashlib.sha256(new_req.read_bytes()).hexdigest()
        return old_hash != new_hash

    def _is_protected(self, path: str) -> bool:
        """Check if a path is in the NEVER_TOUCH list."""
        path_normalized = path.replace("\\", "/")
        for protected in self.NEVER_TOUCH:
            if protected.endswith("/"):
                if path_normalized.startswith(protected) or path_normalized == protected.rstrip("/"):
                    return True
            else:
                if path_normalized == protected:
                    return True
        return False
