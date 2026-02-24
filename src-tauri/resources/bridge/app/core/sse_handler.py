"""
SSE (Server-Sent Events) 处理器
将 Claude SDK 消息流转换为 SSE 事件
"""
import json
from typing import Any, AsyncGenerator, Dict, List
import logging

# 导入 SDK 类型
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    UserMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)

logger = logging.getLogger(__name__)


class SSEEvent:
    """SSE 事件"""

    def __init__(
        self,
        event: str,
        data: Any,
        id: str = None,
        retry: int = None,
    ):
        self.event = event
        self.data = data
        self.id = id
        self.retry = retry

    def encode(self) -> str:
        """编码为 SSE 格式字符串"""
        lines = []

        if self.id:
            lines.append(f"id: {self.id}")

        if self.retry:
            lines.append(f"retry: {self.retry}")

        if self.event:
            lines.append(f"event: {self.event}")

        # 序列化 data
        if isinstance(self.data, (dict, list)):
            data_str = json.dumps(self.data, ensure_ascii=False)
        else:
            data_str = str(self.data)

        # 处理多行数据
        for line in data_str.split("\n"):
            lines.append(f"data: {line}")

        lines.append("")  # 空行表示事件结束
        return "\n".join(lines) + "\n"


def create_message_event(content: str) -> SSEEvent:
    """创建文本消息事件"""
    return SSEEvent(
        event="message",
        data={"type": "text", "content": content},
    )


def create_tool_event(tool_name: str, status: str, result: Any = None) -> SSEEvent:
    """创建工具调用事件"""
    data = {
        "type": "tool_use",
        "tool": tool_name,
        "status": status,
    }
    if result is not None:
        data["result"] = result
    return SSEEvent(event="tool_use", data=data)


def create_error_event(error: str) -> SSEEvent:
    """创建错误事件"""
    return SSEEvent(
        event="error",
        data={"type": "error", "message": error},
    )


def create_done_event(usage: Dict[str, Any] = None, cost_usd: float = None) -> SSEEvent:
    """创建完成事件"""
    data = {"type": "done"}
    if usage:
        data["usage"] = usage
    if cost_usd is not None:
        data["cost_usd"] = cost_usd
    return SSEEvent(event="done", data=data)


class SSEHandler:
    """
    SSE 处理器
    将 Claude SDK 的消息流转换为 SSE 事件流
    """

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    async def convert_stream(
        self, sdk_stream: AsyncGenerator
    ) -> AsyncGenerator[str, None]:
        """
        将 SDK 消息流转换为 SSE 事件流

        Args:
            sdk_stream: Claude SDK 返回的消息流

        Yields:
            SSE 格式的字符串
        """
        try:
            async for message in sdk_stream:
                events = self._convert_message(message)
                for event in events:
                    yield event.encode()

            # 发送完成事件
            done_event = create_done_event(
                usage={
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                },
                cost_usd=self.total_cost_usd,
            )
            yield done_event.encode()

        except Exception as e:
            logger.error(f"Error in SSE stream: {e}")
            error_event = create_error_event(str(e))
            yield error_event.encode()

    def _convert_message(self, message: Any) -> List[SSEEvent]:
        """
        转换单个 SDK 消息为 SSE 事件

        Args:
            message: SDK 消息对象

        Returns:
            SSE 事件列表
        """
        events = []

        # 使用 isinstance 检查消息类型（根据官方 SDK 文档）
        if isinstance(message, AssistantMessage):
            # 助手消息 - 包含 Claude 的回复
            for block in message.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        events.append(create_message_event(block.text))
                elif isinstance(block, ToolUseBlock):
                    events.append(create_tool_event(block.name, "started"))

        elif isinstance(message, ResultMessage):
            # 结果消息 - 包含成本信息
            if message.total_cost_usd:
                self.total_cost_usd = message.total_cost_usd
            if message.usage:
                self.total_input_tokens = message.usage.get("input_tokens", 0)
                self.total_output_tokens = message.usage.get("output_tokens", 0)

        elif isinstance(message, UserMessage):
            # 用户消息 - 可能包含工具结果
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        events.append(
                            create_tool_event(
                                block.tool_use_id, "completed", block.content
                            )
                        )

        elif isinstance(message, SystemMessage):
            # 系统消息
            logger.debug(f"System message: {message.subtype} - {message.data}")

        return events


def format_blocking_response(messages: list, usage: Dict[str, Any] = None, only_last_text: bool = False) -> Dict:
    """
    格式化阻塞式响应

    Args:
        messages: 消息列表
        usage: token 使用统计
        only_last_text: 是否只返回最后一个 TextBlock（用于全异步模式，避免重复）

    Returns:
        响应字典
    """
    text_parts = []
    tool_calls = []
    final_usage = usage or {}
    cost_usd = 0.0

    for message in messages:
        # 使用 isinstance 检查消息类型（根据官方 SDK 文档）
        if isinstance(message, AssistantMessage):
            # 助手消息 - 包含 Claude 的回复
            for block in message.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls.append({
                        "name": block.name,
                        "id": block.id,
                        "input": block.input,
                    })

        elif isinstance(message, ResultMessage):
            # 结果消息 - 包含成本和 token 统计
            if message.total_cost_usd:
                cost_usd = message.total_cost_usd
            if message.usage:
                final_usage = {
                    "input_tokens": message.usage.get("input_tokens", 0),
                    "output_tokens": message.usage.get("output_tokens", 0),
                }

    # only_last_text=True 时，只返回最后一个 TextBlock（用于全异步模式）
    if only_last_text and text_parts:
        content = text_parts[-1]
    else:
        content = "\n".join(text_parts)

    return {
        "content": content,
        "tool_calls": tool_calls,
        "usage": final_usage,
        "cost_usd": cost_usd,
    }
