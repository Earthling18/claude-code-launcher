"""
飞书事件解析

解析飞书 im.message.receive_v1 事件为内部标准格式，
输出可直接构建 ChatRequest 的 dict。

同时提供事件去重和 SDK 类型对象转 dict 的共享逻辑，
供 webhook 和 WebSocket 长连接两种模式复用。
"""
import json
import logging
import re
import time
from typing import Any, Dict, Optional, Set

from app.config import feishu_settings

logger = logging.getLogger(__name__)

# ---- 事件去重（webhook 和 ws_client 共用） ----
_processed_events: Set[str] = set()
_event_timestamps: Dict[str, float] = {}
EVENT_DEDUP_TTL = 300  # 5 分钟过期


def _cleanup_old_events():
    """清理过期的事件 ID"""
    now = time.time()
    expired = [
        eid for eid, ts in _event_timestamps.items()
        if now - ts > EVENT_DEDUP_TTL
    ]
    for eid in expired:
        _processed_events.discard(eid)
        _event_timestamps.pop(eid, None)


def check_and_mark_event(event_id: str) -> bool:
    """
    检查事件是否已处理，未处理则标记。

    Returns:
        True 表示新事件（已标记），False 表示重复事件
    """
    _cleanup_old_events()
    if event_id in _processed_events:
        return False
    _processed_events.add(event_id)
    _event_timestamps[event_id] = time.time()
    return True


def sdk_event_to_dict(data) -> Optional[Dict[str, Any]]:
    """
    将 lark SDK 的 P2ImMessageReceiveV1 类型对象转为与 webhook body 相同结构的 dict。

    SDK WebSocket 模式下收到的事件是类型化对象，需要转为 dict 以复用 parse_event()。

    Args:
        data: P2ImMessageReceiveV1 SDK 事件对象

    Returns:
        与 webhook body 格式一致的 dict，转换失败返回 None
    """
    try:
        header = data.header
        event = data.event

        sender_id = event.sender.sender_id
        message = event.message

        result = {
            "header": {
                "event_id": header.event_id or "",
                "event_type": header.event_type or "",
            },
            "event": {
                "sender": {
                    "sender_id": {
                        "open_id": sender_id.open_id or "",
                        "user_id": sender_id.user_id or "",
                        "union_id": sender_id.union_id or "",
                    },
                },
                "message": {
                    "chat_id": message.chat_id or "",
                    "chat_type": message.chat_type or "",
                    "message_type": message.message_type or "",
                    "content": message.content or "{}",
                    "message_id": message.message_id or "",
                    "parent_id": getattr(message, "parent_id", "") or "",
                    "mentions": [],
                },
            },
        }

        # 转换 mentions
        if message.mentions:
            for m in message.mentions:
                result["event"]["message"]["mentions"].append({
                    "key": m.key or "",
                    "id": {
                        "open_id": m.id.open_id if m.id else "",
                        "user_id": m.id.user_id if m.id else "",
                    },
                    "name": m.name or "",
                })

        return result

    except Exception as e:
        logger.error(f"[FEISHU_EVENT] Failed to convert SDK event to dict: {e}", exc_info=True)
        return None


