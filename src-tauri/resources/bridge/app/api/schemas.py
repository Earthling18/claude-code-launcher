"""
API 请求/响应模型

适配企业微信 → Dify → Backend 字段格式
"""
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator


# ==================== 请求模型 ====================

class ChatRequest(BaseModel):
    """
    对话请求 - 适配企业微信字段格式

    企微通过 Dify 传入的字段:
    - query: 用户问句
    - query_info: JSON 字符串，包含 text/file/image 列表
    - session_id: 会话 ID（4小时无消息刷新）
    - user_id: 用户 ID
    - user_name: 用户名称
    - history_list: 历史对话 JSON 字符串
    - group_chat_name: 群聊名称
    """
    session_id: str = Field(..., description="会话 ID（来自 Dify/企微）")
    user_id: str = Field(..., description="用户 ID")
    query: str = Field(default="", description="用户问句（纯文本）")
    query_info: Optional[Union[str, List, Dict]] = Field(
        default=None,
        description='问句详情: JSON 字符串或数组 [{"type":"text|file|image","content":"..."}]'
    )
    user_name: Optional[str] = Field(default=None, description="用户名称")
    history_list: Optional[Union[str, List]] = Field(
        default=None,
        description="历史对话: JSON 字符串或数组"
    )
    group_chat_name: Optional[str] = Field(default=None, description="群聊名称")
    user_token: Optional[str] = Field(
        default=None,
        description="用户鉴权 Token（用于 COS 文件操作）"
    )
    skill: Optional[str] = Field(
        default=None,
        description="[已废弃] 技能由 SDK 自动触发，此字段不再使用"
    )
    reference_info: Optional[str] = Field(
        default=None,
        description="引用消息：企微引用的文件名或之前说过的话"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="企微对话ID（用于异步超时后主动推送结果）"
    )
    conversation_type: Optional[str] = Field(
        default=None,
        description="企微会话类型：'GROUP' 或 'PRIVATE'（入口处统一转换）"
    )
    channel: str = Field(default="wecom", description="消息渠道: wecom | feishu")

    @field_validator("conversation_type", mode="before")
    @classmethod
    def normalize_conversation_type(cls, v: Optional[str]) -> Optional[str]:
        """统一转换 conversation_type 为英文格式"""
        if v is None:
            return None
        v_upper = v.upper()
        if v_upper == "GROUP" or v == "群聊":
            return "GROUP"
        # 支持 Dify 传入的 "SINGLE" 格式，统一转换为 "PRIVATE"
        if v_upper in ("PRIVATE", "SINGLE") or v == "单聊":
            return "PRIVATE"
        return v_upper  # 其他情况转大写


# ==================== 响应模型 ====================

class MessageItem(BaseModel):
    """
    消息项 - 企微期望的响应格式

    type 取值:
    - txt: 文本消息
    - file: 文件（COS 路径）
    - image: 图片（COS 路径）
    """
    model_config = {"exclude_none": True}  # 排除 None 值，避免企微解析失败

    type: str = Field(..., description="消息类型: txt | file | image")
    content: str = Field(..., description="消息内容或 COS 路径")
    order_no: Optional[str] = Field(default=None, description="消息序号（可选）")


class ChatResponse(BaseModel):
    """对话响应 - 适配企微格式"""
    model_config = {"exclude_none": True}  # 排除 None 值

    message_list: List[MessageItem] = Field(
        default_factory=list,
        description="消息列表"
    )


class SessionInfo(BaseModel):
    """会话信息"""
    model_config = {"extra": "ignore"}

    session_id: str
    user_id: str
    workspace: str
    claude_session_id: Optional[str] = None
    created_at: float
    last_accessed: float
    ttl_remaining: float


class SessionResponse(BaseModel):
    """会话查询响应"""
    success: bool
    session: Optional[SessionInfo] = None
    message: Optional[str] = None


class SkillInfo(BaseModel):
    """技能信息"""
    name: str = Field(..., description="技能目录名")
    display_name: str = Field(..., description="技能显示名称")
    description: str = Field(..., description="技能描述")
    version: str = Field(..., description="版本号")
    scripts: List[str] = Field(default_factory=list, description="可用脚本列表")
    allowed_tools: List[str] = Field(default_factory=list, description="允许的工具")


class SkillsResponse(BaseModel):
    """技能列表响应"""
    skills: List[SkillInfo]
    count: int


class ChannelHealthInfo(BaseModel):
    """通道健康信息"""
    status: str = "disabled"         # connected, starting, disabled, error, disconnected
    since: Optional[float] = None    # 状态变更时间戳
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "healthy"
    version: str = "0.0.0"
    active_sessions: int = 0
    loaded_skills: int = 0
    pid: int = 0
    channels_ready: bool = True
    channels: Dict[str, ChannelHealthInfo] = {}
    sdk_ready: bool = False
    module_build: Optional[str] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str
    detail: Optional[str] = None
