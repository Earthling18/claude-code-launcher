---
name: notebooklm-unified
description: NotebookLM 统一技能。当用户需要以下功能时触发：(1) 生成播客/音频/视频/PPT/报告/信息图/数据表格；(2) 向 NotebookLM 笔记本提问/查询文档；(3) 管理笔记本库（添加/搜索/激活）；(4) 明确提到 NotebookLM。支持输入源：微信公众号、网页、YouTube、PDF、Word、Excel、PPT、Markdown、图片、音频等。
---

# NotebookLM 统一技能

## 核心原则

1. **生成任务创建新笔记本**，查询任务使用用户指定的笔记本
2. **YouTube/网页直接 `source add "URL"`**，不要转写
3. **中国大陆必须配置代理**才能访问
4. **查询统一用 `notebooklm ask`**
5. **认证用 `notebooklm login`**，状态在 `~/.notebooklm/`

## 禁止行为（NEVER）

- 生成 Quiz/Flashcards/Mind-map（卡死进程）
- `source add-text` 传大段文本（爆上下文）
- 转写 YouTube 字幕再上传
- 直接上传内网加密 Office 文档（NotebookLM 无法解析，须 Claude 转 Markdown）
- 猜测笔记本内容描述

## 环境准备（每次会话首先执行）

### 1. 定位 SKILL_DIR

搜索 `notebooklm-unified/SKILL.md` 所在目录，在 `~/.claude` 和当前项目 `.claude/skills` 下查找。**不要硬编码路径。**

### 2. 激活 venv

- macOS/Linux: `source $SKILL_DIR/venv/bin/activate`
- Windows: `$SKILL_DIR\venv\Scripts\activate`
- **venv 不存在时**运行 `python3 $SKILL_DIR/install.py`（Windows 用 `python`）

### 3. 检测并设置代理

检测 clash/v2ray/surge/ss-local/trojan 进程及端口。常见端口：7890(Clash)、10808(V2Ray)、1087(Surge)、1080(SS)。未检测到则询问用户。设置 `http_proxy` 和 `https_proxy`。

### 4. 首次登录（CRITICAL）

`notebooklm login` 需要交互式终端（用户需按 Enter 确认），Claude 的 bash 工具无法处理。

**登录方法**：运行登录辅助脚本，它会打开一个新终端窗口引导用户：
```bash
python $SKILL_DIR/scripts/nlm_login.py
```

脚本会自动：检测代理 → 激活 venv → 打开新终端窗口 → 用户完成 Google 登录 → 按 Enter → 保存认证

**验证登录**：`COLUMNS=200 notebooklm list`

**NEVER**：不要直接在 Claude bash 中执行 `notebooklm login`，会因无法处理 stdin 而失败。

## 关键坑位（CRITICAL）

| 坑 | 解决 |
|---|------|
| `notebooklm list` ID 被终端宽度截断 | **必须** `COLUMNS=200 notebooklm list` 获取完整 UUID |
| 截断 ID 调 `use` 报 `RPC GET_NOTEBOOK failed` | 用完整 36 位 UUID |
| `create` 不自动切换笔记本 | `create` 后必须 `use <ID>` |
| macOS PEP 668 禁止系统 pip install | 只用 venv 内的 pip |
| Windows 上 `python3` 不存在 | 用 `python` |
| `artifact wait` 缺少 ID 报错 | `artifact wait <ARTIFACT_ID>`，ID 不可省略 |
| `download` 误放在 `artifact` 下 | `download` 是顶层命令：`notebooklm download <type>`，不是 `artifact download` |
| `notebooklm login` 在 Claude bash 中超时/失败 | 必须通过 `python $SKILL_DIR/scripts/nlm_login.py` 打开新终端窗口登录 |

## 工作流 A：生成

1. 激活 venv + 设置代理
2. `notebooklm create "标题"` → `notebooklm use <ID>`
3. 添加源：URL 用 `source add "URL"`；内网加密文档须 Claude 先解析为 Markdown 再 `source add`
4. `notebooklm generate <type>` → 获取返回的 ARTIFACT_ID
5. `notebooklm artifact wait <ARTIFACT_ID>` — 必须传 ID
6. `notebooklm download <type>` — download 是顶层命令，不是 artifact 的子命令

生成类型：`audio` | `video` | `slide-deck` | `infographic` | `data-table` | `report`

命令层级速查：
- `artifact` 子命令：`list | get | rename | delete | export | poll | wait`
- `download` 子命令（顶层）：`audio | video | slide-deck | infographic | report | mind-map | data-table`

已通过 `notebooklm language set zh_Hans` 全局默认简体中文。英文加 `--language en`。无明确指令只上传不生成。

## 工作流 B：查询

1. 激活 venv + 设置代理
2. `COLUMNS=200 notebooklm list` 获取完整 ID
3. `notebooklm use <ID>` 或 `notebooklm ask "问题" --notebook <ID>`

### 输出风格（CRITICAL）

查询结果回复用户时，遵循以下风格：

- 纯文字为主，不用 emoji、不用装饰符号（如 ✅❌🔥⚡ 等）
- 用简洁的自然段落组织内容，段落之间空一行
- 需要列举时用短横线（-）或数字序号，不用嵌套列表
- 标题层级最多两级，用加粗代替三级标题
- 不输出 Markdown 表格（在企业微信等 IM 中渲染差）
- 关键概念可加粗，但不要满篇加粗
- 代码片段保留代码块格式
- 整体控制在手机一屏半以内，避免信息过载

### 跟进提问（CRITICAL）

获取回答后不要立即回复用户。对比原始请求，识别信息缺口，`notebooklm ask` 追问直到信息完整，合并后再回复。

### 智能发现

用户分享 URL 但无描述时：先 `ask "What topics are covered?"` 了解内容，再添加到笔记本库。

## 工作流 C：笔记本库

管理脚本：`python $SKILL_DIR/scripts/notebook_library.py`

子命令：`list` | `add --url --name --description --topics` | `search --query` | `activate --id` | `remove --id` | `stats`

**添加时不要猜测描述**，用智能发现或问用户。

## 微信公众号

MCP `read_weixin_article` 抓取 → 存 Markdown → `source add`

## 错误处理

详见 `references/troubleshooting.md`。
