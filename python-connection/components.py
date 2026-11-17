"""Optional local libraries only; never download or execute a proxy core."""
import asyncio
import importlib
import importlib.util
import os
import platform
from pathlib import Path
import shutil
import sys
import tempfile

BASE=Path(__file__).resolve().parent
DEPS=BASE/'.deps'/f'py{sys.version_info.major}{sys.version_info.minor}-{sys.platform}-{platform.machine()}'

def activate():
    if DEPS.is_dir() and str(DEPS) not in sys.path:
        sys.path.insert(0,str(DEPS));importlib.invalidate_caches()

def available():
    activate()
    try:
        import yaml
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return True
    except (ImportError,OSError):return False

async def install():
    if available():return
    stage=Path(tempfile.mkdtemp(prefix='.components-',dir=BASE))
    process=None
    try:
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','pip','install','--disable-pip-version-check','--no-input','--only-binary=:all:','--target',str(stage),'cryptography==46.0.7','PyYAML==6.0.3',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(process.wait(),180)
        if process.returncode:raise ValueError('组件下载失败，请检查网络和 Python pip')
        # A broken previous install is kept for rollback rather than overwritten.
        if DEPS.exists():raise ValueError('已有组件不可用，请使用干净目录重新安装')
        DEPS.parent.mkdir(parents=True,exist_ok=True)
        os.replace(stage,DEPS);activate()
        if not available():raise ValueError('组件加载失败，请重新打开管理页')
    finally:
        if process and process.returncode is None:process.kill();await process.wait()
        if stage.exists():shutil.rmtree(stage)
