"""
飞书消息推送

对应 proactive_messenger.py，提供相同的 send_text() / send_message_list() 签名，
通过飞书 Open API 发送消息。
"""
import asyncio
import json
import logging
from typing import List, Optional

import httpx

from app.channels.feishu.auth import feishu_auth, FEISHU_API_BASE

logger = logging.getLogger(__name__)


class FeishuMessenger:
    """飞书消息推送器"""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2
    RETRY_BACKOFF_FACTOR = 2  # 2s → 4s → 8s

    def _detect_receive_id_type(self, conversation_id: str) -> str:
        """
        根据 ID 前缀判断 receive_id_type

        - oc_ 开头 → chat_id（群聊）
        - ou_ 开头 → open_id（私聊）
        """
        if conversation_id.startswith("oc_"):
            return "chat_id"
        return "open_id"

    async def send_message_list(
        self,
        message_list: List,
        conversation_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_chat_name: Optional[str] = None,
        is_group: Optional[bool] = None,
    ):
        """
        将 message_list 通过飞书 API 发送

        与 ProactiveMessenger.send_message_list() 签名一致。
        """
        if not message_list:
            logger.warning("[FEISHU_MSG] Empty message_list, nothing to send")
            return

        if not conversation_id:
            logger.error("[FEISHU_MSG] No conversation_id, cannot send")
            return

        # 分类消息
        text_items = []
        image_items = []
        file_items = []

        for item in message_list:
            item_type = item.type if hasattr(item, "type") else item.get("type", "")
            item_content = item.content if hasattr(item, "content") else item.get("content", "")

            if item_type == "txt":
                text_items.append(item_content)
            elif item_type == "image":
                image_items.append(item_content)
            elif item_type == "file":
                file_items.append(item_content)

        # 发送文本
        if text_items:
            combined_text = "\n\n".join(text_items)
            await self._send_text_message(conversation_id, combined_text)
            await asyncio.sleep(0.5)

        # 发送图片
        for image_key in image_items:
            await self._send_image_message(conversation_id, image_key)
            await asyncio.sleep(0.5)

        # 发送文件
        for file_key in file_items:
            await self._send_file_message(conversation_id, file_key)
            await asyncio.sleep(0.5)

        logger.info(
            f"[FEISHU_MSG] Sent {len(text_items)} text, "
            f"{len(image_items)} image, {len(file_items)} file messages"
        )

    async def send_text(
        self,
        content: str,
        conversation_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_chat_name: Optional[str] = None,
        is_group: Optional[bool] = None,
    ):
        """发送纯文本消息，签名与 ProactiveMessenger.send_text() 一致"""
        if not conversation_id:
            logger.error("[FEISHU_MSG] No conversation_id, cannot send text")
            return

        await self._send_text_message(conversation_id, content)

    async def _send_text_message(self, receive_id: str, text: str):
        """发送文本消息"""
        content = json.dumps({"text": text})
        await self._send_message(receive_id, "text", content)

    async def _send_image_message(self, receive_id: str, image_key: str):
        """发送图片消息"""
        content = json.dumps({"image_key": image_key})
        await self._send_message(receive_id, "image", content)

    async def _send_file_message(self, receive_id: str, file_key: str):
        """发送文件消息"""
        content = json.dumps({"file_key": file_key})
        await self._send_message(receive_id, "file", content)

    async def _send_message(self, receive_id: str, msg_type: str, content: str):
        """
        调用飞书发送消息 API（带指数退避重试）

        POST /open-apis/im/v1/messages?receive_id_type={type}
        """
        receive_id_type = self._detect_receive_id_type(receive_id)
        url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type={receive_id_type}"

        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content,
        }

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                token = await feishu_auth.get_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                }

                async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    data = resp.json()

                if data.get("code") == 0:
                    logger.info(
                        f"[FEISHU_MSG] Sent {msg_type} to {receive_id} "
                        f"(attempt {attempt + 1})"
                    )
                    return data
                else:
                    raise Exception(
                        f"Feishu API error: code={data.get('code')}, msg={data.get('msg')}"
                    )

            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (self.RETRY_BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        f"[FEISHU_MSG] Attempt {attempt + 1}/{self.MAX_RETRIES + 1} "
                        f"failed: {e}, retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[FEISHU_MSG] All {self.MAX_RETRIES + 1} attempts failed: {last_error}"
                    )
                    raise


# 全局实例
feishu_messenger = FeishuMessenger()
