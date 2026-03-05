"""
COS 文件下载/上传客户端

通过 HTTP API 与 COS 交互，需要 user-token 鉴权
API 地址配置在 .env 中的 WECOM_COS_API_BASE
"""
import logging
import httpx
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class COSClient:
    """COS 文件客户端（需要 user-token 鉴权）"""

    def __init__(self):
        self.base_url = settings.cos_api_base.rstrip("/")
        self.timeout = httpx.Timeout(60.0, connect=10.0)

    async def download_file(
        self,
        cos_path: str,
        local_path: Path,
        user_token: str,
    ) -> bool:
        """
        从 COS 下载文件到本地

        Args:
            cos_path: COS 路径，如 /user_id/path/file.xlsx
            local_path: 本地保存路径
            user_token: 用户鉴权 Token

        Returns:
            是否下载成功
        """
        if not user_token:
            logger.error(f"COS download failed: user_token is required for {cos_path}")
            return False

        # 处理 cos:// 前缀
        file_path = cos_path
        if file_path.startswith("cos://"):
            file_path = file_path[6:]  # 移除 cos://

        # 确保 file_path 以 / 开头（根据文档示例）
        if not file_path.startswith("/"):
            file_path = "/" + file_path

        # 确保父目录存在
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 调用 COS 下载 API
            url = f"{self.base_url}/cos/download"
            headers = {"user-token": user_token}

            # 根据文档，COS API 使用 multipart/form-data 格式（curl -F 参数）
            # 参考：cos操作.markdown 第 193-195 行
            # httpx 中使用 files 参数发送 multipart/form-data
            # 格式：{field_name: (None, field_value)} 用于非文件字段
            files = {"file_path": (None, file_path)}

            logger.info(f"[COS] Requesting: {url}")
            logger.info(f"[COS] Multipart form data: file_path={file_path}")
            logger.info(f"[COS] user-token length: {len(user_token)}")

            # 禁用代理，因为 COS 是内网地址，不应该通过代理访问
            async with httpx.AsyncClient(
                timeout=self.timeout,
                trust_env=False  # 不使用环境变量中的代理设置
            ) as client:
                # 注意：虽然文档写的是 GET，但 curl -F 实际上会发送 POST 请求
                # httpx 的 GET 不支持 body，所以使用 POST
                response = await client.post(url, headers=headers, files=files)

                logger.info(f"[COS] Response status: {response.status_code}")
                logger.info(f"[COS] Response headers: {dict(response.headers)}")

                if response.status_code == 200:
                    # 写入本地文件
                    local_path.write_bytes(response.content)
                    logger.info(f"Downloaded: {cos_path} -> {local_path} ({len(response.content)} bytes)")
                    return True
                else:
                    logger.error(
                        f"COS download failed: {response.status_code} - {response.text[:500]}"
                    )
                    return False

        except httpx.TimeoutException as e:
            logger.error(f"COS download timeout (60s): {cos_path} - {str(e)}")
            return False
        except Exception as e:
            import traceback
            logger.error(f"COS download error: {type(e).__name__}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    async def upload_file(
        self,
        local_path: Path,
        user_token: str,
        cos_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        上传本地文件到 COS

        Args:
            local_path: 本地文件路径
            user_token: 用户鉴权 Token
            cos_path: COS 目标路径（可选，不提供则由服务端生成）

        Returns:
            上传成功返回 COS 路径/URL，失败返回 None
        """
        if not user_token:
            logger.error("COS upload failed: user_token is required")
            return None

        if not local_path.exists():
            logger.error(f"File not found: {local_path}")
            return None

        try:
            url = f"{self.base_url}/cos/upload"
            headers = {"user-token": user_token}

            # 禁用代理，因为 COS 是内网地址
            async with httpx.AsyncClient(
                timeout=self.timeout,
                trust_env=False
            ) as client:
                # 读取文件内容
                file_content = local_path.read_bytes()
                files = {
                    "file": (local_path.name, file_content),
                }
                # 必需参数：fileName，isUrl 设为 false 返回存储路径（企微需要的格式）
                data = {
                    "fileName": local_path.name,  # 必需：文件名
                    "isUrl": "false",             # 返回存储路径（如 dep-taf/alin/xxx/file.txt）
                }
                if cos_path:
                    data["staticPath"] = cos_path  # 可选：自定义存储路径

                logger.info(f"[COS] Upload request: url={url}, fileName={local_path.name}")
                logger.info(f"[COS] Upload form data: {data}")

                response = await client.post(
                    url, headers=headers, files=files, data=data
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"[COS] Upload response: {result}")
                    # 直接使用 COS 返回的 path
                    uploaded_path = result.get("path") or result.get("file_path")
                    logger.info(f"Uploaded: {local_path} -> {uploaded_path}")
                    return uploaded_path
                else:
                    logger.error(
                        f"COS upload failed: {response.status_code} - {response.text}"
                    )
                    return None

        except httpx.TimeoutException:
            logger.error(f"COS upload timeout: {local_path}")
            return None
        except Exception as e:
            logger.error(f"COS upload error: {e}")
            return None

    def parse_cos_url(self, cos_url: str) -> tuple[str, str]:
        """
        解析 COS URL

        Args:
            cos_url: 如 cos://bucket/path/to/file.xlsx

        Returns:
            (bucket, path) 元组
        """
        if cos_url.startswith("cos://"):
            path = cos_url[6:]
            parts = path.split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
            return parts[0], ""
        return "", cos_url


# 全局实例
cos_client = COSClient()
