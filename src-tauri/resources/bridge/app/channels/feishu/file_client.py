"""
飞书文件上传下载客户端

对应 cos_client.py，提供相同的 upload_file() / download_file() 签名，
通过飞书 Open API 操作文件。
"""
import logging
import mimetypes
from pathlib import Path
from typing import Optional

import httpx

from app.channels.feishu.auth import feishu_auth, FEISHU_API_BASE

logger = logging.getLogger(__name__)

# 图片后缀集合
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class FeishuFileClient:
    """飞书文件客户端"""

    def __init__(self):
        self.timeout = httpx.Timeout(60.0, connect=10.0)

    async def download_file(
        self,
        file_key: str,
        local_path: Path,
        user_token: str,
        message_id: str = "",
    ) -> bool:
        """
        从飞书下载文件到本地

        Args:
            file_key: 飞书 image_key 或 file_key
            local_path: 本地保存路径
            user_token: 用户鉴权 Token（保留参数，飞书使用 tenant_token）
            message_id: 飞书消息 ID（用于消息资源端点下载用户发送的附件）

        Returns:
            是否下载成功
        """
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            token = await feishu_auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}

            if message_id:
                # 消息资源端点（下载用户在消息中发送的图片/文件）
                res_type = "image" if file_key.startswith("img_") else "file"
                url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/resources/{file_key}?type={res_type}"
            elif file_key.startswith("img_"):
                # 回退到原有端点（机器人自己上传的图片）
                url = f"{FEISHU_API_BASE}/im/v1/images/{file_key}"
            else:
                url = f"{FEISHU_API_BASE}/im/v1/files/{file_key}"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, headers=headers)

                if resp.status_code == 200:
                    local_path.write_bytes(resp.content)
                    logger.info(
                        f"[FEISHU_FILE] Downloaded: {file_key} -> {local_path} "
                        f"({len(resp.content)} bytes)"
                    )
                    return True
                else:
                    logger.error(
                        f"[FEISHU_FILE] Download failed: {resp.status_code} - "
                        f"{resp.text[:500]}"
                    )
                    return False

        except Exception as e:
            logger.error(f"[FEISHU_FILE] Download error: {e}")
            return False

    async def upload_file(
        self,
        local_path: Path,
        user_token: str,
        cos_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        上传本地文件到飞书

        Args:
            local_path: 本地文件路径
            user_token: 用户鉴权 Token（保留参数，飞书使用 tenant_token）
            cos_path: COS 目标路径（保留参数，飞书不使用）

        Returns:
            上传成功返回 image_key 或 file_key，失败返回 None
        """
        if not local_path.exists():
            logger.error(f"[FEISHU_FILE] File not found: {local_path}")
            return None

        try:
            token = await feishu_auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}

            suffix = local_path.suffix.lower()
            file_content = local_path.read_bytes()

            if suffix in IMAGE_SUFFIXES:
                return await self._upload_image(local_path, file_content, headers)
            else:
                return await self._upload_file(local_path, file_content, headers)

        except Exception as e:
            logger.error(f"[FEISHU_FILE] Upload error: {e}")
            return None

    async def _upload_image(
        self, local_path: Path, content: bytes, headers: dict
    ) -> Optional[str]:
        """上传图片，返回 image_key"""
        url = f"{FEISHU_API_BASE}/im/v1/images"

        mime_type = mimetypes.guess_type(str(local_path))[0] or "image/png"
        files = {"image": (local_path.name, content, mime_type)}
        data = {"image_type": "message"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            result = resp.json()

        if result.get("code") == 0:
            image_key = result["data"]["image_key"]
            logger.info(f"[FEISHU_FILE] Uploaded image: {local_path} -> {image_key}")
            return image_key
        else:
            logger.error(
                f"[FEISHU_FILE] Image upload failed: "
                f"code={result.get('code')}, msg={result.get('msg')}"
            )
            return None

    async def _upload_file(
        self, local_path: Path, content: bytes, headers: dict
    ) -> Optional[str]:
        """上传文件，返回 file_key"""
        url = f"{FEISHU_API_BASE}/im/v1/files"

        mime_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
        files = {"file": (local_path.name, content, mime_type)}
        data = {
            "file_type": self._get_feishu_file_type(local_path.suffix.lower()),
            "file_name": local_path.name,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, files=files, data=data)
            result = resp.json()

        if result.get("code") == 0:
            file_key = result["data"]["file_key"]
            logger.info(f"[FEISHU_FILE] Uploaded file: {local_path} -> {file_key}")
            return file_key
        else:
            logger.error(
                f"[FEISHU_FILE] File upload failed: "
                f"code={result.get('code')}, msg={result.get('msg')}"
            )
            return None

    async def get_message(self, message_id: str) -> Optional[str]:
        """
        获取指定消息的文本内容（用于引用消息场景）

        Args:
            message_id: 飞书消息 ID

        Returns:
            消息文本内容，失败返回 None
        """
        try:
            token = await feishu_auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    logger.warning(
                        f"[FEISHU_FILE] Get message failed: {resp.status_code} - "
                        f"{resp.text[:200]}"
                    )
                    return None

                data = resp.json()
                if data.get("code") != 0:
                    logger.warning(
                        f"[FEISHU_FILE] Get message API error: "
                        f"code={data.get('code')}, msg={data.get('msg')}"
                    )
                    return None

                items = data.get("data", {}).get("items", [])
                if not items:
                    return None

                msg = items[0]
                msg_type = msg.get("msg_type", "")
                body = msg.get("body", {})
                content_str = body.get("content", "{}")

                import json
                try:
                    content = json.loads(content_str)
                except (json.JSONDecodeError, TypeError):
                    content = {}

                if msg_type == "text":
                    return content.get("text", "")
                elif msg_type == "post":
                    # 富文本：提取所有文本段落
                    texts = []
                    title = content.get("title", "")
                    if title:
                        texts.append(title)
                    for paragraph in content.get("content", []):
                        for element in paragraph:
                            tag = element.get("tag", "")
                            if tag == "text":
                                texts.append(element.get("text", ""))
                            elif tag == "a":
                                texts.append(element.get("text", ""))
                    return " ".join(texts).strip() if texts else None
                elif msg_type == "image":
                    return "[图片]"
                elif msg_type == "file":
                    return f"[文件: {content.get('file_name', '未知文件')}]"
                else:
                    return f"[{msg_type}消息]"

        except Exception as e:
            logger.error(f"[FEISHU_FILE] Get message error: {e}")
            return None

    @staticmethod
    def _get_feishu_file_type(suffix: str) -> str:
        """映射文件后缀到飞书 file_type"""
        # 飞书支持的 file_type: opus, mp4, pdf, doc, xls, ppt, stream
        mapping = {
            ".pdf": "pdf",
            ".doc": "doc", ".docx": "doc",
            ".xls": "xls", ".xlsx": "xls",
            ".ppt": "ppt", ".pptx": "ppt",
            ".mp4": "mp4",
            ".opus": "opus", ".ogg": "opus",
        }
        return mapping.get(suffix, "stream")


# 全局实例
feishu_file_client = FeishuFileClient()
