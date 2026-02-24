"""
主动推送服务 - 通过 sendMsg MCP 插件主动发送企微消息

用于 SDK 处理超时后，异步完成时主动将结果推送给用户。
"""
import asyncio
import logging
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class SendMessageError(Exception):
    """sendMsg MCP 业务错误（如频率限制、对话不存在等）"""
    pass


class ProactiveMessenger:
    """通过 sendMsg MCP 插件主动发送企微消息"""

    MAX_RETRIES = 3            # 最多重试 3 次（共 4 次尝试）
    RETRY_BASE_DELAY = 3       # 基础延迟 3 秒
    RETRY_BACKOFF_FACTOR = 2   # 指数退避: 3s → 6s → 12s

    async def send_message_list(
        self,
        message_list: List,
        conversation_id: Optional[str] = None,
        user_name: Optional[str] = None,
        group_chat_name: Optional[str] = None,
        is_group: Optional[bool] = None,
    ):
        """
        将 message_list 通过 sendMsg 发送给用户

        策略：
        - 纯文本 → messageType=text
        - 文件 → messageType=file，content=COS路径
        - 图片 → messageType=image，content=COS路径
        - 文本+图片混合 → messageType=combined（图文消息）
        - 有文件时 → 先发 combined/text，再逐个发 file
        """
        if not message_list:
            logger.warning("[SENDMSG] Empty message_list, nothing to send")
            return

        if not settings.sendmsg_api_url:
            logger.error("[SENDMSG] sendmsg_api_url not configured, cannot send")
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

        # 确定 sendType 和对话标识
        # 优先使用 is_group 参数（支持未命名群聊），否则用 group_chat_name 判断
        if is_group is not None:
            send_type = "3" if is_group else "1"
        else:
            send_type = "3" if group_chat_name else "1"
        conversation_name = group_chat_name or user_name or ""

        # 1. 发送文本（和图片合并为 combined，如果有图片的话）
        if text_items:
            combined_text = "\n\n".join(text_items)

            if image_items:
                # 文本+图片 → combined 图文消息
                # combined 格式：文本内容，图片作为附件
                # 先发文本
                await self._send_single(
                    content=combined_text,
                    message_type="text",
                    send_type=send_type,
                    conversation_id=conversation_id,
                    conversation_name=conversation_name,
                )
                await asyncio.sleep(1.5)

                # 再逐个发图片
                for img_path in image_items:
                    await self._send_single(
                        content=img_path,
                        message_type="image",
                        send_type=send_type,
                        conversation_id=conversation_id,
                        conversation_name=conversation_name,
                    )
                    await asyncio.sleep(1.5)
            else:
                # 纯文本
                await self._send_single(
                    content=combined_text,
                    message_type="text",
                    send_type=send_type,
                    conversation_id=conversation_id,
                    conversation_name=conversation_name,
                )
                await asyncio.sleep(1.5)
        elif image_items:
            # 只有图片没有文本
            for img_path in image_items:
                await self._send_single(
                    content=img_path,
                    message_type="image",
                    send_type=send_type,
                    conversation_id=conversation_id,
                    conversation_name=conversation_name,
                )
                await asyncio.sleep(1.5)

        # 2. 逐个发送文件
        for file_path in file_items:
            await self._send_single(
                content=file_path,
                message_type="file",
                send_type=send_type,
                conversation_id=conversation_id,
                conversation_name=conversation_name,
            )
            await asyncio.sleep(1.5)

        logger.info(
            f"[SENDMSG] Sent {len(text_items)} text, "
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
        """发送纯文本消息"""
        # 优先使用 is_group 参数（支持未命名群聊），否则用 group_chat_name 判断
        if is_group is not None:
            send_type = "3" if is_group else "1"
        else:
            send_type = "3" if group_chat_name else "1"
        conversation_name = group_chat_name or user_name or ""

        return await self._send_single(
            content=content,
            message_type="text",
            send_type=send_type,
            conversation_id=conversation_id,
            conversation_name=conversation_name,
        )

    async def _send_single(
        self,
        content: str,
        message_type: str,
        send_type: str,
        conversation_id: Optional[str],
        conversation_name: str,
    ):
        """
        发送单条消息（带退避重试）

        sendMsg 参数规则：
        - 群聊（sendType=3）：使用 conversationId
        - 私聊（sendType=1）：使用 conversationName（用户名）

        重试策略：所有错误默认重试，退避间隔递增 3s → 6s → 12s
        注意：错误使用会导致 B2AA1002（对话不存在）
        """
        # 诊断日志：打印接收到的参数
        logger.info(
            f"[SEND PARAMS] is_group={send_type == '3'}, conversation_id={conversation_id}, "
            f"send_type={send_type}, conversation_name={conversation_name}"
        )
        arguments = {
            "authKey": settings.sendmsg_auth_key,
            "sendType": send_type,
            "depUserId": settings.sendmsg_dep_user_id,
            "content": content,
            "messageType": message_type,
            "fullOutPut": "Y",
        }

        # 群聊和私聊都使用 conversationId
        if conversation_id:
            arguments["conversationId"] = conversation_id
        else:
            # 回退：私聊没有 conversationId 时用 conversationName
            if conversation_name:
                arguments["conversationName"] = conversation_name
            logger.warning(f"[SENDMSG] No conversationId, fallback to conversationName={conversation_name}")

        logger.info(
            f"[SENDMSG] Full arguments: {{{', '.join(f'{k}={repr(v[:80]) if isinstance(v, str) and len(v) > 80 else repr(v)}' for k, v in arguments.items())}}}"
        )

        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                result = await self._call_sendmsg(arguments)

                # 检查 MCP 返回的业务错误（如频率限制、对话不存在等）
                if hasattr(result, 'isError') and result.isError:
                    error_text = str(result.content) if hasattr(result, 'content') else str(result)
                    raise SendMessageError(error_text)

                logger.info(f"[SENDMSG] Send confirmed (attempt {attempt + 1})")
                return result

            except Exception as e:
                last_error = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (self.RETRY_BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        f"[SENDMSG] Attempt {attempt + 1}/{self.MAX_RETRIES + 1} failed: {e}, "
                        f"retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[SENDMSG] All {self.MAX_RETRIES + 1} attempts failed: {last_error}"
                    )
                    raise

    async def _call_sendmsg(self, arguments: dict) -> dict:
        """
        调用 sendMsg MCP 工具（带 60s 总超时）

        使用 MCP Python SDK 的 streamablehttp_client 连接 sendMsg 服务。
        整体包裹 60s 超时，防止 MCP 服务无响应导致调用方卡死。
        """
        try:
            return await asyncio.wait_for(
                self._call_sendmsg_inner(arguments),
                timeout=60,
            )
        except asyncio.TimeoutError:
            raise Exception("MCP sendmsg timed out after 60s")

    async def _call_sendmsg_inner(self, arguments: dict) -> dict:
        """
        实际调用 sendMsg MCP 工具

        注意：必须禁用代理（trust_env=False），否则内网地址走代理会 502。
        """
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = settings.sendmsg_api_url
        logger.info(f"[SENDMSG] Connecting to MCP service: {url}")

        def _no_proxy_client_factory(
            headers=None, timeout=None, auth=None,
        ):
            kwargs = {"follow_redirects": True, "trust_env": False}
            if timeout is not None:
                kwargs["timeout"] = timeout
            else:
                kwargs["timeout"] = httpx.Timeout(30, read=300)
            if headers is not None:
                kwargs["headers"] = headers
            if auth is not None:
                kwargs["auth"] = auth
            return httpx.AsyncClient(**kwargs)

        async with streamablehttp_client(
            url=url,
            httpx_client_factory=_no_proxy_client_factory,
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("sendToUser", arguments=arguments)
                logger.info(f"[SENDMSG] MCP call completed")
                return result


# 全局实例
proactive_messenger = ProactiveMessenger()
