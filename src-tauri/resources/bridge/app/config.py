"""
配置管理模块
使用 pydantic-settings 从环境变量加载配置
"""
import json
import time
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（config.py 位于 app/ 下，上一级即为项目根）
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=("data/.env", ".env"),  # 优先从 data/.env 读取，兼容旧位置
        env_file_encoding="utf-8",
        env_prefix="WECOM_",
        case_sensitive=False,
        extra="ignore",
    )

    # Claude API 配置
    claude_auth_mode: str = "oauth"  # 认证模式: "oauth"（默认，Claude Code 登录）| "key"（API Key + Base URL）
    claude_api_base: str = ""  # API 地址（oauth 模式留空；key 模式必填）
    claude_api_key: str = ""  # API 密钥（oauth 模式留空；key 模式必填）
    claude_model: str = "claude-opus-4-6"  # 默认模型，可通过 .env 覆盖
    claude_cli_path: str = ""  # Claude CLI 路径（留空=自动检测，oauth 优先 npm 版本）
    claude_small_fast_model: str = ""  # CLI ANTHROPIC_SMALL_FAST_MODEL（留空=默认Haiku；填写=覆盖pre-flight等轻量API调用的模型）

    # 网络代理配置（可选，留空=继承系统环境变量）
    claude_http_proxy: str = ""  # HTTP 代理
    claude_https_proxy: str = ""  # HTTPS 代理
    claude_no_proxy: str = ""  # 不走代理的地址

    # 会话配置
    session_ttl: int = 3600  # 会话超时时间（秒）
    workspace_dir: str = "./data/workspace"  # 工作目录（默认在 data/ 下）

    # 技能配置（由 Claude Agent SDK 自动管理）
    skills_dir: str = "./skills"  # 技能目录路径（仅用于兼容）

    # COS 配置（使用 user-token 鉴权）
    cos_api_base: str = "http://172.21.193.224:31003/plugin-b2dj-digit-cosfile-mcp"  # COS API 地址

    # 配置文件路径
    soul_file: str = "./app/prompts/soul.md"  # 身份人格文件
    mcp_config_file: str = ""  # MCP 配置文件（留空=自动检测 data/.mcp.json 或 .mcp.json）
    allowed_tools_file: str = "./allowed_tools.txt"  # 额外工具列表

    @property
    def resolved_mcp_config_file(self) -> str:
        """解析 MCP 配置文件路径（优先 data/.mcp.json）"""
        if self.mcp_config_file:
            return self.mcp_config_file
        data_mcp = _PROJECT_ROOT / "data" / ".mcp.json"
        if data_mcp.exists():
            return str(data_mcp)
        return "./.mcp.json"

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
    sendmsg_api_url: str = ""  # sendMsg MCP 服务地址
    sendmsg_auth_key: str = ""  # 授权 key
    sendmsg_dep_user_id: str = ""  # 数字员工 ID

    # 异步超时配置
    async_timeout_seconds: float = 0  # 0=禁用异步，>0=超时后切异步推送

    # 全异步推送模式配置（v2.1）
    immediate_return_mode: bool = True  # True=启用全异步模式（HTTP立即返回，全部走推送）
    progress_push_intervals: str = "15"  # 进度推送冷却间隔（秒）

    # 用户白名单
    user_whitelist: str = ""  # 用户白名单，逗号分隔 user_name（如 yanbinmo(莫彦斌)），空=不限制

    # 数字分身模式
    avatar_mode: str = "auto"  # 全局默认模式: "auto"（托管/全自动）| "semi"（协作/半自动）
    admin_whitelist: str = ""  # 管理员白名单，逗号分隔（企微填 user_name，飞书填 user_id），空=不允许任何人操作

    # Agent 会话隔离
    agent_root: str = ""  # Agent CWD（空=默认 ~/.mobot-bridge-agent/）

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
    def admin_whitelist_set(self) -> set:
        """解析管理员白名单为 set"""
        if not self.admin_whitelist:
            return set()
        return {uid.strip() for uid in self.admin_whitelist.split(",") if uid.strip()}

    @property
    def data_dir(self) -> Path:
        """运行时数据目录（data/），用于存放 .env、workspace、logs 等"""
        d = _PROJECT_ROOT / "data"
        d.mkdir(exist_ok=True)
        return d

    @property
    def resolved_soul_file(self) -> Path:
        """获取 soul 文件绝对路径（相对路径基于项目根目录解析）"""
        p = Path(self.soul_file)
        if p.is_absolute():
            return p
        return (_PROJECT_ROOT / p).resolve()

    @property
    def workspace_path(self) -> Path:
        """获取工作目录绝对路径（相对路径基于项目根目录解析）"""
        p = Path(self.workspace_dir)
        if p.is_absolute():
            return p
        return (_PROJECT_ROOT / p).resolve()

    @property
    def skills_path(self) -> Path:
        """获取技能目录绝对路径（相对路径基于项目根目录解析）"""
        p = Path(self.skills_dir)
        if p.is_absolute():
            return p
        return (_PROJECT_ROOT / p).resolve()

    def resolve_cli_path(self) -> str:
        """解析 Claude CLI 路径（留空=SDK bundled CLI）"""
        if self.claude_cli_path:
            return self.claude_cli_path
        return ""

    def check_oauth_status(self) -> tuple:
        """
        检查 OAuth 凭证是否存在且未过期

        Returns:
            (is_valid, error_message, expires_at_ms)
        """
        cred_file = Path.home() / ".claude" / ".credentials.json"
        if not cred_file.exists():
            return False, "OAuth credentials not found. Please run 'claude login' to authenticate.", 0

        try:
            data = json.loads(cred_file.read_text(encoding="utf-8"))
            oauth = data.get("claudeAiOauth", {})
            expires_at = oauth.get("expiresAt", 0)
            # expiresAt 是 epoch 毫秒
            if expires_at and expires_at < time.time() * 1000:
                return False, "OAuth credentials expired. Please run 'claude login' to refresh.", expires_at
            return True, "", expires_at
        except Exception as e:
            return False, f"Failed to validate OAuth credentials: {e}", 0

    async def refresh_oauth_token(self) -> tuple[bool, str]:
        """使用 refresh_token 主动刷新 OAuth 凭证"""
        import httpx
        cred_file = Path.home() / ".claude" / ".credentials.json"
        if not cred_file.exists():
            return False, "Credentials file not found"
        try:
            data = json.loads(cred_file.read_text(encoding="utf-8"))
            oauth = data.get("claudeAiOauth", {})
            refresh_token = oauth.get("refreshToken", "")
            if not refresh_token:
                return False, "No refresh token available"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://platform.claude.com/v1/oauth/token",
                    json={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
                        "scope": "user:profile user:inference user:sessions:claude_code user:mcp_servers",
                    },
                    headers={"Content-Type": "application/json"},
                )
            if resp.status_code != 200:
                return False, f"Token refresh failed: HTTP {resp.status_code}"
            result = resp.json()
            oauth["accessToken"] = result["access_token"]
            if result.get("refresh_token"):
                oauth["refreshToken"] = result["refresh_token"]
            oauth["expiresAt"] = int(time.time() * 1000) + result.get("expires_in", 3600) * 1000
            data["claudeAiOauth"] = oauth
            cred_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, ""
        except Exception as e:
            return False, f"Token refresh error: {e}"


# 全局配置实例
settings = Settings()


class FeishuSettings(BaseSettings):
    """飞书渠道配置"""

    model_config = SettingsConfigDict(
        env_file=("data/.env", ".env"),  # 优先从 data/.env 读取，兼容旧位置
        env_file_encoding="utf-8",
        env_prefix="FEISHU_",
        case_sensitive=False,
        extra="ignore",
    )

    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""  # Webhook URL 验证 token
    encrypt_key: str = ""  # 消息加密 key（可选）
    user_whitelist: str = ""  # 飞书用户白名单，逗号分隔 open_id，空=不限制

    @property
    def enabled(self) -> bool:
        """有配置就自动启用（app_id 和 app_secret 都配置了）"""
        return bool(self.app_id and self.app_secret)

    @property
    def user_whitelist_set(self) -> set:
        """解析飞书白名单字符串为 set"""
        if not self.user_whitelist:
            return set()
        return {uid.strip() for uid in self.user_whitelist.split(",") if uid.strip()}


feishu_settings = FeishuSettings()

# 运行时变量：由 main.py lifespan() 初始化
# Agent SDK 的 cwd，用于隔离 agent 会话与开发者 Claude Code 会话
resolved_agent_root: str = ""
