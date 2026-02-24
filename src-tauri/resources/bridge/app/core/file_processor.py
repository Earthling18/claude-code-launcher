"""
文件处理器

负责文件下载、分类和 base64 编码
支持图片和文档的分类处理
"""
import base64
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

from app.services.cos_client import cos_client

logger = logging.getLogger(__name__)


class FileCategory(Enum):
    """文件分类"""
    IMAGE = "image"
    DOCUMENT = "document"


# 图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# MIME 类型映射
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@dataclass
class ProcessedFile:
    """处理后的文件"""
    filename: str
    local_path: Path
    category: FileCategory
    original_type: str  # 原始类型 (file/image)
    cos_path: str  # 原始 COS 路径

    # 图片特有字段
    base64_data: Optional[str] = None
    mime_type: Optional[str] = None

    def is_image(self) -> bool:
        return self.category == FileCategory.IMAGE


class FileProcessor:
    """
    文件处理器

    职责：
    1. 下载 COS 文件到本地
    2. 分类文件（图片 vs 文档）
    3. 图片读取为 base64
    """

    @staticmethod
    def classify_file(filename: str, original_type: str = "") -> FileCategory:
        """
        根据文件名和原始类型分类文件

        Args:
            filename: 文件名
            original_type: 原始类型 (file/image)

        Returns:
            文件分类
        """
        # 优先根据扩展名判断
        ext = Path(filename).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return FileCategory.IMAGE

        # 其次根据原始类型
        if original_type == "image":
            return FileCategory.IMAGE

        return FileCategory.DOCUMENT

    @staticmethod
    def read_image_as_base64(file_path: Path) -> tuple[Optional[str], Optional[str]]:
        """
        读取图片文件为 base64

        Args:
            file_path: 图片文件路径

        Returns:
            (base64_data, mime_type) 元组
        """
        if not file_path.exists():
            logger.error(f"[FileProcessor] Image file not found: {file_path}")
            return None, None

        try:
            ext = file_path.suffix.lower()
            mime_type = MIME_TYPES.get(ext, "image/png")

            with open(file_path, "rb") as f:
                data = f.read()

            base64_data = base64.standard_b64encode(data).decode("utf-8")
            logger.info(f"[FileProcessor] Read image as base64: {file_path.name} ({len(data)} bytes)")

            return base64_data, mime_type

        except Exception as e:
            logger.error(f"[FileProcessor] Failed to read image: {e}")
            return None, None

    async def download_file(
        self,
        cos_path: str,
        workspace: Path,
        user_token: str,
    ) -> Optional[Path]:
        """
        下载单个文件到工作目录

        Args:
            cos_path: COS 路径
            workspace: 工作目录
            user_token: 用户鉴权 Token

        Returns:
            本地文件路径，失败返回 None
        """
        # 提取文件名
        filename = cos_path.split("/")[-1] if "/" in cos_path else cos_path
        local_path = workspace / filename

        # 如果文件已存在，直接返回
        if local_path.exists():
            logger.info(f"[FileProcessor] File already exists: {local_path}")
            return local_path

        # 下载文件
        success = await cos_client.download_file(cos_path, local_path, user_token)

        if success:
            logger.info(f"[FileProcessor] Downloaded: {cos_path} -> {local_path}")
            return local_path
        else:
            logger.error(f"[FileProcessor] Failed to download: {cos_path}")
            return None

    async def process_file(
        self,
        cos_path: str,
        original_type: str,
        workspace: Path,
        user_token: str,
    ) -> Optional[ProcessedFile]:
        """
        处理单个文件：下载 + 分类 + (图片) base64 编码

        Args:
            cos_path: COS 路径
            original_type: 原始类型 (file/image)
            workspace: 工作目录
            user_token: 用户鉴权 Token

        Returns:
            ProcessedFile 对象，失败返回 None
        """
        # 1. 下载文件
        local_path = await self.download_file(cos_path, workspace, user_token)
        if not local_path:
            return None

        # 2. 分类
        filename = local_path.name
        category = self.classify_file(filename, original_type)

        # 3. 创建 ProcessedFile
        processed = ProcessedFile(
            filename=filename,
            local_path=local_path,
            category=category,
            original_type=original_type,
            cos_path=cos_path,
        )

        # 4. 如果是图片，读取为 base64
        if category == FileCategory.IMAGE:
            base64_data, mime_type = self.read_image_as_base64(local_path)
            processed.base64_data = base64_data
            processed.mime_type = mime_type

        logger.info(f"[FileProcessor] Processed: {filename} -> {category.value}")
        return processed

    async def process_files(
        self,
        file_items: list,  # List[QueryItem]
        workspace: Path,
        user_token: str,
    ) -> List[ProcessedFile]:
        """
        处理多个文件

        Args:
            file_items: 文件列表 (QueryItem 格式)
            workspace: 工作目录
            user_token: 用户鉴权 Token

        Returns:
            ProcessedFile 列表（只包含成功处理的文件）
        """
        if not user_token:
            logger.error("[FileProcessor] Missing user_token, cannot process files")
            return []

        results = []
        for item in file_items:
            processed = await self.process_file(
                cos_path=item.content,
                original_type=item.type,
                workspace=workspace,
                user_token=user_token,
            )
            if processed:
                results.append(processed)

        logger.info(f"[FileProcessor] Processed {len(results)}/{len(file_items)} files successfully")
        return results

    async def process_cached_files(
        self,
        cached_files: list,  # List[dict] with type, content, filename
        workspace: Path,
    ) -> List[ProcessedFile]:
        """
        处理已缓存的文件（已下载到本地）

        Args:
            cached_files: 缓存的文件列表 (dict 格式，content 是本地路径)
            workspace: 工作目录

        Returns:
            ProcessedFile 列表
        """
        results = []

        for cached in cached_files:
            local_path = Path(cached.get("content", ""))

            if not local_path.exists():
                logger.warning(f"[FileProcessor] Cached file not found: {local_path}")
                continue

            filename = cached.get("filename", local_path.name)
            original_type = cached.get("type", "file")
            category = self.classify_file(filename, original_type)

            processed = ProcessedFile(
                filename=filename,
                local_path=local_path,
                category=category,
                original_type=original_type,
                cos_path=str(local_path),  # 缓存的文件用本地路径
            )

            # 如果是图片，读取为 base64
            if category == FileCategory.IMAGE:
                base64_data, mime_type = self.read_image_as_base64(local_path)
                processed.base64_data = base64_data
                processed.mime_type = mime_type

            results.append(processed)
            logger.info(f"[FileProcessor] Processed cached: {filename} -> {category.value}")

        return results


# 全局实例
file_processor = FileProcessor()
