"""
Agent Bridge Client - 桥接客户端

运行在用户机器上，负责：
- 连接到中央服务端
- 连接到本地 OpenClaw Gateway 或自定义 HTTP Agent
- 转发任务和结果
- 支持流式响应

支持三种后端模式：
- openclaw: 通过 WebSocket 连接本地 OpenClaw Gateway
- http: 通过 HTTP POST 连接自定义 Agent (V2 API 格式)
- openai: 通过 OpenAI 兼容 API 连接 (支持 OpenAI/Azure/Ollama/vLLM 等)
"""

import asyncio
import json
import logging
import os
import platform
import uuid
import sys
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass

import aiohttp
import websockets
from websockets.client import WebSocketClientProtocol

class FlushHandler(logging.StreamHandler):
    """Handler that flushes after every emit (for piped embedded Python)"""
    def emit(self, record):
        super().emit(record)
        self.flush()

_handler = FlushHandler(sys.stderr)
_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.root.addHandler(_handler)
logging.root.setLevel(logging.INFO)
logger = logging.getLogger(__name__)


def get_or_create_client_id(config_dir: str = None) -> str:
    """获取或创建持久化的客户端 ID（基于主机名）"""
    if config_dir is None:
        config_dir = os.path.expanduser("~/.agent-bridge")

    os.makedirs(config_dir, exist_ok=True)
    id_file = os.path.join(config_dir, "client_id")

    # 尝试读取已存在的 ID
    if os.path.exists(id_file):
        with open(id_file, "r") as f:
            client_id = f.read().strip()
            if client_id:
                return client_id

    # 生成新 ID：使用主机名，同一台机器始终是同一个 ID
    client_id = platform.node()
    with open(id_file, "w") as f:
        f.write(client_id)

    logger.info(f"生成新客户端 ID: {client_id}")
    return client_id


@dataclass
class BridgeConfig:
    """桥接配置"""
    # 服务端配置
    server_url: str = "ws://localhost:8765"

    # 本地 OpenClaw 配置
    openclaw_url: str = "ws://127.0.0.1:18789"
    openclaw_token: str = ""

    # 客户端标识
    client_id: str = ""

    # 服务端认证 Token (由服务端生成)
    server_token: str = ""

    # 用户绑定 Key (用户的 API Key，用于绑定客户端到用户)
    bind_key: str = ""

    # 后端类型: "openclaw", "http", "openai"
    backend_type: str = "openclaw"

    # "both" 模式下默认路由目标
    default_backend: str = "openclaw"

    # HTTP Agent 配置 (backend_type == "http" 或 "both" 时使用)
    http_agent_url: str = "http://127.0.0.1:5000/v2/chat"
    http_agent_key: str = ""
    http_agent_timeout: float = 300.0

    # OpenAI 兼容 API 配置 (backend_type == "openai" 或 "both" 时使用)
    openai_api_url: str = "https://api.openai.com/v1/chat/completions"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # 重连配置
    reconnect_interval: int = 5
    heartbeat_interval: int = 30

    def __post_init__(self):
        if not self.client_id:
            # 使用持久化的客户端 ID
            self.client_id = get_or_create_client_id()

    @classmethod
    def from_file(cls, path: str) -> "BridgeConfig":
        """从配置文件加载"""
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        client_cfg = data.get("client", {})
        return cls(
            server_url=client_cfg.get("server_url", "ws://localhost:8765"),
            openclaw_url=client_cfg.get("openclaw_url", "ws://127.0.0.1:18789"),
            openclaw_token=client_cfg.get("openclaw_token", ""),
            client_id=client_cfg.get("client_id", ""),
            server_token=client_cfg.get("server_token", ""),
            bind_key=client_cfg.get("bind_key", ""),
            backend_type=client_cfg.get("backend_type", "openclaw"),
            default_backend=client_cfg.get("default_backend", "openclaw"),
            http_agent_url=client_cfg.get("http_agent_url", "http://127.0.0.1:5000/v2/chat"),
            http_agent_key=client_cfg.get("http_agent_key", ""),
            http_agent_timeout=client_cfg.get("http_agent_timeout", 300.0),
            openai_api_url=client_cfg.get("openai_api_url", "https://api.openai.com/v1/chat/completions"),
            openai_api_key=client_cfg.get("openai_api_key", ""),
            openai_model=client_cfg.get("openai_model", "gpt-4o"),
            reconnect_interval=client_cfg.get("reconnect_interval", 5),
            heartbeat_interval=client_cfg.get("heartbeat_interval", 30),
        )


