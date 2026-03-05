"""
飞书群聊历史消息拉取

调用飞书 IM API 获取群聊最近消息，转换为与企微 history_list 兼容的 JSON 字符串，
供 format_group_chat_history() 消费。
"""
import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from app.channels.feishu.auth import feishu_auth, FEISHU_API_BASE

logger = logging.getLogger(__name__)


async def fetch_group_history(chat_id: str, limit: int = 50) -> Optional[str]:
    """
    拉取飞书群聊最近消息，转换为 history_list JSON 字符串。

    API: GET /open-apis/im/v1/messages
    参数: container_id_type=chat, container_id={chat_id}, page_size={limit}

    Returns:
        JSON 字符串，格式与企微 history_list 兼容：
        [{"user_name": "...", "message_content": "...", "message_time": "...", "message_type": "text"}, ...]
        拉取失败返回 None
    """
    try:
        token = await feishu_auth.get_token()
        headers = {"Authorization": f"Bearer {token}"}

        url = (
            f"{FEISHU_API_BASE}/im/v1/messages"
            f"?container_id_type=chat&container_id={chat_id}"
            f"&page_size={limit}&sort_type=ByCreateTimeDesc"
        )

        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            logger.warning(
                f"[FEISHU_HISTORY] API error: code={data.get('code')}, msg={data.get('msg')}"
            )
            return None

        items = data.get("data", {}).get("items", [])
        if not items:
            logger.debug(f"[FEISHU_HISTORY] No messages for chat_id={chat_id}")
            return None

        history = []
        for item in items:
            # 过滤机器人自己发送的消息
            sender = item.get("sender", {})
            if sender.get("sender_type") == "app":
                continue

            # 提取文本内容
            msg_type = item.get("msg_type", "")
            body = item.get("body", {})
            content_str = body.get("content", "{}")

            text = _extract_text(msg_type, content_str)
            if not text:
                continue

            # 发送者标识：使用 open_id 短标识（避免额外调用用户信息 API）
            sender_id = sender.get("id", sender.get("sender_id", {}).get("open_id", "unknown"))

            # create_time 是 Unix 毫秒时间戳，转换为 YYYYMMDDHHmmss 格式
            create_time = item.get("create_time", "")
            message_time = _format_time(create_time)

            history.append({
                "user_name": sender_id,
                "message_content": text,
                "message_time": message_time,
                "message_type": "text",
            })

        # API 返回按创建时间倒序，反转为正序（与企微 history_list 一致）
        history.reverse()

        if history:
            logger.info(f"[FEISHU_HISTORY] Fetched {len(history)} messages for chat_id={chat_id}")
            return json.dumps(history, ensure_ascii=False)

        return None

    except Exception as e:
        logger.warning(f"[FEISHU_HISTORY] Failed to fetch history for chat_id={chat_id}: {e}")
        return None


def _extract_text(msg_type: str, content_str: str) -> str:
    """从消息 body.content 中提取文本"""
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return ""

    if msg_type == "text":
        return content.get("text", "").strip()
    elif msg_type == "post":
        # 富文本：提取所有文本段落
        texts = []
        title = content.get("title", "")
        if title:
            texts.append(title)
        for paragraph in content.get("content", []):
            for element in paragraph:
                if element.get("tag") == "text":
                    texts.append(element.get("text", ""))
                elif element.get("tag") == "a":
                    texts.append(element.get("text", ""))
        return " ".join(texts).strip()
    elif msg_type == "sticker":
        return "[表情贴纸]"
    else:
        # image/file/audio/video 等：用占位描述
        return f"[{msg_type}]" if msg_type else ""


def _format_time(create_time: str) -> str:
    """将 Unix 毫秒时间戳转为 YYYYMMDDHHmmss 格式"""
    if not create_time:
        return ""
    try:
        ts = int(create_time) / 1000  # 毫秒 → 秒
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%Y%m%d%H%M%S")
    except (ValueError, OSError):
        return ""
