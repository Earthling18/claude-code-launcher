"""
配置管理模块
使用 pydantic-settings 从环境变量加载配置
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WECOM_",
        case_sensitive=False,
    )

    # Claude API 配置
    claude_auth_mode: str = "oauth"  # 认证模式: "proxy"（代理网关） 或 "oauth"（Claude Code OAuth）
    claude_api_base: str = ""  # 代理网关地址（proxy 模式），由 Launcher UI 或 .env 设置
    claude_api_key: str = ""  # 代理密钥（proxy 模式），由 Launcher UI 或 .env 设置
    claude_model: str = "claude-sonnet-4-5-20250929"
    claude_cli_path: str = ""  # Claude CLI 路径（可选，留空使用默认）
    http_proxy: str = ""  # HTTP 代理（OAuth 模式访问官方 API 时使用）

    # 会话配置
    session_ttl: int = 3600  # 会话超时时间（秒）
    workspace_dir: str = "./workspace"  # 工作目录

    # 技能配置（由 Claude Agent SDK 自动管理）
    skills_dir: str = "./skills"  # 技能目录路径（仅用于兼容）

    # COS 配置（使用 user-token 鉴权）
    cos_api_base: str = "http://172.21.193.224:31003/plugin-b2dj-digit-cosfile-mcp"  # COS API 地址

    # 配置文件路径
    soul_file: str = "./app/soul.md"  # 身份人格文件
    system_prompt_file: str = "./app/system_prompt.md"  # 系统提示文件
    mcp_config_file: str = "./.mcp.json"  # MCP 配置文件
    allowed_tools_file: str = "./allowed_tools.txt"  # 额外工具列表

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # 消息处理配置
    aggregation_window_seconds: float = 6.0  # 消息聚合时间窗口（秒）[仅聚合模式有效]
    message_processing_mode: str = "queue"  # 处理模式: "queue"（零延迟队列）| "aggregate"（聚合模式）
    queue_timeout_seconds: float = 1800.0  # 队列等待超时（秒）- 30分钟，支持长时间任务

    # 文件输出配置
    file_output_mode: str = "prompt"  # 输出模式: "prompt"（格式约定）| "mcp"（MCP工具）| "all"（全部返回）
    file_cache_timeout_seconds: float = 300.0  # 文件缓存超时（秒）

    # sendMsg 主动推送配置
    sendmsg_api_url: str = "http://172.21.193.224:31003/plugin-b2aa-sendmsg/mcp"  # sendMsg MCP 服务地址
    sendmsg_auth_key: str = "13f64987826f0779ae3568a8d1c3f377"  # 授权 key
    sendmsg_dep_user_id: str = "alin"  # 数字员工 ID

    # 异步超时配置
    async_timeout_seconds: float = 0  # 0=禁用异步，>0=超时后切异步推送

    # 全异步推送模式配置（v2.1）
    immediate_return_mode: bool = True  # True=启用全异步模式（HTTP立即返回，全部走推送）
    progress_push_intervals: str = "15"  # 进度推送冷却间隔（秒）

    # Agent SDK 配置（可由 Launcher UI 通过环境变量覆盖）
    agent_max_turns: int = 3  # 最大对话轮数，对应 env: WECOM_AGENT_MAX_TURNS

    # 用户白名单
    user_whitelist: str = ""  # 用户白名单，逗号分隔，空=不限制

    @property
    def progress_push_intervals_list(self) -> list:
        """解析进度推送间隔字符串为列表"""
        if not self.progress_push_intervals:
            return [15]  # 默认值
        try:
            return [int(x.strip()) for x in self.progress_push_intervals.split(",") if x.strip()]
        except ValueError:
            return [15]

    @property
    def user_whitelist_set(self) -> set:
        """解析白名单字符串为 set，方便快速查找"""
        if not self.user_whitelist:
            return set()
        return {uid.strip() for uid in self.user_whitelist.split(",") if uid.strip()}

    @property
    def workspace_path(self) -> Path:
        """获取工作目录绝对路径"""
        return Path(self.workspace_dir).resolve()

    @property
    def skills_path(self) -> Path:
        """获取技能目录绝对路径"""
        return Path(self.skills_dir).resolve()


# 全局配置实例
settings = Settings()
