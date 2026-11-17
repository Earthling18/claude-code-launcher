> 2026-11-16 更新：已接入本地 SS / AnyTLS 订阅与简化网页入口。先看 [快速使用说明](QUICKSTART.md)，下文保留云节点版本的接口与历史说明。

# Python 连接工具（试用）

Windows 与 macOS 使用同一份脚本，要求 Python 3.11+；云节点模式仅用标准库，订阅节点按需安装 Python 支持库，不使用独立代理 EXE。
支持 TLS HTTP CONNECT 云节点及本地 SS / AnyTLS 订阅。TUN、系统代理和浏览器接管不在本版中。

## 在启动器中使用

1. 解压并保留整个 `python-connection` 文件夹，不能只复制一个 `.py` 文件。
2. 「管理模型 → 代理配置 → 新建代理」填写名称，展开高级选项并启用 Python。
3. Python 环境留空自动检测；脚本选择 `ai-connection.py`。
4. 新版「管理连接与分流」打开本地网页，可新建云节点、编辑方案名称、认证、分流和公司 DNS；已有方案直接显示。导入旧包请先运行 `ai-connection.py menu`，选 `2` 并填写旧包目录（包含 `config.json` 和 `credentials.json`）；旧包不会修改，目标方案已存在时不会覆盖。旧版脚本仍使用终端菜单。
5. 回到启动器点击「检测 / 刷新方案」，选择导入的方案并保存。
6. 项目编辑页的「代理」选择这个方案，然后照常启动 Codex 或 Claude Code。自定义 API 模式也支持。

普通代理模式可随时重新选择；建议新建独立预设，保留原代理用于回退。
回退旧版启动器前，先把使用 Python 方案的项目切回原普通代理；旧版不认识 Python 预设。
退出 CLI 后，本次会话监听自动关闭。可以同时启动多个项目，不需要额外运行固定端口代理。
Codex 会自动使用 `--no-daemon` 独立运行，防止已有共享后台绕过本次代理环境。
脚本先检测当前 CLI 是否支持该选项；不支持时明确报错，需更新 Codex 后使用。
此设置仅作用于通过 Python 方案启动的 Codex，不修改全局配置或关闭其他会话的后台服务。

## 放在哪里

- Windows：例如 `%USERPROFILE%\cc-connection\python-connection`，桌面也可以；不要移动后仍使用旧路径。
- Mac：建议 `~/cc-connection/python-connection`。桌面、文稿、下载等目录可能需要 macOS 文件夹访问授权；检测超时时先处理系统提示。无需开启完全磁盘访问权限，也不要关闭系统保护。
- Mac 第一次从启动器打开终端时，系统可能询问是否允许控制 Terminal；这是启动终端所需的自动化权限。
- 解压目录需要可写，因为方案保存在脚本旁的 `profiles/<方案 ID>/`。
- Windows 任务管理器会显示 `python.exe`；脚本不隐藏进程，不创建系统服务。

## 单独运行

双击 Mac 的 `manage.command` 或 Windows 的 `manage.cmd` 打开管理页。窗口中提示的管理端口只用于本机；认证凭据通过自动打开的页面传递，不打印在终端。页面关闭后常驻代理仍可运行；停止常驻再点「退出管理」即可完全退出。不要将脚本目录放在公开共享文件夹。

Windows PowerShell（从脚本目录运行）：

```powershell
py -3 .\ai-connection.py menu
py -3 .\ai-connection.py web
py -3 .\ai-connection.py --profile default doctor
py -3 .\ai-connection.py --profile default run -- codex
py -3 .\ai-connection.py --profile default run -- claude
```

macOS（用实际 Python 3.11+ 解释器替换 `python3`）：

```sh
python3 ./ai-connection.py menu
python3 ./ai-connection.py web
python3 ./ai-connection.py --profile default doctor
python3 ./ai-connection.py --profile default run -- codex
python3 ./ai-connection.py --profile default run -- claude
```

可从任意目录用脚本完整路径执行；CLI 的工作目录保持为当前项目。

## 两种使用方式

- **按需启动（默认）**：启动器原来的 `run -- codex` / `run -- claude`，每个项目独立随机端口，CLI 退出后清理。管理页无需保持运行。
- **常驻接入**：管理页选方案、点击「启动常驻」。另一个终端执行 `python3 /完整路径/ai-connection.py --profile 方案ID attach -- codex`（Windows 使用 `py -3`）。退出这次 CLI 不停止常驻；停止常驻会断开所有使用它的请求。未启动或方案不一致时明确失败，不回退直连。

高级命令 `--profile 方案ID serve` 在当前终端启动同一套管理服务并自动启用常驻，可再运行 `web` 打开管理页。每份脚本目录只有一个管理进程；再次启动不会创建冲突的代理，切换方案需先停止。固定端口可用 `serve --port 端口`，冲突时失败，不杀占用程序。默认随机端口通过私有的管理接口交给 `attach`，无需手动复制带密码的代理 URL。

界面区分「已停止」「本地待命」「连接保留」「正在传输」。本地待命不建立远端连接；工具不周期探测或测速。应用自身的保活、遥测、请求重试仍可能产生网络流量，因此不能把“没有输入”视为“没有外部连接”。活动流不会因为单向静默被工具强制断开。