def handle_url_verification(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    处理 URL verification challenge

    飞书在注册 webhook 时会发送验证请求，需要原样返回 challenge。

    Returns:
        验证响应 dict，如果不是验证请求则返回 None
    """
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info(f"[FEISHU_EVENT] URL verification challenge received")
        return {"challenge": challenge}
    return None


def verify_token(body: Dict[str, Any]) -> bool:
    """验证事件的 verification_token"""
    token = body.get("token", "")
    if not feishu_settings.verification_token:
        return True  # 未配置 token 则跳过验证
    return token == feishu_settings.verification_token


def parse_event(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    解析飞书事件为内部标准格式

    支持 v2 事件格式（im.message.receive_v1）。

    Returns:
        标准化 dict，包含 ChatRequest 所需字段，解析失败返回 None
    """
    # v2 事件格式
    header = body.get("header", {})
    event_type = header.get("event_type", "")

    if event_type != "im.message.receive_v1":
        logger.debug(f"[FEISHU_EVENT] Ignoring event type: {event_type}")
        return None

    event = body.get("event", {})
    sender = event.get("sender", {}).get("sender_id", {})
    message = event.get("message", {})

    # 提取基本信息
    open_id = sender.get("open_id", "")
    employee_id = sender.get("user_id", "")
    union_id = sender.get("union_id", "")
    chat_id = message.get("chat_id", "")
    chat_type = message.get("chat_type", "")  # "p2p" 或 "group"
    message_type = message.get("message_type", "")
    content_str = message.get("content", "{}")
    mentions = message.get("mentions") or []

    # user_id 加 feishu_ 前缀，天然隔离
    user_id = f"feishu_{open_id}"

    # 会话 ID：群聊用 chat_id，私聊用 open_id
    if chat_type == "group":
        conversation_id = chat_id
        conversation_type = "GROUP"
    else:
        conversation_id = open_id
        conversation_type = "PRIVATE"

    # 解析消息内容
    query, query_info = _parse_message_content(
        message_type, content_str, mentions
    )

    if query is None and query_info is None:
        logger.debug(f"[FEISHU_EVENT] Unsupported message_type: {message_type}")
        return None

    # session_id: 用 chat_id 或 open_id（保持稳定）
    session_id = conversation_id

    # 提取 message_id（用于下载消息附件）
    message_id = message.get("message_id", "")

    result = {
        "session_id": session_id,
        "user_id": user_id,
        "query": query or "",
        "conversation_id": conversation_id,
        "conversation_type": conversation_type,
        "channel": "feishu",
    }

    if query_info:
        # 回填 message_id 到每个文件项（下载消息附件需要）
        for item in query_info:
            if isinstance(item, dict) and item.get("type") in ("image", "file"):
                item["message_id"] = message_id
        result["query_info"] = query_info

    # 诊断用：保留原始用户标识字段
    result["_open_id"] = open_id
    result["_employee_id"] = employee_id
    result["_union_id"] = union_id

    # 被引用消息 ID（用于获取引用内容）
    parent_id = message.get("parent_id", "")
    if parent_id:
        result["_parent_id"] = parent_id

    # 事件 ID（用于去重）
    event_id = header.get("event_id", "")
    if event_id:
        result["_event_id"] = event_id

    return result


def _parse_message_content(
    message_type: str,
    content_str: str,
    mentions: list,
) -> tuple:
    """
    解析飞书各种消息类型

    Returns:
        (query, query_info) 元组
    """
    try:
        content = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        content = {}

    if message_type == "text":
        text = content.get("text", "")
        text = _remove_mentions(text, mentions)
        return text.strip(), None

    elif message_type == "image":
        image_key = content.get("image_key", "")
        if image_key:
            query_info = [{"type": "image", "content": image_key}]
            return "", query_info
        return None, None

    elif message_type == "file":
        file_key = content.get("file_key", "")
        file_name = content.get("file_name", "file")
        if file_key:
            query_info = [{"type": "file", "content": file_key, "filename": file_name}]
            return "", query_info
        return None, None

    elif message_type == "post":
        # 富文本：遍历所有段落提取文本和图片
        title = content.get("title", "")
        body_content = content.get("content", [])
        texts = []
        files = []

        if title:
            texts.append(title)

        for paragraph in body_content:
            for element in paragraph:
                tag = element.get("tag", "")
                if tag == "text":
                    texts.append(element.get("text", ""))
                elif tag == "a":
                    texts.append(element.get("text", "") + " " + element.get("href", ""))
                elif tag == "at":
                    # 跳过 @mention
                    pass
                elif tag == "img":
                    image_key = element.get("image_key", "")
                    if image_key:
                        files.append({"type": "image", "content": image_key})

        combined_text = " ".join(texts).strip()
        combined_text = _remove_mentions(combined_text, mentions)

        if files:
            query_info = [{"type": "text", "content": combined_text}] + files if combined_text else files
            return combined_text, query_info

        return combined_text, None

    elif message_type == "sticker":
        return "[用户发送了一个表情贴纸]", None

    else:
        # 不支持的消息类型
        return None, None


def _remove_mentions(text: str, mentions: list) -> str:
    """去除 @mention 占位符"""
    if not mentions:
        return text

    for mention in mentions:
        key = mention.get("key", "")
        if key:
            text = text.replace(key, "")

    # 清理多余空格
    text = re.sub(r"\s+", " ", text).strip()
    return text
