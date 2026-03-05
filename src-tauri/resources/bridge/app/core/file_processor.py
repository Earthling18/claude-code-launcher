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

from app.channels import get_file_client

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

    @staticmethod
    def _detect_extension_from_magic(file_path: Path) -> Optional[str]:
        """从文件头 magic bytes 检测文件扩展名"""
        try:
            with open(file_path, "rb") as f:
                header = f.read(16)
            if header[:3] == b'\xff\xd8\xff':
                return '.jpg'
            if header[:8] == b'\x89PNG\r\n\x1a\n':
                return '.png'
            if header[:4] == b'GIF8':
                return '.gif'
            if header[:4] == b'RIFF' and len(header) >= 12 and header[8:12] == b'WEBP':
                return '.webp'
            if header[:2] == b'BM':
                return '.bmp'
            if header[:4] == b'%PDF':
                return '.pdf'
        except Exception:
            pass
        return None

    async def download_file(
        self,
        cos_path: str,
        workspace: Path,
        user_token: str,
        channel: str = "wecom",
        message_id: str = "",
        filename: str = "",
    ) -> Optional[Path]:
        """
        下载单个文件到工作目录

        Args:
            cos_path: COS 路径（企微）或 file_key/image_key（飞书）
            workspace: 工作目录
            user_token: 用户鉴权 Token
            channel: 渠道标识 ("wecom" | "feishu")
            message_id: 飞书消息 ID（用于消息资源端点下载用户附件）
            filename: 原始文件名（保留扩展名，飞书 file 类型提供）

        Returns:
            本地文件路径，失败返回 None
        """
        # 确定保存文件名：优先使用提供的 filename（保留原始扩展名）
        if filename:
            save_filename = filename
        else:
            save_filename = cos_path.split("/")[-1] if "/" in cos_path else cos_path

        local_path = workspace / save_filename

        # 如果文件已存在，直接返回
        if local_path.exists():
            logger.info(f"[FileProcessor] File already exists: {local_path}")
            return local_path

        # 无扩展名时，检查是否已有检测过的重命名版本（如 img_xxx.jpg）
        if not Path(save_filename).suffix:
            for ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.pdf'):
                candidate = workspace / f"{save_filename}{ext}"
                if candidate.exists():
                    logger.info(f"[FileProcessor] Found renamed file: {candidate}")
                    return candidate

        # 走渠道路由下载
        file_client = get_file_client(channel)
        if channel == "feishu":
            success = await file_client.download_file(cos_path, local_path, user_token, message_id=message_id)
        else:
            success = await file_client.download_file(cos_path, local_path, user_token)

        if success:
            # 无扩展名 → 从文件头 magic bytes 检测真实类型并重命名
            if not local_path.suffix:
                detected_ext = self._detect_extension_from_magic(local_path)
                if detected_ext:
                    new_path = local_path.with_suffix(detected_ext)
                    local_path.rename(new_path)
                    local_path = new_path
                    logger.info(f"[FileProcessor] Detected type and renamed: {cos_path} -> {local_path}")

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
        channel: str = "wecom",
        message_id: str = "",
        filename: str = "",
    ) -> Optional[ProcessedFile]:
        """
        处理单个文件：下载 + 分类 + (图片) base64 编码

        Args:
            cos_path: COS 路径（企微）或 file_key/image_key（飞书）
            original_type: 原始类型 (file/image)
            workspace: 工作目录
            user_token: 用户鉴权 Token
            channel: 渠道标识 ("wecom" | "feishu")
            message_id: 飞书消息 ID（用于消息资源端点下载用户附件）
            filename: 原始文件名（保留扩展名）

        Returns:
            ProcessedFile 对象，失败返回 None
        """
        # 1. 下载文件
        local_path = await self.download_file(cos_path, workspace, user_token, channel=channel, message_id=message_id, filename=filename)
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
        channel: str = "wecom",
    ) -> List[ProcessedFile]:
        """
        处理多个文件

        Args:
            file_items: 文件列表 (QueryItem 格式)
            workspace: 工作目录
            user_token: 用户鉴权 Token
            channel: 渠道标识 ("wecom" | "feishu")

        Returns:
            ProcessedFile 列表（只包含成功处理的文件）
        """
        # 飞书渠道不需要 user_token（内部使用 tenant_token），企微渠道需要
        if not user_token and channel != "feishu":
            logger.error("[FileProcessor] Missing user_token, cannot process files")
            return []

        results = []
        for item in file_items:
            processed = await self.process_file(
                cos_path=item.content,
                original_type=item.type,
                workspace=workspace,
                user_token=user_token,
                channel=channel,
                message_id=getattr(item, "message_id", ""),
                filename=getattr(item, "filename", ""),
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