本阶段常驻入口用于显式 CLI 接入。Mac 客户端另有下方的专用试用入口。**Codex 客户端原图标接入、Windows 客户端入口、浏览器专用窗口尚未完成**。管理页里的规则只处理进入本工具的流量，不是系统全局代理。

## Mac Codex 客户端入口（试用）

日常只需两步：选择云节点，点击「打开 Codex · 保留记录」。现有账号、项目和聊天记录沿用原客户端的数据目录，不复制或合并数据库，不改写共享的登录、配置或 `.env` 文件。

如果 Codex 已运行（包括之前的独立试用窗口），先通过客户端菜单退出，Mac 可用 ⌘Q；仅关闭窗口通常不够。工具会拦截重复打开并给出提示，不会强制关闭已有客户端。请在处理完正在执行的任务后自行退出，再从管理页打开。代理环境只传给这次新进程，原图标之后单独启动不会自动使用它。

「更多设置与排查」内提供云节点编辑、分流、公司 DNS、诊断、终端常驻，以及客户端启动选项。独立测试窗口保留为可选的排错方式，默认不使用；原试用目录的独立历史不会自动合并到主客户端。

如出现 127.0.0.1 的代理认证框，可在高级设置里复制本次随机本地密码，用户名 `local`。不要把该密码粘贴到网站或账号登录表单。退出通过这里打开的客户端后会清理它自己的代理；其他 CLI 和常驻代理不受影响。仅关闭网页不退出客户端。

普通订阅可导入 HTTPS 地址、Clash YAML / JSON、SS URI / Base64；选择兼容节点后可检测、启动客户端或在启动器引用。本地 SS / AnyTLS 已分别完成真实 Codex 请求；不兼容的协议会标注原因。

本次已验证正常数据目录选择、已有客户端拦截、原文件保持不变以及进程清理；原历史在真实窗口中的显示、模型调用和完整流量覆盖仍需人工验收。Windows 客户端入口未开放，Windows CLI 保持原有功能。

## 分流和凭据

管理页可切换「规则分流」和「全部代理（仅接入的应用）」。旧方案默认规则分流。全部代理保留阻止规则，其余目标直接交给上游，不进行目标域名的本地 DNS 查询；直连、国内规则和公司 DNS 暂停使用，但原配置不会删除。访问公司内网时请使用规则分流。修改后需重新启动对应 CLI 或常驻会话，不中途切换正在传输的请求。

优先级：阻止 → 强制代理 → 显式直连 → 公司域名 → 国内域名/IP 规则 → 默认动作。
公司域名只使用所填公司 DNS，失败不会转向公共 DNS。公共国内规则查询使用加密 DoH；查询提供商仍能看到查询的域名。
导入旧包会保留国内规则数据库；新建通用方案不会带入任何公司的域名、DNS 或凭据。
规则变更在新启动的会话生效，不会中途切换正在流式输出的连接。

旧方案从 `config.json` / `credentials.json` 读取；网页保存后使用原子写入的 `connection.json` 同时保存配置和认证，旧文件保留作回退副本。新旧文件均含敏感信息，只由 Python 使用。不要把 `profiles` 提交到代码仓库或分享给别人。回退到不识别 `connection.json` 的旧脚本会读取旧配置，修改不会自动同步回旧文件。
启动器只保存解释器、脚本路径、方案 ID；高级模式复制的命令不包含代理密码。
项目原有模型 API Key 和登录方式保持原来的处理方式，Python 不接管模型认证。

## 诊断边界

`UPSTREAM_TCP_TLS` 表示入口 TCP/TLS 连接失败，`TLS_CERTIFICATE` 表示证书验证失败，
`UPSTREAM_AUTH` 表示代理认证失败，`UPSTREAM_CONNECT` 表示上游连接被拒绝。
`CLI_ISOLATION` 表示 Codex 不能保证本次会话隔离；检查 CLI 版本或移除 `--remote` 参数。
按需 `run` 会先验证加密入口及上游 CONNECT；失败不启动 CLI，也不自动直连。常驻启动只在本地监听，点击「测试已保存方案」才执行独立网络诊断；实际请求失败也不会改走直连。停止诊断不会停止正在使用的常驻连接。
HTTP 401 仅说明目标给出了未认证响应；403 也可能是目标封禁，均不等于模型调用成功。
模型认证失败需要处理 Codex / Claude Code 本身的账号；Python 不会自动登录或替换 Key。

## 开发验证

`python3 -m unittest discover -s python-connection/tests -v`（测试 TLS fixture 还需要 `openssl` 命令）。
包含本地认证、TLS 证书错误、IPv6 TLS、流式传输、规则优先级、公司 DNS 失败、旧包导入、路径引用、并发端口、环境隔离和 POSIX 中断清理；还覆盖网页来源校验、认证脱敏、原子保存、过期编辑拒绝、常驻停止清理及 CLI 关闭不误停常驻。
Windows Job Object、Windows 真实终端和模型调用必须在 Windows 实机另行验收；Mac 的结果不能代替。

接口版本 1：`profiles --json` 保持原 `protocol` 和方案 ID 列表，新增可选 `capabilities`。支持新能力的启动器用 `web` 打开管理页，不支持的旧启动器继续 `menu`；`doctor` / `run -- CLI ...` 不变。
传输和规则由 Python 独立实现，订阅导入和 SS / AnyTLS 不依赖启动器实现协议逻辑。
