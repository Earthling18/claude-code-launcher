# CC 启动器诊断接收端

这套 Terraform 创建 API Gateway、Function Compute 3.0 和 SLS。安装包仍然放在原有 OSS；诊断事件写入独立 SLS Logstore，不占用安装包 OSS 空间。

## 安全与费用边界

- API 只接收 POST，单份正文硬上限 48 KiB。
- 自动事件只允许 `webview_renderer_missing`、`rust_panic`、`tauri_startup_fatal`；另允许用户主动提交 `manual_diagnostic`。
- 白屏事件必须包含 3 次连续采样，且每次都满足 `browser_count > 0 && renderer_count == 0`，否则返回 422，不写 SLS。
- 日志尾部最多 30 行、每行最多 300 字；备注最多 500 字。未知字段一律拒绝。
- 客户端对同版本、同故障类型 24 小时最多自动上报一次，本地待传队列最多保留 10 份。
- API Gateway 默认全局 300 次/天、同一来源 IP 10 次/天。按最大请求体计算，入口理论封顶约 14 MiB/天。
- Logstore 只使用 1 个分片，默认保留 14 天后自动删除。
- Gateway 到 FC 使用随机共享密钥；FC 公网地址本身无法绕过校验。SLS 只接收函数输出的白名单字段。
- Terraform state 包含共享密钥，只能以加密形式存放，并限制读取权限。

## 部署与发布

1. 创建诊断专用 RAM 用户，准备具备 FC、SLS、传统 API Gateway 和 RAM 资源管理权限的独立凭据；不要复用安装包 OSS AccessKey。
2. 为 `sls_project_name` 选择全局唯一的小写名称，执行 Terraform。
3. 取得 `diagnostics_endpoint` 输出，并设置 GitHub Secret `CCL_DIAGNOSTICS_ENDPOINT`。
4. 发布构建会通过 `option_env!` 将 HTTPS endpoint 固化进客户端；客户端不包含任何云端密钥。
5. 先运行函数目录内的 Node 测试，再用测试包完成一次“手动提交诊断”冒烟测试。

GitHub Actions 使用 `DIAGNOSTICS_ACCESS_KEY_ID`、`DIAGNOSTICS_ACCESS_KEY_SECRET` 管理诊断资源；原有 `OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET` 仅用于保存 AES-256 加密后的 Terraform state。两组凭据互不替代。

默认二级域名适合当前低流量诊断。若后续改用自定义 HTTPS 域名，需要同步更新 `CCL_DIAGNOSTICS_ENDPOINT` 并重新构建客户端。
