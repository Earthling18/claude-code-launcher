# 连接助手 · 云节点 / 本地订阅试用

## 日常使用

1. Mac 双击 `manage.command`，Windows 双击 `manage.cmd`。需要 Python 3.11+。
2. 选择「云节点」或「订阅节点」。首次使用订阅，按页面提示安装 Python 支持库，然后粘贴 HTTPS 订阅地址或 Clash YAML / JSON / SS 链接。
3. 选节点，点「检测此节点」。HTTP 401 是网络诊断；实际模型回复才算模型成功。
4. CLI：在 CC 启动器新建一条代理，展开高级 Python，选择本目录 `ai-connection.py`，点「检测 / 刷新方案」，按名称选择节点。项目继续用原来的代理下拉框。
5. Mac Codex 客户端：先完整退出原客户端，再点击「打开 Codex · 保留记录」。不会自动强退现有窗口。不要关闭正在承载工作/本次对话的客户端来配合自动测试。

原普通代理仍可切回。每个 CLI 拥有自己的随机回环端口，退出后清理。无需先手工运行常驻代理。网页中的常驻模式是可选项。规则与公司 DNS 在「更多设置与排查」里，按连接分别保存。

## 支持范围

- 云节点：有合法证书与认证的 TLS HTTP CONNECT 入口。
- 本地 SS TCP：aes-128-gcm / aes-256-gcm / chacha20-ietf-poly1305；支持 simple-obfs HTTP。不忽略不支持的插件。
- 本地 AnyTLS TCP：标准 Python TLS，证书验证开启；支持会话复用、服务端 padding 更新、30 秒空闲回收。不会模拟 Chrome TLS 指纹。
- VLESS / Reality、VMess、Hysteria、SS 2022、UDP / TUN 不支持，会标注原因。要求跳过证书验证的节点不能选用。
- 只接管明确接入的进程。没有系统代理、系统服务、TUN 或开机启动。Python 和加密扩展库不等于进程不可见。
- 浏览器专用入口未加入。Windows CLI 跨平台代码与模拟测试已覆盖，Windows 实机、Windows 客户端入口尚未验收。

## 配置和安全边界

订阅地址、节点密码保存在 `profiles/.subscriptions.json`；已选连接是独立快照，保存在各方案 `connection.json`。更新订阅后重新选择节点，才应用新凭据。进行中的会话不切换。若更新只剩不支持协议，保留现有列表并提示。网址与密码不出现在诊断和复制的启动命令中。

可选依赖只有 cryptography 46.0.7、PyYAML 6.0.3 及其依赖，安装到工具目录 `.deps/` 下对应的 Python / 系统版本目录，不修改系统 Python。云节点不依赖这两个库。没有下载 Clash、Mihomo、sing-box 或独立代理 EXE。

AnyTLS 空闲上游最多保留 30 秒，关闭本次代理即清理；没有定时测速。节点域名使用加密 DNS 解析，目的域名随加密隧道交给节点。SS HTTP 混淆会暴露混淆 Host，不代表目标网址，但也不保证无法被识别为代理。直连规则对应的请求本来就不经隧道。

## 本轮实测（2026-11-16，Mac）

- Nexi SS「Hong Kong 01」：真实 Codex 返回 `LOCAL_SS_CODEX_OK`，17 次代理、0 次直连、0 次失败。
- 网际 AnyTLS「美国·AWSSG·1倍消耗」：真实 Codex 返回 `LOCAL_ANYTLS_US_OK`，20 次代理、0 次直连、0 次失败。
- 原云方案：真实 Codex 返回 `CLOUD_REGRESSION_OK`，18 次代理、0 次直连、0 次失败。
- 测试节点配置绑定 en0，避免被本机 TUN 路由串联；没有切换或关闭用户当前网络。
- 网际香港 AnyTLS 的 HTTP 401 不代表模型成功：模型请求超时。新加坡 AWSSG 节点遇到证书错误。
- 当前网际订阅链接实取只返回 2 个 VLESS 节点；旧缓存的 AnyTLS 仍可完成上述模型请求。试用包保留已测试的缓存，不会用这次不兼容的更新覆盖它。节点可用性以当时实测为准。
- Claude Code 官方账号按用户要求未测。Mac 客户端保留历史的 GUI 模型请求需用户完整退出后手动验收，不能用 CLI 成功替代。

协议参考：[SS AEAD](https://shadowsocks.org/doc/aead.html)、[AnyTLS](https://github.com/anytls/anytls-go/blob/main/docs/protocol.md)、[simple-obfs HTTP](https://github.com/shadowsocks/simple-obfs/blob/master/src/obfs_http.c)。
