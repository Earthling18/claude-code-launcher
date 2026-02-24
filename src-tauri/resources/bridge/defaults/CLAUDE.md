# 企业微信数字分身后端服务

## 项目概述

基于 Claude Agent SDK 的后端服务框架，为 Dify 工作流提供 HTTP API。

**核心能力**：多用户并发会话、Claude Agent SDK 长连接会话（非阻塞）、Skill 技能系统、MCP 工具扩展、定时任务调度、多轮对话上下文保持（双任务架构，新消息在 Claude 处理中立即发送）。

## 目录结构

```
├── app/                      # 应用代码
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理
│   ├── system_prompt.md     # 系统提示
│   ├── api/
│   │   ├── routes.py        # API 路由
│   │   └── schemas.py       # 请求/响应模型
│   ├── core/
│   │   ├── agent_service.py     # Claude SDK 封装
│   │   ├── session_manager.py   # 会话管理
│   │   ├── request_router.py    # 请求路由器（零延迟分发）
│   │   ├── request_queue.py     # 文件缓存队列
│   │   ├── output_registry.py   # 输出文件注册表
│   │   ├── query_parser.py      # 解析企微 query_info JSON
│   │   ├── file_processor.py    # 文件下载处理（COS → workspace）
│   │   ├── message_builder.py   # 响应消息构建
│   │   ├── sse_handler.py       # SSE 转换（已废弃）
│   │   ├── user_session.py      # 用户会话管理器（双任务架构）
│   │   ├── progress_pusher.py   # 进度推送器（冷却机制）
│   │   └── cron_service.py      # 定时任务服务
│   ├── services/
│   │   ├── cos_client.py        # COS 文件上传/下载客户端
│   │   └── proactive_messenger.py  # sendMsg 主动推送封装
│   └── mcp_tools/
│       └── file_output_tool.py  # 文件输出工具（prompt 解析 + MCP）
├── .claude/skills/           # 技能目录（SDK 自动加载）
├── docs/                     # 文档
│   ├── REQUEST_FORMAT.md    # 请求格式详细说明
│   └── OUTPUT_FORMAT.md     # 输出格式详细说明
├── tests/                    # 测试
├── workspace/{user_id}/      # 用户工作目录
├── start.py                  # 启动入口
├── .env                      # 环境变量
├── .mcp.json                 # MCP 工具配置
└── cron_jobs.json            # 定时任务配置
```

## 配置文件

### .env
```bash
# Claude API
WECOM_CLAUDE_AUTH_MODE=proxy           # 认证模式: proxy（代理网关）| oauth（Claude Code OAuth）
WECOM_CLAUDE_API_BASE=...              # Claude API 地址
WECOM_CLAUDE_API_KEY=...               # API 密钥
WECOM_CLAUDE_MODEL=...                 # 模型名称
WECOM_CLAUDE_CLI_PATH=...              # Claude CLI 路径（可选，留空使用默认）

# 会话
WECOM_SESSION_TTL=3600                 # 会话超时（秒）

# 消息处理
WECOM_MESSAGE_PROCESSING_MODE=queue    # queue | aggregate（immediate_return_mode=true 时忽略）
WECOM_AGGREGATION_WINDOW_SECONDS=6.0   # 聚合窗口（仅 aggregate）
WECOM_QUEUE_TIMEOUT_SECONDS=1800.0     # 队列等待超时（秒）

# 文件输出
WECOM_FILE_OUTPUT_MODE=prompt          # prompt（默认，文本标记）| mcp（MCP工具）| all（全部返回）
WECOM_FILE_CACHE_TIMEOUT_SECONDS=300.0

# 全异步推送
WECOM_IMMEDIATE_RETURN_MODE=true       # true=HTTP立即返回，全部走推送
WECOM_PROGRESS_PUSH_INTERVALS=15       # 进度推送冷却间隔（秒）
WECOM_ASYNC_TIMEOUT_SECONDS=0          # 0=禁用，>0=超时后切异步推送

# sendMsg 主动推送（全异步模式必需）
WECOM_SENDMSG_API_URL=...
WECOM_SENDMSG_AUTH_KEY=...
WECOM_SENDMSG_DEP_USER_ID=...

# COS 文件服务
WECOM_COS_API_BASE=...                 # COS API 地址

# 访问控制
WECOM_USER_WHITELIST=...               # 用户白名单（逗号分隔，空=不限制）
```

