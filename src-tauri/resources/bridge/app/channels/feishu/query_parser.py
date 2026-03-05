"""
飞书查询解析（薄封装）

event_handler.py 已将飞书消息转换为 query + query_info 格式（与企微一致），
此处直接委托给现有的 parse_query_info()。

飞书特殊处理：表情文字（如 [看]、[笑哭]）以 [ 开头，会被通用解析器误判为 JSON 而丢弃。
在委托前检测并包装为 query_info text item 绕过该问题。
"""
import json
import logging
from typing import Optional

from app.core.query_parser import parse_query_info, ParsedQuery

logger = logging.getLogger(__name__)


def parse_feishu_query(
    query: str,
    query_info=None,
    history_list: Optional[str] = None,
) -> ParsedQuery:
    """
    解析飞书消息（委托给通用解析器）

    Args:
        query: 文本内容
        query_info: 附件列表（与企微格式一致）
        history_list: 对话历史（飞书暂不使用）

    Returns:
        ParsedQuery 标准解析结果
    """
    # 飞书表情文字（如 [看]、[笑哭]、[看]喜欢）以 [ 开头，
    # 会被通用解析器误判为 JSON 而跳过。
    # 仅在 query_info 为空且 query 不是合法 JSON 时包装为 text item。
    if query and query_info is None:
        stripped = query.strip()
        if stripped.startswith('[') or stripped.startswith('{'):
            try:
                json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                logger.info(f"[FEISHU_PARSE] Emoji/sticker text detected, wrapping as query_info: {stripped[:80]}")
                query_info = json.dumps([{"type": "text", "content": stripped}], ensure_ascii=False)

    return parse_query_info(query, query_info, history_list)
