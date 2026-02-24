"""
消息构建器

构建 Claude SDK 的 multimodal 消息格式
- 图片 → multimodal content block (base64)
- 文档 → 提示文本，让 Claude 使用 Read 工具
"""
import logging
from typing import Dict, List, Any, Optional

from app.core.file_processor import ProcessedFile, FileCategory

logger = logging.getLogger(__name__)


class MessageBuilder:
    """
    消息构建器

    根据文件类型构建不同的消息格式：
    - 图片：使用 SDK 的 multimodal message 直接传递 base64
    - 文档：生成提示文本，指导 Claude 使用 Read 工具
    """

    @staticmethod
    def build_multimodal_content(
        user_text: str,
        files: List[ProcessedFile],
        workspace_path: str,
    ) -> List[Dict[str, Any]]:
        """
        构建 multimodal content 列表

        Args:
            user_text: 用户文本
            files: 处理后的文件列表
            workspace_path: 工作目录路径

        Returns:
            content 列表，包含 text 和 image blocks
        """
        content = []

        # 分离图片和文档
        images = [f for f in files if f.is_image() and f.base64_data]
        documents = [f for f in files if not f.is_image()]

        # 1. 添加图片 blocks
        for img in images:
            if img.base64_data and img.mime_type:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.mime_type,
                        "data": img.base64_data,
                    }
                })
                logger.info(f"[MessageBuilder] Added image block: {img.filename}")

        # 2. 如果有文档，添加文档提示
        if documents:
            doc_prompt = MessageBuilder._build_document_prompt(documents, workspace_path)
            content.append({
                "type": "text",
                "text": doc_prompt,
            })
            logger.info(f"[MessageBuilder] Added document prompt for {len(documents)} files")

        # 3. 添加用户文本
        if user_text and user_text.strip():
            content.append({
                "type": "text",
                "text": user_text.strip(),
            })

        return content

    @staticmethod
    def _build_document_prompt(documents: List[ProcessedFile], workspace_path: str) -> str:
        """
        构建文档提示文本

        Args:
            documents: 文档文件列表
            workspace_path: 工作目录路径

        Returns:
            提示文本
        """
        if len(documents) == 1:
            doc = documents[0]
            return f"用户上传了文件 {doc.filename}，路径：{doc.local_path}\n请使用 Read 工具读取文件内容。"
        else:
            lines = ["用户上传了以下文件，请使用 Read 工具读取："]
            for i, doc in enumerate(documents, 1):
                lines.append(f"{i}. {doc.filename} - {doc.local_path}")
            return "\n".join(lines)

    @staticmethod
    def build_text_only_prompt(
        user_text: str,
        files: List[ProcessedFile],
        workspace_path: str,
    ) -> str:
        """
        构建纯文本格式的 prompt（用于无图片场景）

        当没有图片时，使用这种简化格式，文件路径直接拼接到 prompt 前面

        Args:
            user_text: 用户文本
            files: 处理后的文件列表
            workspace_path: 工作目录路径

        Returns:
            完整的 prompt 字符串
        """
        if not files:
            return user_text

        # 所有文件都是文档（没有图片）
        file_paths = [str(f.local_path) for f in files]

        if len(file_paths) == 1:
            prompt = f"{file_paths[0]}\n{user_text}"
        else:
            files_str = "\n".join(file_paths)
            prompt = f"{files_str}\n{user_text}"

        logger.info(f"[MessageBuilder] Built text-only prompt with {len(files)} file paths")
        return prompt

    @staticmethod
    def has_images(files: List[ProcessedFile]) -> bool:
        """检查文件列表中是否包含图片"""
        return any(f.is_image() and f.base64_data for f in files)

    @staticmethod
    def build_user_message(
        user_text: str,
        files: List[ProcessedFile],
        workspace_path: str,
    ) -> Dict[str, Any]:
        """
        构建完整的用户消息

        根据文件类型自动选择格式：
        - 有图片：使用 multimodal content
        - 无图片：使用简单文本格式

        Args:
            user_text: 用户文本
            files: 处理后的文件列表
            workspace_path: 工作目录路径

        Returns:
            用户消息 dict
        """
        if MessageBuilder.has_images(files):
            # 有图片时，使用 multimodal 格式
            content = MessageBuilder.build_multimodal_content(
                user_text, files, workspace_path
            )
            return {
                "role": "user",
                "content": content,
            }
        else:
            # 无图片时，使用简单文本格式
            prompt = MessageBuilder.build_text_only_prompt(
                user_text, files, workspace_path
            )
            return {
                "role": "user",
                "content": prompt,
            }


# 全局实例
message_builder = MessageBuilder()