### .mcp.json
用户自行创建，定义 MCP servers。格式见 Claude SDK 文档。

### app/system_prompt.md
系统提示配置文件。如不存在则使用默认值。

## API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/v1/chat` | 对话（非阻塞，全异步推送） |
| POST | `/api/v1/chat/stream` | 对话（SSE，非 SDK 官方规范，已废弃） |
| GET | `/api/v1/session/{id}` | 查询会话 |
| DELETE | `/api/v1/session/{id}` | 销毁会话 |
| GET | `/api/v1/skills` | 技能列表 |
| POST | `/api/v1/config/reload` | 重载配置 |
| POST | `/api/v1/cron/reload` | 重载定时任务 |
| GET | `/health` | 健康检查 |

### 请求格式

基础字段：`session_id`、`user_id`、`query`。还支持 `query_info`（JSON 数组）、`conversation_id`、`conversation_type`、`group_chat_name`、`user_name`、`user_token` 等。详见 [docs/REQUEST_FORMAT.md](docs/REQUEST_FORMAT.md)。

> **注意**：`/api/v1/chat/stream`（SSE）已废弃，生产环境使用 `/api/v1/chat` + sendMsg 推送。

## Skill 开发规范

技能由 Claude Agent SDK 自动加载和触发（渐进式披露）：
1. **启动时**：SDK 扫描 `.claude/skills/`，加载 `name` 和 `description`
2. **匹配时**：Claude 根据用户问题自动判断使用哪个技能
3. **执行时**：按需加载完整内容和参考文档

### 目录结构
```
.claude/skills/my-skill/
├── SKILL.md              # 必需：技能定义
├── scripts/              # 可选：可执行脚本
└── references/           # 可选：参考文档
```

### SKILL.md 格式
```markdown
---
name: 显示名称
description: 何时触发此技能的描述（Claude 依此判断）
version: 1.0.0
---
技能指令内容...
```

**注意**：`description` 字段至关重要。技能自动触发，无需在 API 请求中指定。

## 核心模块

| 模块 | 职责 |
|------|------|
| **SessionManager** | 会话生命周期管理，以 user_id 为主键，TTL 自动过期 |
| **AgentService** | 封装 Claude Agent SDK，支持 query() 一次性调用和 ClaudeSDKClient 长连接会话 |
| **RequestRouter** | 零延迟消息分发，per-user 队列，串行处理 |
| **UserSessionManager** | 用户会话管理，内聚 SDK 长连接，双任务架构（sender+receiver），遵循 Claude Agent SDK 官方 ClaudeSDKClient 规范，query() 非阻塞发送，receive_messages() 持续接收 |
| **QueryParser** | 解析企微 query_info JSON 格式，提取文本和文件 |
| **FileProcessor** | COS 文件下载到 workspace |
| **MessageBuilder** | 构建响应消息（文本 + 文件列表） |
| **OutputRegistry** | 追踪 Agent 指定返回的文件，过滤中间过程 |
| **ProgressPusher** | 冷却机制进度推送：首条立即发送 → 冷却期累积 → 到期发送最新，用户新消息重置冷却 |
| **CronService** | APScheduler 定时任务，支持 message/command/skill 三种模式 |
| **CosClient** | COS 文件上传/下载封装（user-token 鉴权） |
| **ProactiveMessenger** | sendMsg 主动推送封装 |

## 消息处理模式

两个配置项共同决定行为：`WECOM_IMMEDIATE_RETURN_MODE` 和 `WECOM_MESSAGE_PROCESSING_MODE`。