class OpenClawConnection:
    """OpenClaw Gateway 连接管理"""

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.ws: Optional[WebSocketClientProtocol] = None
        self.connected = False
        self.request_id = 0
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.stream_callbacks: Dict[str, Callable[[str], Awaitable[None]]] = {}
        # 等待广播事件的 waiters，key 为 runId
        self.event_waiters: Dict[str, asyncio.Future] = {}
        # 流式事件回调，key 为 runId，value 为 delta 回调
        self.stream_event_callbacks: Dict[str, Callable[[str], Awaitable[None]]] = {}
        # 会话级 waiters，key 为 sessionKey，用于等待子代理完成
        self.session_waiters: Dict[str, asyncio.Future] = {}
        # 会话级流式回调，key 为 sessionKey
        self.session_stream_callbacks: Dict[str, Callable[[str], Awaitable[None]]] = {}

    async def connect(self) -> bool:
        """连接到 OpenClaw Gateway"""
        try:
            self.ws = await websockets.connect(self.url)

            # 等待 challenge (如果有)
            try:
                first_msg = await asyncio.wait_for(self.ws.recv(), timeout=5)
                first_data = json.loads(first_msg)
                if first_data.get("event") == "connect.challenge":
                    logger.debug("收到 OpenClaw challenge")
            except asyncio.TimeoutError:
                pass

            # 发送 connect 请求
            # 有效的 mode 值: webchat, cli, ui, backend, node, probe, test
            self.request_id += 1
            connect_req = {
                "type": "req",
                "id": str(self.request_id),
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": "cli",
                        "version": "2026.2.3-1",
                        "platform": platform.system().lower(),
                        "mode": "backend",
                    },
                    "role": "operator",
                    "scopes": ["operator.read", "operator.write", "operator.admin", "operator.approvals"],
                    "caps": ["streaming"],
                    "commands": [],
                    "permissions": {},
                    "auth": {"token": self.token} if self.token else {},
                    "locale": "zh-CN",
                    "userAgent": "agent-bridge/1.0.0",
                }
            }
            await self.ws.send(json.dumps(connect_req))

            # 等待连接确认
            response = await asyncio.wait_for(self.ws.recv(), timeout=10)
            res_data = json.loads(response)

            if res_data.get("ok"):
                self.connected = True
                logger.info("已连接到本地 OpenClaw Gateway")
                return True
            else:
                logger.error(f"OpenClaw 连接失败: {res_data.get('error')}")
                return False

        except Exception as e:
            logger.error(f"连接 OpenClaw 失败: {e}")
            return False

    async def send_request(self, method: str, params: dict, timeout: float = 60) -> dict:
        """发送请求到 OpenClaw"""
        if not self.connected or not self.ws:
            raise ConnectionError("未连接到 OpenClaw")

        self.request_id += 1
        req_id = str(self.request_id)

        request = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": params,
        }

        # 创建 Future
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[req_id] = future

        try:
            await self.ws.send(json.dumps(request))
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self.pending_requests.pop(req_id, None)

    async def send_streaming_request(
        self,
        method: str,
        params: dict,
        on_chunk: Callable[[str], Awaitable[None]],
        timeout: float = 120
    ) -> dict:
        """发送流式请求到 OpenClaw"""
        if not self.connected or not self.ws:
            raise ConnectionError("未连接到 OpenClaw")

        self.request_id += 1
        req_id = str(self.request_id)

        request = {
            "type": "req",
            "id": req_id,
            "method": method,
            "params": {**params, "stream": True},
        }

        # 创建 Future 和流式回调注册
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[req_id] = future
        self.stream_callbacks[req_id] = on_chunk

        try:
            await self.ws.send(json.dumps(request))
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self.pending_requests.pop(req_id, None)
            self.stream_callbacks.pop(req_id, None)

    async def wait_for_chat_result(self, run_id: str, timeout: float = 120) -> dict:
        """等待 chat 广播事件返回最终结果"""
        future = asyncio.get_event_loop().create_future()
        self.event_waiters[run_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self.event_waiters.pop(run_id, None)

    async def receive_loop(self):
        """接收消息循环"""
        try:
            async for message in self.ws:
                data = json.loads(message)
                msg_type = data.get("type")

                # 记录所有收到的消息（调试用）
                logger.debug(f"WS 收到: type={msg_type} event={data.get('event')}")

                if msg_type == "res":
                    # 响应消息
                    req_id = data.get("id")
                    if req_id in self.pending_requests:
                        self.pending_requests[req_id].set_result(data)

                elif msg_type == "event":
                    # 事件消息
                    event = data.get("event")
                    payload = data.get("payload", {})
                    logger.debug(f"OpenClaw 事件: {event} state={payload.get('state')}")

                    # 处理 agent 事件
                    if event == "agent":
                        stream = payload.get("stream")
                        agent_data = payload.get("data", {})
                        run_id = payload.get("runId")
                        logger.debug(f"agent 事件: runId={run_id} stream={stream}")
                        if stream == "assistant" and isinstance(agent_data, dict):
                            delta = agent_data.get("delta", "")
                            session_key = payload.get("sessionKey", "main")
                            if delta:
                                # runId 级别的流式回调
                                if run_id and run_id in self.stream_event_callbacks:
                                    try:
                                        await self.stream_event_callbacks[run_id](delta)
                                    except Exception as e:
                                        logger.error(f"agent 流式回调错误: {e}")
                                # session 级别的流式回调（用于子代理）
                                elif session_key in self.session_stream_callbacks:
                                    try:
                                        await self.session_stream_callbacks[session_key](delta)
                                    except Exception as e:
                                        logger.error(f"session 流式回调错误: {e}")

                    # 处理 chat 广播事件 (final/error/delta)
                    if event == "chat":
                        run_id = payload.get("runId")
                        state = payload.get("state")
                        logger.debug(f"chat 事件: runId={run_id} state={state}")
                        if state == "delta":
                            # 累积 delta 文本
                            if run_id and run_id in self.event_waiters:
                                msg = payload.get("message", {})
                                if msg:
                                    for part in msg.get("content", []):
                                        if isinstance(part, dict) and part.get("type") == "text":
                                            text = part.get("text", "")
                                            if text:
                                                # 累积到 _delta_text
                                                if not hasattr(self, '_delta_texts'):
                                                    self._delta_texts = {}
                                                self._delta_texts.setdefault(run_id, []).append(text)
                                                logger.debug(f"chat delta: runId={run_id} chunk_len={len(text)}")
                        elif state == "final":
                            session_key = payload.get("sessionKey", "main")
                            message = payload.get("message")
                            # 检查 delta 累积
                            delta_text = ""
                            if hasattr(self, '_delta_texts') and run_id in self._delta_texts:
                                delta_text = "".join(self._delta_texts.pop(run_id, []))
                            if not message and delta_text:
                                message = {
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": delta_text}],
                                }
                            result_data = {"state": "final", "message": message}
                            logger.debug(f"chat final: runId={run_id} has_msg={message is not None}")

                            # runId 级别的 waiter（主代理）
                            if run_id and run_id in self.event_waiters:
                                self.event_waiters[run_id].set_result(result_data)
                            # session 级别的 waiter（子代理完成）
                            elif session_key in self.session_waiters:
                                if not self.session_waiters[session_key].done():
                                    self.session_waiters[session_key].set_result(result_data)

                        elif state == "error":
                            session_key = payload.get("sessionKey", "main")
                            error_data = {"state": "error", "errorMessage": payload.get("errorMessage")}
                            if run_id and run_id in self.event_waiters:
                                logger.warning(f"chat error: runId={run_id} error={payload.get('errorMessage')}")
                                self.event_waiters[run_id].set_result(error_data)
                            elif session_key in self.session_waiters:
                                if not self.session_waiters[session_key].done():
                                    self.session_waiters[session_key].set_result(error_data)

                    # 处理流式事件
                    elif event == "chat.chunk" or event == "agent.chunk":
                        req_id = payload.get("requestId")
                        chunk = payload.get("content", "")
                        if req_id and req_id in self.stream_callbacks:
                            try:
                                await self.stream_callbacks[req_id](chunk)
                            except Exception as e:
                                logger.error(f"流式回调错误: {e}")

        except websockets.exceptions.ConnectionClosed:
            self.connected = False
            logger.warning("OpenClaw 连接断开")
        except Exception as e:
            self.connected = False
            logger.error(f"OpenClaw 接收错误: {e}")

    async def close(self):
        """关闭连接"""
        if self.ws:
            await self.ws.close()
            self.connected = False


class HttpAgentConnection:
    """HTTP Agent 连接管理 - 用于 V2 API 格式的自定义代理"""

    def __init__(self, base_url: str, agent_key: str = "", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.agent_key = agent_key
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """初始化 HTTP 会话"""
        try:
            headers = {}
            if self.agent_key:
                headers["Authorization"] = f"Bearer {self.agent_key}"
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers=headers,
            )
            logger.info(f"HTTP Agent 会话已创建: {self.base_url}")
            return True
        except Exception as e:
            logger.error(f"创建 HTTP Agent 会话失败: {e}")
            return False

    def _build_v2_request(self, payload: dict, streaming: bool = False) -> dict:
        """将 Bridge 任务 payload 透传给 HTTP Agent，仅补充 streaming 字段"""
        request = dict(payload)
        request["streaming"] = streaming
        return request

    async def send_sync_request(self, payload: dict) -> dict:
        """发送同步请求到 HTTP Agent，返回结果"""
        if not self._session:
            raise ConnectionError("HTTP Agent 会话未初始化")

        v2_request = self._build_v2_request(payload, streaming=False)
        logger.info(f"[HTTP] 同步请求: {self.base_url}")
        logger.debug(f"[HTTP] body={json.dumps(v2_request, ensure_ascii=False)[:300]}")

        async with self._session.post(self.base_url, json=v2_request) as resp:
            if resp.status == 401:
                error_text = await resp.text()
                return {"success": False, "error": f"认证失败: {error_text}"}
            if resp.status != 200:
                error_text = await resp.text()
                return {"success": False, "error": f"HTTP {resp.status}: {error_text}"}

            data = await resp.json()
            logger.info(f"[HTTP] 响应: status={resp.status}")
            logger.debug(f"[HTTP] body={json.dumps(data, ensure_ascii=False)[:300]}")
            return {
                "success": True,
                "result": data,
            }

    async def send_streaming_request(
        self,
        payload: dict,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> dict:
        """发送 SSE 流式请求到 HTTP Agent"""
        if not self._session:
            raise ConnectionError("HTTP Agent 会话未初始化")

        v2_request = self._build_v2_request(payload, streaming=True)
        logger.info(f"[HTTP] 流式请求: {self.base_url}")
        logger.debug(f"[HTTP] body={json.dumps(v2_request, ensure_ascii=False)[:300]}")

        chunks = []
        async with self._session.post(self.base_url, json=v2_request) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                return {"success": False, "error": f"HTTP {resp.status}: {error_text}"}

            # 解析 SSE 流
            buffer = ""
            async for raw_chunk in resp.content.iter_any():
                buffer += raw_chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    text = self._parse_sse_event(event_str)
                    if text is not None:
                        chunks.append(text)
                        await on_chunk(text)

            # 处理剩余 buffer
            if buffer.strip():
                text = self._parse_sse_event(buffer)
                if text is not None:
                    chunks.append(text)
                    await on_chunk(text)

        full_content = "".join(chunks)
        logger.info(f"[HTTP] 流式完成, 总长度={len(full_content)}")
        return {
            "success": True,
            "result": {"content": full_content},
        }

    @staticmethod
    def _parse_sse_event(event_str: str) -> Optional[str]:
        """解析单个 SSE 事件，返回文本内容或 None"""
        data_lines = []
        for line in event_str.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if not data_lines:
            return None

        data_str = "\n".join(data_lines)
        if data_str == "[DONE]":
            return None

        try:
            data = json.loads(data_str)
            if "delta" in data:
                return data["delta"]
            elif "message_list" in data:
                return HttpAgentConnection._extract_text_from_v2_response(data)
            elif "content" in data:
                return data["content"]
            else:
                return data_str
        except json.JSONDecodeError:
            return data_str

    @staticmethod
    def _extract_text_from_v2_response(data: dict) -> str:
        """从 V2 API 响应中提取文本内容"""
        message_list = data.get("message_list", [])
        parts = []
        for msg in message_list:
            if isinstance(msg, dict):
                msg_type = msg.get("type", "txt")
                if msg_type in ("txt", "markdown"):
                    content = msg.get("content", "")
                    if content:
                        parts.append(content)
        return "\n".join(parts) if parts else data.get("content", "")

    async def close(self):
        """关闭 HTTP 会话"""
        if self._session:
            await self._session.close()
            self._session = None


class OpenAIConnection:
    """OpenAI 兼容 API 连接管理"""

    def __init__(self, api_url: str, api_key: str, model: str, timeout: float = 300.0):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """初始化 HTTP 会话"""
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers=headers,
            )
            logger.info(f"OpenAI API 会话已创建: {self.api_url} (model={self.model})")
            return True
        except Exception as e:
            logger.error(f"创建 OpenAI API 会话失败: {e}")
            return False

    def _build_request(self, payload: dict, streaming: bool = False) -> dict:
        """将 Bridge 任务 payload 转换为 OpenAI API 格式"""
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": payload.get("message", "")}],
            "stream": streaming,
        }

    async def send_sync_request(self, payload: dict) -> dict:
        """发送同步请求，返回结果"""
        if not self._session:
            raise ConnectionError("OpenAI API 会话未初始化")

        request = self._build_request(payload, streaming=False)
        logger.info(f"OpenAI API 同步请求: model={self.model}")

        async with self._session.post(self.api_url, json=request) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                return {"success": False, "error": f"HTTP {resp.status}: {error_text}"}

            data = await resp.json()
            text = self._extract_text(data)
            return {"success": True, "result": {"content": text}}

    async def send_streaming_request(
        self,
        payload: dict,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> dict:
        """发送 SSE 流式请求"""
        if not self._session:
            raise ConnectionError("OpenAI API 会话未初始化")

        request = self._build_request(payload, streaming=True)
        logger.info(f"OpenAI API 流式请求: model={self.model}")

        chunks = []
        async with self._session.post(self.api_url, json=request) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                return {"success": False, "error": f"HTTP {resp.status}: {error_text}"}

            buffer = ""
            async for raw_chunk in resp.content.iter_any():
                buffer += raw_chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    text = self._parse_sse_event(event_str)
                    if text is not None:
                        chunks.append(text)
                        await on_chunk(text)

            if buffer.strip():
                text = self._parse_sse_event(buffer)
                if text is not None:
                    chunks.append(text)
                    await on_chunk(text)

        return {"success": True, "result": {"content": "".join(chunks)}}

    @staticmethod
    def _parse_sse_event(event_str: str) -> Optional[str]:
        """解析 OpenAI SSE 事件，提取 delta content"""
        data_lines = []
        for line in event_str.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if not data_lines:
            return None

        data_str = "\n".join(data_lines)
        if data_str == "[DONE]":
            return None

        try:
            data = json.loads(data_str)
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    return content
            return None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_text(data: dict) -> str:
        """从 OpenAI 同步响应中提取文本"""
        choices = data.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            return message.get("content", "")
        return ""

    async def close(self):
        """关闭会话"""
        if self._session:
            await self._session.close()
            self._session = None


class BridgeClient:
    """桥接客户端"""

    def __init__(self, config: BridgeConfig):
        self.config = config
        self.server_ws: Optional[WebSocketClientProtocol] = None
        self.openclaw: Optional[OpenClawConnection] = None
        self.http_agent: Optional[HttpAgentConnection] = None
        self.openai_conn: Optional[OpenAIConnection] = None
        self.running = False

    async def connect_server(self) -> bool:
        """连接到中央服务端"""
        try:
            self.server_ws = await websockets.connect(self.config.server_url)

            # 注册（包含可选的认证 Token）
            register_msg = {
                "type": "register",
                "client_id": self.config.client_id,
                "platform": platform.system(),
                "capabilities": ["chat", "agent", "tools", "browser"],
                "backend_type": self.config.backend_type,
            }
            if self.config.server_token:
                register_msg["token"] = self.config.server_token
            if self.config.bind_key:
                register_msg["bind_key"] = self.config.bind_key
            await self.server_ws.send(json.dumps(register_msg))

            # 等待注册确认
            response = await asyncio.wait_for(self.server_ws.recv(), timeout=10)
            res_data = json.loads(response)

            if res_data.get("type") == "registered":
                logger.info(f"已注册到服务端: {self.config.client_id}")
                return True
            else:
                logger.error(f"注册失败: {res_data}")
                return False

        except Exception as e:
            logger.error(f"连接服务端失败: {e}")
            return False

    async def connect_openclaw(self) -> bool:
        """连接到本地 OpenClaw"""
        self.openclaw = OpenClawConnection(
            self.config.openclaw_url,
            self.config.openclaw_token
        )
        return await self.openclaw.connect()

    async def connect_http_agent(self) -> bool:
        """连接到 HTTP Agent"""
        self.http_agent = HttpAgentConnection(
            self.config.http_agent_url,
            self.config.http_agent_key,
            self.config.http_agent_timeout,
        )
        return await self.http_agent.connect()

    async def connect_openai(self) -> bool:
        """连接到 OpenAI 兼容 API"""
        self.openai_conn = OpenAIConnection(
            self.config.openai_api_url,
            self.config.openai_api_key,
            self.config.openai_model,
            self.config.http_agent_timeout,
        )
        return await self.openai_conn.connect()

    async def handle_task(self, task: dict) -> dict:
        """处理任务 — 纯路由层"""
        task_id = task.get("task_id")
        task_type = task.get("task_type")
        payload = task.get("payload", {})
        streaming = task.get("streaming", False)

        logger.info(f"任务: {task_id} type={task_type} stream={streaming}")

        if self.config.backend_type == "both":
            return await self._handle_both_backend_task(task_id, task_type, payload, streaming)
        elif self.config.backend_type == "http":
            return await self._handle_http_agent_task(task_id, task_type, payload, streaming)
        elif self.config.backend_type == "openai":
            return await self._handle_openai_task(task_id, task_type, payload, streaming)
        else:
            return await self._handle_openclaw_task(task_id, task_type, payload, streaming)

    # ---- 双后端路由 ----

    def _resolve_backend(self, task_type: str, payload: dict) -> str:
        """在 both 模式下决定使用哪个后端"""
        # 1. 显式指定
        explicit = payload.get("backend")
        if explicit in ("openclaw", "http", "openai"):
            target = explicit
        else:
            target = self.config.default_backend

        # 2. HTTP/OpenAI 不支持的任务类型，强制走 OpenClaw
        if target in ("http", "openai") and task_type not in ("chat", "agent"):
            target = "openclaw"

        # 3. 容错: 目标后端不可用时回退
        if target == "openclaw" and (not self.openclaw or not self.openclaw.connected):
            if task_type in ("chat", "agent"):
                if self.openai_conn:
                    logger.warning("OpenClaw 不可用，回退到 OpenAI")
                    target = "openai"
                elif self.http_agent:
                    logger.warning("OpenClaw 不可用，回退到 HTTP Agent")
                    target = "http"
        elif target == "http" and not self.http_agent:
            if self.openclaw and self.openclaw.connected:
                logger.warning("HTTP Agent 不可用，回退到 OpenClaw")
                target = "openclaw"
        elif target == "openai" and not self.openai_conn:
            if self.openclaw and self.openclaw.connected:
                logger.warning("OpenAI 不可用，回退到 OpenClaw")
                target = "openclaw"

        return target

    async def _handle_both_backend_task(
        self, task_id: str, task_type: str, payload: dict, streaming: bool
    ) -> dict:
        """双后端模式: 路由到合适的后端"""
        target = self._resolve_backend(task_type, payload)
        logger.debug(f"路由: task={task_id} -> {target}")
        if target == "http":
            return await self._handle_http_agent_task(task_id, task_type, payload, streaming)
        elif target == "openai":
            return await self._handle_openai_task(task_id, task_type, payload, streaming)
        else:
            return await self._handle_openclaw_task(task_id, task_type, payload, streaming)

    # ---- OpenClaw 后端处理 ----

    async def _handle_openclaw_task(
        self, task_id: str, task_type: str, payload: dict, streaming: bool
    ) -> dict:
        """通过 OpenClaw Gateway 处理任务"""
        try:
            if task_type == "chat":
                if streaming:
                    return await self._handle_streaming_chat(task_id, payload)
                # 聊天任务 - chat.send 是异步的
                # 策略: 发送消息 → 等待 run 完成 → 用 chat.history 获取实际回复
                idempotency_key = str(uuid.uuid4())
                session_key = payload.get("session_key", "main")
                result = await self.openclaw.send_request("chat.send", {
                    "message": payload.get("message", ""),
                    "sessionKey": session_key,
                    "idempotencyKey": idempotency_key,
                })
                if not result.get("ok"):
                    return {
                        "success": False,
                        "result": result.get("payload"),
                        "error": result.get("error"),
                    }
                run_id = result.get("payload", {}).get("runId", idempotency_key)
                logger.debug(f"chat.send runId={run_id}, 等待完成...")
                # 等待 run 完成 (final 事件，无论有无 message)
                chat_result = await self.openclaw.wait_for_chat_result(run_id, timeout=120)
                if chat_result.get("state") == "error":
                    return {
                        "success": False,
                        "error": chat_result.get("errorMessage", "模型调用失败"),
                    }
                # final 事件中可能有 message，也可能没有
                message = chat_result.get("message")
                if message and message.get("content"):
                    text = self._extract_text_from_message(message)
                else:
                    # final 无 message，可能是空确认（agent 还在跑）
                    # 先尝试 chat.history
                    logger.debug(f"final 无 message，尝试 chat.history")
                    text = await self._fetch_latest_reply(session_key)

                    # 如果 chat.history 也为空，说明 agent 还未完成
                    # 注册 session waiter 等待真正的结果
                    if not text:
                        logger.debug(f"等待后续结果: session={session_key}")
                        sub_future = asyncio.get_event_loop().create_future()
                        self.openclaw.session_waiters[session_key] = sub_future
                        try:
                            sub_result = await asyncio.wait_for(sub_future, timeout=300)
                            logger.debug(f"后续结果到达: state={sub_result.get('state')}")
                        except asyncio.TimeoutError:
                            logger.warning(f"等待后续结果超时: session={session_key}")
                            self.openclaw.session_waiters.pop(session_key, None)
                            return {"success": False, "error": "等待回复超时"}
                        finally:
                            self.openclaw.session_waiters.pop(session_key, None)

                        if sub_result.get("state") == "error":
                            return {"success": False, "error": sub_result.get("errorMessage", "模型调用失败")}

                        sub_message = sub_result.get("message")
                        if sub_message and sub_message.get("content"):
                            text = self._extract_text_from_message(sub_message)
                        else:
                            text = await self._fetch_latest_reply(session_key)

                # 检查是否为子代理委派消息
                if text and self._is_delegation_message(text):
                    logger.debug(f"子代理委派(非流式), 继续等待")
                    sub_future = asyncio.get_event_loop().create_future()
                    self.openclaw.session_waiters[session_key] = sub_future
                    try:
                        sub_result = await asyncio.wait_for(sub_future, timeout=300)
                        logger.debug(f"子代理完成(非流式)")
                    except asyncio.TimeoutError:
                        logger.warning(f"子代理超时(非流式): session={session_key}")
                        self.openclaw.session_waiters.pop(session_key, None)
                        return {"success": False, "error": "子代理执行超时"}
                    finally:
                        self.openclaw.session_waiters.pop(session_key, None)

                    if sub_result.get("state") == "error":
                        return {"success": False, "error": sub_result.get("errorMessage", "子代理执行失败")}

                    sub_message = sub_result.get("message")
                    if sub_message and sub_message.get("content"):
                        sub_text = self._extract_text_from_message(sub_message)
                    else:
                        sub_text = await self._fetch_latest_reply(session_key)
                    text = text + "\n\n---\n" + sub_text

                logger.info(f"chat 完成, runId={run_id}, 回复长度={len(text)}")
                return {
                    "success": True,
                    "result": {"content": text, "runId": run_id},
                }

            elif task_type == "agent":
                if streaming:
                    return await self._handle_streaming_agent(task_id, payload)
                # 代理任务
                result = await self.openclaw.send_request("agent", {
                    "message": payload.get("message", ""),
                    "sessionKey": payload.get("session_key"),
                    "model": payload.get("model"),
                })
                return {
                    "success": result.get("ok", False),
                    "result": result.get("payload"),
                    "error": result.get("error"),
                }

            elif task_type == "tools_invoke":
                # 工具调用
                result = await self.openclaw.send_request("tools.invoke", {
                    "tool": payload.get("tool"),
                    "args": payload.get("args", {}),
                })
                return {
                    "success": result.get("ok", False),
                    "result": result.get("payload"),
                    "error": result.get("error"),
                }

            elif task_type == "sessions_list":
                # 列出会话
                result = await self.openclaw.send_request("sessions.list", {})
                return {
                    "success": result.get("ok", False),
                    "result": result.get("payload"),
                    "error": result.get("error"),
                }

            elif task_type == "health":
                # 健康检查
                result = await self.openclaw.send_request("health", {})
                return {
                    "success": result.get("ok", False),
                    "result": result.get("payload"),
                    "error": result.get("error"),
                }

            elif task_type == "browser":
                # 浏览器控制
                action = payload.get("action", "snapshot")
                result = await self.openclaw.send_request(f"browser.{action}", payload)
                return {
                    "success": result.get("ok", False),
                    "result": result.get("payload"),
                    "error": result.get("error"),
                }

            else:
                return {
                    "success": False,
                    "error": f"未知任务类型: {task_type}",
                }

        except asyncio.TimeoutError:
            return {"success": False, "error": "任务超时"}
        except Exception as e:
            logger.error(f"任务执行错误: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _extract_text_from_message(message: dict) -> str:
        """从 message 中提取文本"""
        content_parts = message.get("content", []) if message else []
        text = ""
        for part in content_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text += part.get("text", "")
            elif isinstance(part, str):
                text += part
        return text

    async def _fetch_latest_reply(self, session_key: str, retries: int = 3) -> str:
        """通过 chat.history 获取最新的 assistant 回复（带重试）"""
        for attempt in range(retries):
            try:
                # 等待 transcript 写入完成
                await asyncio.sleep(0.5 * (attempt + 1))
                result = await self.openclaw.send_request("chat.history", {
                    "sessionKey": session_key,
                    "limit": 10,
                }, timeout=10)
                if not result.get("ok"):
                    logger.warning(f"chat.history 失败: {result.get('error')}")
                    continue
                messages = result.get("payload", {}).get("messages", [])
                logger.debug(f"chat.history: {len(messages)} 条消息 (attempt={attempt+1})")
                # 从后往前找最新的 assistant 消息
                for msg in reversed(messages):
                    if msg.get("role") == "assistant":
                        text = self._extract_text_from_message(msg)
                        if text:
                            return text
            except Exception as e:
                logger.error(f"获取 chat.history 失败: {e}")
        return ""

    @staticmethod
    def _is_delegation_message(text: str) -> bool:
        """判断是否为子代理委派消息"""
        delegation_keywords = [
            "子代理", "subagent", "sub-agent", "子会话",
            "启动专门的", "专门的代理", "专门代理",
            "委派", "delegat",
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in delegation_keywords)

    # ---- HTTP Agent 后端处理 ----

    async def _handle_http_agent_task(
        self, task_id: str, task_type: str, payload: dict, streaming: bool
    ) -> dict:
        """通过 HTTP Agent 处理任务"""
        if task_type not in ("chat", "agent"):
            return {
                "success": False,
                "error": f"HTTP Agent 不支持任务类型: {task_type}",
            }

        try:
            if streaming:
                return await self._handle_http_agent_streaming(task_id, payload)
            else:
                return await self.http_agent.send_sync_request(payload)
        except asyncio.TimeoutError:
            return {"success": False, "error": "HTTP Agent 请求超时"}
        except Exception as e:
            logger.error(f"HTTP Agent 任务错误: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_http_agent_streaming(self, task_id: str, payload: dict) -> dict:
        """通过 HTTP Agent 处理流式任务"""
        chunks = []

        async def on_chunk(delta: str):
            chunks.append(delta)
            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_chunk",
                    "task_id": task_id,
                    "chunk": delta,
                }))

        try:
            result = await self.http_agent.send_streaming_request(payload, on_chunk)

            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_end",
                    "task_id": task_id,
                }))

            return {
                "success": result.get("success", False),
                "result": {"content": "".join(chunks)},
                "error": result.get("error"),
                "streaming": True,
            }
        except Exception as e:
            logger.error(f"HTTP Agent 流式错误: {e}")
            if self.server_ws:
                try:
                    await self.server_ws.send(json.dumps({
                        "type": "stream_end",
                        "task_id": task_id,
                    }))
                except Exception:
                    pass
            return {"success": False, "error": str(e), "streaming": True}

    # ---- OpenAI 后端处理 ----

    async def _handle_openai_task(
        self, task_id: str, task_type: str, payload: dict, streaming: bool
    ) -> dict:
        """通过 OpenAI 兼容 API 处理任务"""
        if task_type not in ("chat", "agent"):
            return {"success": False, "error": f"OpenAI API 不支持任务类型: {task_type}"}

        try:
            if streaming:
                return await self._handle_openai_streaming(task_id, payload)
            else:
                return await self.openai_conn.send_sync_request(payload)
        except asyncio.TimeoutError:
            return {"success": False, "error": "OpenAI API 请求超时"}
        except Exception as e:
            logger.error(f"OpenAI API 任务错误: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_openai_streaming(self, task_id: str, payload: dict) -> dict:
        """通过 OpenAI 兼容 API 处理流式任务"""
        chunks = []

        async def on_chunk(delta: str):
            chunks.append(delta)
            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_chunk",
                    "task_id": task_id,
                    "chunk": delta,
                }))

        try:
            result = await self.openai_conn.send_streaming_request(payload, on_chunk)

            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_end",
                    "task_id": task_id,
                }))

            return {
                "success": result.get("success", False),
                "result": {"content": "".join(chunks)},
                "error": result.get("error"),
                "streaming": True,
            }
        except Exception as e:
            logger.error(f"OpenAI API 流式错误: {e}")
            if self.server_ws:
                try:
                    await self.server_ws.send(json.dumps({
                        "type": "stream_end",
                        "task_id": task_id,
                    }))
                except Exception:
                    pass
            return {"success": False, "error": str(e), "streaming": True}

    # ---- OpenClaw 流式处理 ----

    async def _handle_streaming_chat(self, task_id: str, payload: dict) -> dict:
        """处理流式聊天任务 - 通过 agent 事件的 delta 实现真正的流式输出"""
        chunks = []

        async def on_delta(delta: str):
            chunks.append(delta)
            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_chunk",
                    "task_id": task_id,
                    "chunk": delta,
                }))

        try:
            # 发送 chat.send 请求
            idempotency_key = str(uuid.uuid4())
            session_key = payload.get("session_key", "main")
            result = await self.openclaw.send_request("chat.send", {
                "message": payload.get("message", ""),
                "sessionKey": session_key,
                "idempotencyKey": idempotency_key,
            })
            if not result.get("ok"):
                return {"success": False, "error": result.get("error"), "streaming": True}

            run_id = result.get("payload", {}).get("runId", idempotency_key)

            # 注册 runId 级别的流式回调 + session 级别的流式回调
            # 这样不管 agent 使用原 runId 还是新 runId，都能捕获 delta
            self.openclaw.stream_event_callbacks[run_id] = on_delta
            self.openclaw.session_stream_callbacks[session_key] = on_delta

            # 等待 chat final 事件
            chat_result = await self.openclaw.wait_for_chat_result(run_id, timeout=120)

            # 清理 runId 级别的回调
            self.openclaw.stream_event_callbacks.pop(run_id, None)

            if chat_result.get("state") == "error":
                self.openclaw.session_stream_callbacks.pop(session_key, None)
                if self.server_ws:
                    await self.server_ws.send(json.dumps({"type": "stream_end", "task_id": task_id}))
                return {"success": False, "error": chat_result.get("errorMessage", "模型调用失败"), "streaming": True}

            # 检查 final 是否有实际内容
            message = chat_result.get("message")
            main_text = self._extract_text_from_message(message) if message else "".join(chunks)
            has_content = bool(main_text.strip()) or bool("".join(chunks).strip())

            # 情况1: final 无内容（空确认），agent 可能在另一个 runId 下运行
            # 情况2: 内容是子代理委派消息
            # 两种情况都需要继续等待 session 级别的 chat final
            need_wait = not has_content or self._is_delegation_message(main_text)

            if need_wait:
                reason = "空确认" if not has_content else "子代理委派"
                logger.debug(f"检测到{reason}，等待后续结果")

                if has_content and self.server_ws:
                    await self.server_ws.send(json.dumps({
                        "type": "stream_chunk",
                        "task_id": task_id,
                        "chunk": "\n\n---\n*子代理处理中...*\n\n",
                    }))

                # session 级别的流式回调已注册，继续使用
                # 注册 session waiter 等待后续 chat final
                sub_future = asyncio.get_event_loop().create_future()
                self.openclaw.session_waiters[session_key] = sub_future

                try:
                    sub_result = await asyncio.wait_for(sub_future, timeout=300)
                    logger.debug(f"后续结果到达(流式): state={sub_result.get('state')}")
                except asyncio.TimeoutError:
                    logger.warning(f"等待后续结果超时(流式): session={session_key}")
                    sub_result = {"state": "error", "errorMessage": "等待回复超时"}
                finally:
                    self.openclaw.session_stream_callbacks.pop(session_key, None)
                    self.openclaw.session_waiters.pop(session_key, None)

                # 发送流式结束信号
                if self.server_ws:
                    await self.server_ws.send(json.dumps({"type": "stream_end", "task_id": task_id}))

                if sub_result.get("state") == "error":
                    return {"success": False, "error": sub_result.get("errorMessage", "执行失败"), "streaming": True}

                all_text = "".join(chunks)
                return {
                    "success": True,
                    "result": {"content": all_text, "runId": run_id},
                    "streaming": True,
                }

            # 正常结果，清理 session 回调并返回
            self.openclaw.session_stream_callbacks.pop(session_key, None)

            if self.server_ws:
                await self.server_ws.send(json.dumps({"type": "stream_end", "task_id": task_id}))

            return {
                "success": True,
                "result": {"content": "".join(chunks), "runId": run_id},
                "streaming": True,
            }
        except Exception as e:
            logger.error(f"流式聊天错误: {e}")
            return {"success": False, "error": str(e), "streaming": True}

    async def _handle_streaming_agent(self, task_id: str, payload: dict) -> dict:
        """处理流式代理任务"""
        chunks = []

        async def on_chunk(chunk: str):
            chunks.append(chunk)
            # 发送流式数据块到服务端
            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_chunk",
                    "task_id": task_id,
                    "chunk": chunk,
                }))

        try:
            result = await self.openclaw.send_streaming_request(
                "agent",
                {
                    "message": payload.get("message", ""),
                    "sessionKey": payload.get("session_key"),
                    "model": payload.get("model"),
                },
                on_chunk,
                timeout=300
            )

            # 发送流式结束信号
            if self.server_ws:
                await self.server_ws.send(json.dumps({
                    "type": "stream_end",
                    "task_id": task_id,
                }))

            return {
                "success": result.get("ok", False),
                "result": {"content": "".join(chunks)},
                "error": result.get("error"),
                "streaming": True,
            }
        except Exception as e:
            logger.error(f"流式代理错误: {e}")
            return {"success": False, "error": str(e), "streaming": True}

    async def _execute_task(self, data: dict):
        """在后台执行单个任务（不阻塞接收循环）"""
        task_id = data.get("task_id")
        try:
            # 发送进度
            await self.server_ws.send(json.dumps({
                "type": "task_progress",
                "task_id": task_id,
                "progress": "started",
            }))

            # 执行任务
            result = await self.handle_task(data)

            # 发送结果
            result_msg = {
                "type": "task_result",
                "task_id": task_id,
                **result,
            }
            logger.info(f"[结果] task={task_id}, success={result.get('success')}")
            await self.server_ws.send(json.dumps(result_msg))
        except Exception as e:
            logger.error(f"任务 {task_id} 执行异常: {e}")
            try:
                await self.server_ws.send(json.dumps({
                    "type": "task_result",
                    "task_id": task_id,
                    "success": False,
                    "error": str(e),
                }))
            except Exception:
                pass

    async def server_receive_loop(self):
        """服务端消息接收循环"""
        try:
            async for message in self.server_ws:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "task":
                    logger.info(f"[收到任务] task={data.get('task_id')}, type={data.get('task_type')}, stream={data.get('streaming')}")
                    # 并发执行任务，不阻塞接收循环
                    asyncio.create_task(self._execute_task(data))

                elif msg_type == "heartbeat_ack":
                    logger.debug("心跳确认")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("服务端连接断开")
        except Exception as e:
            logger.error(f"服务端接收错误: {e}")

    async def heartbeat_loop(self):
        """心跳循环"""
        while self.running:
            try:
                if self.server_ws:
                    await self.server_ws.send(json.dumps({"type": "heartbeat"}))
                await asyncio.sleep(self.config.heartbeat_interval)
            except Exception as e:
                logger.error(f"心跳发送失败: {e}")
                break

    async def run(self):
        """运行桥接客户端"""
        self.running = True

        while self.running:
            try:
                # 连接服务端
                if not await self.connect_server():
                    logger.warning(f"{self.config.reconnect_interval}秒后重连服务端...")
                    await asyncio.sleep(self.config.reconnect_interval)
                    continue

                if self.config.backend_type == "both":
                    # 多后端模式: 连接所有配置的后端
                    openclaw_ok = await self.connect_openclaw()
                    http_ok = await self.connect_http_agent() if self.config.http_agent_url else False
                    openai_ok = await self.connect_openai() if self.config.openai_api_key else False
                    if not openclaw_ok and not http_ok and not openai_ok:
                        logger.warning(f"所有后端都无法连接，{self.config.reconnect_interval}秒后重试...")
                        await asyncio.sleep(self.config.reconnect_interval)
                        continue

                    logger.info("多后端模式启动")
                    tasks = [
                        asyncio.create_task(self.server_receive_loop()),
                        asyncio.create_task(self.heartbeat_loop()),
                    ]
                    if openclaw_ok:
                        tasks.append(asyncio.create_task(self.openclaw.receive_loop()))

                elif self.config.backend_type == "openai":
                    # OpenAI API 模式
                    if not await self.connect_openai():
                        logger.warning(f"{self.config.reconnect_interval}秒后重试...")
                        await asyncio.sleep(self.config.reconnect_interval)
                        continue

                    logger.info("OpenAI API 模式启动")
                    tasks = [
                        asyncio.create_task(self.server_receive_loop()),
                        asyncio.create_task(self.heartbeat_loop()),
                    ]

                elif self.config.backend_type == "http":
                    # HTTP Agent 模式
                    if not await self.connect_http_agent():
                        logger.warning(f"{self.config.reconnect_interval}秒后重试...")
                        await asyncio.sleep(self.config.reconnect_interval)
                        continue

                    logger.info("HTTP Agent 模式启动")
                    tasks = [
                        asyncio.create_task(self.server_receive_loop()),
                        asyncio.create_task(self.heartbeat_loop()),
                    ]
                else:
                    # OpenClaw 模式: 原有逻辑
                    if not await self.connect_openclaw():
                        logger.warning(f"{self.config.reconnect_interval}秒后重连 OpenClaw...")
                        await asyncio.sleep(self.config.reconnect_interval)
                        continue

                    tasks = [
                        asyncio.create_task(self.server_receive_loop()),
                        asyncio.create_task(self.openclaw.receive_loop()),
                        asyncio.create_task(self.heartbeat_loop()),
                    ]

                # 等待任何一个任务结束
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

                # 取消其他任务
                for task in pending:
                    task.cancel()

                # 清理连接
                if self.server_ws:
                    await self.server_ws.close()
                if self.openclaw:
                    await self.openclaw.close()
                if self.http_agent:
                    await self.http_agent.close()
                if self.openai_conn:
                    await self.openai_conn.close()

            except Exception as e:
                logger.error(f"运行错误: {e}")

            if self.running:
                logger.info(f"{self.config.reconnect_interval}秒后重连...")
                await asyncio.sleep(self.config.reconnect_interval)

    def stop(self):
        """停止运行"""
        self.running = False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Agent Bridge Client")
    parser.add_argument("--config", "-c", type=str, help="配置文件路径 (YAML)")
    parser.add_argument("--config-json", type=str, help="JSON 配置字符串 (由 Launcher 传入)")
    parser.add_argument("--server", type=str, default="ws://localhost:8765",
                        help="服务端 WebSocket 地址")
    parser.add_argument("--openclaw", type=str, default="ws://127.0.0.1:18789",
                        help="本地 OpenClaw Gateway 地址")
    parser.add_argument("--token", type=str, default="",
                        help="OpenClaw Gateway Token")
    parser.add_argument("--client-id", type=str, default="",
                        help="客户端 ID (默认自动生成)")
    parser.add_argument("--server-token", type=str, default="",
                        help="服务端认证 Token (由服务端生成)")
    parser.add_argument("--bind-key", type=str, default="",
                        help="用户绑定 Key (用户的 API Key，用于将客户端绑定到用户)")
    parser.add_argument("--backend-type", type=str, default="openclaw",
                        choices=["openclaw", "http", "openai", "both"],
                        help="后端类型: openclaw (默认), http, openai, 或 both")
    parser.add_argument("--default-backend", type=str, default="openclaw",
                        choices=["openclaw", "http", "openai"],
                        help="多后端模式下默认路由 (默认 openclaw)")
    parser.add_argument("--http-agent-url", type=str,
                        default="http://127.0.0.1:5000/v2/chat",
                        help="HTTP Agent URL (backend-type=http/both 时使用)")
    parser.add_argument("--http-agent-key", type=str, default="",
                        help="HTTP Agent 认证 Key (Bearer Token)")
    parser.add_argument("--openai-api-url", type=str,
                        default="https://api.openai.com/v1/chat/completions",
                        help="OpenAI 兼容 API URL")
    parser.add_argument("--openai-api-key", type=str, default="",
                        help="OpenAI API Key")
    parser.add_argument("--openai-model", type=str, default="gpt-4o",
                        help="OpenAI 模型名称")
    args = parser.parse_args()

    if args.config_json:
        # Launcher 通过 JSON 字符串传入配置
        cfg_data = json.loads(args.config_json)
        config = BridgeConfig(
            server_url=cfg_data.get("server_url", "ws://localhost:8765"),
            bind_key=cfg_data.get("bind_key", ""),
            client_id=cfg_data.get("client_id", ""),
            backend_type="http",  # Launcher 始终用 HTTP 模式连接本地 Agent Server
            http_agent_url=cfg_data.get("http_agent_url", "http://127.0.0.1:8000/api/v2/chat"),
            http_agent_timeout=cfg_data.get("http_agent_timeout", 300.0),
            reconnect_interval=cfg_data.get("reconnect_interval", 5),
            heartbeat_interval=cfg_data.get("heartbeat_interval", 30),
        )
    elif args.config:
        config = BridgeConfig.from_file(args.config)
    else:
        config = BridgeConfig(
            server_url=args.server,
            openclaw_url=args.openclaw,
            openclaw_token=args.token,
            client_id=args.client_id,
            server_token=args.server_token,
            bind_key=args.bind_key,
            backend_type=args.backend_type,
            default_backend=args.default_backend,
            http_agent_url=args.http_agent_url,
            http_agent_key=args.http_agent_key,
            openai_api_url=args.openai_api_url,
            openai_api_key=args.openai_api_key,
            openai_model=args.openai_model,
        )

    logger.info(f"启动桥接客户端: {config.client_id}")
    logger.info(f"服务端: {config.server_url}")
    if config.backend_type == "both":
        logger.info(f"后端: 多后端模式 (默认: {config.default_backend})")
        logger.info(f"  OpenClaw: {config.openclaw_url}")
        if config.http_agent_url:
            logger.info(f"  HTTP Agent: {config.http_agent_url}")
        if config.openai_api_key:
            logger.info(f"  OpenAI API: {config.openai_api_url} (model={config.openai_model})")
    elif config.backend_type == "openai":
        logger.info(f"后端: OpenAI API ({config.openai_api_url}, model={config.openai_model})")
    elif config.backend_type == "http":
        logger.info(f"后端: HTTP Agent ({config.http_agent_url})")
    else:
        logger.info(f"后端: OpenClaw ({config.openclaw_url})")

    client = BridgeClient(config)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        logger.info("收到退出信号")
        client.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"[Bridge] Fatal error in main(): {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
