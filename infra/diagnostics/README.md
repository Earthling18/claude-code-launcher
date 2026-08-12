# CC 启动器诊断接收端

这套 Terraform 创建 API Gateway、Function Compute 3.0 和 SLS。客户端只上报白名单事件；函数会再次校验固定 schema、拒绝扩展字段、复核 WebView `renderer` 缺失证据并二次脱敏，然后由 Function Compute 的日志配置写入 SLS。

## 安全边界

- API 仅接收 POST，正文上限 128 KiB。
- 自动事件仅允许 `webview_renderer_missing`、`rust_panic`、`tauri_startup_fatal`；另允许用户主动提交 `manual_diagnostic`。
- 白屏事件必须包含 3 次连续采样，且每次都满足 `browser_count > 0 && renderer_count == 0`，否则返回 422，不写 SLS。
- API Gateway 对来源 IP 和接口总量限流；Gateway 到 FC 使用随机共享密钥，FC 公网地址本身无法绕过校验。
- API Gateway 不记录请求正文；SLS 只接收函数输出的白名单字段。
- Terraform state 包含 Gateway/FC 共享密钥，应放在加密的远端 state 后端并限制读取权限。

## 部署与发布

1. 准备阿里云凭据，并为 `sls_project_name` 选择全局唯一的小写名称。
2. 在本目录初始化并应用 Terraform；首次执行会显式开通 SLS 与传统 API Gateway 服务。
3. 获取 `diagnostics_endpoint` 输出，在发布构建环境中设置 `CCL_DIAGNOSTICS_ENDPOINT` 后再编译 Tauri。该值通过 `option_env!` 固化进发布包，不需要把任何云端密钥放进客户端。
4. 先用函数目录内的 Node 测试验证 schema，再用测试包完成一次“手动提交诊断”冒烟测试。

默认二级域名适合小流量验证，正式长期使用建议在 API Gateway 绑定已备案的 HTTPS 自定义域名，并同步更新发布构建中的 endpoint。