| 模式 | 特点 | 适用场景 |
|------|------|---------|
| **immediate_return**（推荐） | `immediate_return_mode=true` 时生效。HTTP 立即返回空响应，全部走 sendMsg 推送，ClaudeSDKClient 长连接 | 生产环境 |
| **queue** | `immediate_return_mode=false` 时默认。零延迟分发，使用 query() 一次性调用 | 简单对话（无需长连接） |
| **aggregate** | 6秒窗口合并消息 | 连续多条消息需合并 |

`immediate_return` 模式需配置 `WECOM_IMMEDIATE_RETURN_MODE=true` 和 `WECOM_SENDMSG_API_URL`。

## 定时任务

基于 APScheduler，支持三种模式：

| 模式 | 说明 | 示例 |
|------|------|------|
| **message** | 发送固定文本 | "每天提醒喝水" |
| **command** | 调用 Agent 执行命令 | 自由文本指令 |
| **skill** | 触发指定 Skill（转换为 `/skill-name`） | `timesheet-analysis` |

### cron_jobs.json 格式
```json
{
  "jobs": [{
    "id": "job-id",
    "cron": "0 9 * * 1",
    "command": "执行指令",
    "skill": "skill-name",
    "message": "文本（message/command/skill 三选一）",
    "context_type": "private|group",
    "target_type": "self|group",
    "owner_conversation_id": "wrkSxxxx",
    "owner_name": "用户名",
    "target_conversation_id": "wrkSxxxx",
    "target_name": "目标名",
    "enabled": true,
    "end_date": "ISO日期（可选，到期自动删除）",
    "delete_after_run": false
  }]
}
```

### 创建方式
1. **通过 Skill**：`cron-manager` Skill 支持自然语言创建
2. **直接编辑**：编辑 `cron_jobs.json`

### 发送规则
- 私聊创建 → 只能发给自己
- 群聊创建 → 当前群 或 发给自己

## 文件输出模式

| 模式 | 说明 |
|------|------|
| **prompt**（默认） | Agent 在回复中用 `<!--RETURN_FILES:["file.txt"]-->` 标记返回哪些文件 |
| **mcp** | Agent 通过 MCP 工具标记返回文件 |
| **all** | 返回所有新增/修改的文件 |

## 数据流（Claude Agent SDK 长连接架构）

```
用户消息 → RequestRouter → UserSession.add_message()
                             ↓
                   ClaudeSDKClient 长连接会话
                             ↓
                     双任务（sender + receiver）
                             ↓
       sender: client.query(消息)    receiver: client.receive_messages()
       非阻塞，立即返回              持续接收响应，不因 ResultMessage 停止
                             ↓
       新消息到达 → 立即发送，不等当前处理完成
                             ↓
       Claude 看到完整对话历史，输出综合响应
                             ↓
       结果通过 sendMsg API 推送给用户
```

基于 Claude Agent SDK 官方 `ClaudeSDKClient` 长连接规范：`query()` 非阻塞发送消息，`receive_messages()` 持续接收响应，实现真正的对话式交互。

## 扩展指南

### 添加 MCP 工具
编辑 `.mcp.json`，重启服务或调用 `/api/v1/config/reload`。

### 自定义系统提示
编辑 `app/system_prompt.md`，重启服务。

### 创建新 Skill
1. 在 `.claude/skills/` 下创建目录，编写 `SKILL.md`
2. 可选添加 `scripts/` 和 `references/`
3. 重启服务，SDK 自动加载

### 添加 API 端点
1. `app/api/schemas.py` 定义模型
2. `app/api/routes.py` 添加路由

## 启动

```bash
python start.py
# 或
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API 文档: http://localhost:8000/docs

## 详细文档

- [请求格式](docs/REQUEST_FORMAT.md)
- [输出格式](docs/OUTPUT_FORMAT.md)

## Compact instructions

当接近上下文限制或执行 compact 操作时：

**必须保留**：文件路径、用户需求、错误信息、任务状态、核心代码片段、输出文件路径。

**可以压缩**：调试输出、重复工具调用结果、大文件内容（保留摘要）、探索性搜索结果。

**大文件策略**：PDF 先提取目录按需读取；数据文件先读前几行了解结构；长文本分段处理。
