# Bridge Client - 企微消息桥接客户端

通过 WebSocket 连接中转服务器，将企微消息转发到本地 mobot HTTP API。

## 架构

```
企业微信 → Bridge Server (远程 WebSocket) → Bridge Client (本地) → mobot API (本地)
```

- Bridge Client 连接远程 Bridge Server，注册为消息接收端
- 收到企微消息后，通过 HTTP POST 转发到本地 mobot v2 API
- mobot 以 immediate_return 模式工作：HTTP 立即返回空响应，实际结果通过 sendMsg 直推企微

## 文件说明

| 文件 | 说明 |
|------|------|
| `bridge_client.py` | 客户端主程序 |
| `config.yaml` | 配置文件 |
| `requirements.txt` | Python 依赖 |

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 修改配置

编辑 `config.yaml`，**将 `http_agent_url` 中的 IP 替换为本机局域网 IP**：

```yaml
client:
  server_url: "ws://<bridge-server-host>/bridge"   # Bridge Server 地址
  bind_key: "sk-xxx"                                # 绑定 Key（从管理员获取）
  backend_type: "http"
  http_agent_url: "http://<本机IP>:8000/api/v2/chat"  # 替换为本机局域网 IP
  http_agent_api_key: "ak-xxx"                          # mobot v2 API Key
  http_agent_timeout: 300
```

> **注意**：`http_agent_url` 中的 IP 需要替换为当前机器的局域网 IP（不是 `127.0.0.1`）。
> 可通过 `ipconfig` 查看本机 IPv4 地址。

### 3. 确保 mobot 服务已启动

```bash
python start.py
```

### 4. 启动 Bridge Client

```bash
cd 直接请求
python bridge_client.py
```

> 不加 `-c` 参数时默认读取同目录下的 `config.yaml`。

### 5. 验证

日志出现以下内容表示连接成功：
```
INFO - 已注册到服务端: <client_id>
INFO - HTTP Agent 会话已创建: http://127.0.0.1:8000/api/v2/chat
INFO - HTTP Agent 模式启动
```

## 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `server_url` | Bridge Server WebSocket 地址 | `ws://localhost:8765` |
| `bind_key` | 用户绑定 Key（sk-xxx 格式） | 空 |
| `client_id` | 客户端 ID，留空自动取主机名 | 空 |
| `backend_type` | 后端类型：`openclaw` / `http` / `both` | `http` |
| `http_agent_url` | mobot v2 API 端点 | `http://127.0.0.1:5000/v2/chat` |
| `http_agent_api_key` | v2 API 认证 Key（Bearer token） | 空 |
| `http_agent_timeout` | HTTP 请求超时（秒） | 300 |
| `reconnect_interval` | 断线重连间隔（秒） | 5 |
| `heartbeat_interval` | 心跳间隔（秒） | 30 |

## 代理与网络注意事项

> **重要**：Bridge Client 通过 WebSocket 直连 Bridge Server，**不能走任何 HTTP 代理**。

常见代理冲突场景：
- 系统开着 **Clash**（端口 7890）、**V2Ray**（10808）等代理工具，系统环境变量中有 `HTTP_PROXY` / `HTTPS_PROXY`
- 终端继承了 Claude Code 的代理设置

如果遇到 WebSocket 握手失败或连接超时，在启动 Bridge 的终端中清除代理变量：

```powershell
# Windows PowerShell
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""
python bridge_clientv3.py
```

```bash
# Linux / macOS
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
python bridge_clientv3.py
```

> **注意**：Agent 主服务（`python start.py`）不受此限制。两个服务建议在不同终端中启动。

## 其他注意事项

- mobot 需要先启动并监听在 8000 端口
- `http_agent_api_key` 用于 v2 API 的 `Authorization: Bearer` 认证，不配置会收到 401
- 断线后客户端会自动重连
