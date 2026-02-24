---
name: cron-manager
description: |
  定时任务管理技能。当用户说"每天早上X点提醒我"、"定时给我发"、"每周一发送"、"X分钟后提醒我"、"我有哪些定时任务"、"查看我的定时任务"、"取消定时任务"、"删除定时任务"时使用此技能。支持简单提醒（固定文本）和复杂任务（触发 /skill 动态生成）两种模式。
---

# 定时任务管理

## 重要：执行规范

**严格禁止在工具调用之间输出任何文字。** 连续调用工具，中间不说话。只在全部操作完成后输出一条最终回复。

**绝对禁止提及以下内容（用户不关心这些）：**
- 服务器时间、当前时间
- 时间计算过程（如"X分钟后是XX:XX"）
- "让我先查看时间"、"我来创建任务"等过渡语

正确：调用 time → 调用 create →（全部完成后）"好的，XX:XX 会提醒你喝水"
错误：调用 time → 输出"服务器时间是18:18，3分钟后是18:21" → 调用 create → "创建成功"

## 重要：使用系统注入的上下文

系统已在提示中注入当前请求的上下文信息，格式如下：

```
# 当前请求上下文
- 对话 ID: R:xxx（群聊）或 xxx（私聊）
- 对话类型: 群聊/私聊
```

**创建定时任务时，必须使用系统注入的对话 ID，不要从 time 命令获取。**

这是解决并发覆盖问题的关键：当同一用户在不同群聊同时创建任务时，系统注入的上下文是并发安全的。

## 任务类型判断

| 用户表达 | 类型 | 参数 |
|---------|------|------|
| "提醒我喝水"、"提醒我开会" | 简单提醒 | `--message "提醒：xxx"` |
| "发晨报"、"汇总数据"、"生成报告" | 复杂任务 | `--skill "/skill-name"` |

**判断依据**：
- 消息内容**固定**（提醒、通知）→ `--message`
- 需要 AI **动态生成**（报告、分析）→ `--skill "/skill-name"`

## 创建定时任务

### 第1步：获取服务器时间（仅用于计算 cron 表达式）

```bash
python scripts/cron_cli.py time
```

返回示例：
```json
{
  "server_time": "2026-02-03 19:40:00",
  "weekday": "Monday",
  "weekday_num": 1
}
```

**注意**：time 命令仅用于获取服务器时间以计算 cron 表达式，**不要使用 time 命令返回的 context 信息**。

### 第2步：自然语言转 cron

| 用户说 | cron | 计算方式 |
|--------|------|---------|
| 每天早上7点 | `0 7 * * *` | 固定 |
| 每天下午3点 | `0 15 * * *` | 固定 |
| 每周一早上9点 | `0 9 * * 1` | 固定 |
| 每月1号 | `0 9 1 * *` | 固定 |
| 工作日早上8点 | `0 8 * * 1-5` | 固定 |
| X分钟后 | `(server_time + X分钟)` | **动态计算** |
| 明天下午3点 | `0 15 (server_date+1) (month) *` | **动态计算** |

**动态计算示例**：
- `server_time = 2026-02-03 18:40:00`
- 用户说"1分钟后" → 18:40 + 1分钟 = 18:41 → cron = `41 18 3 2 *`
- 用户说"30分钟后" → 18:40 + 30分钟 = 19:10 → cron = `10 19 3 2 *`

### 第3步：创建任务

**根据系统提示中的"对话类型"确定参数**：
- 对话类型为"群聊" → 使用 `--context-type group --target-type group`
- 对话类型为"私聊" → 使用 `--context-type private --target-type self`

**`--context-conversation-id` 的值必须从系统提示的"当前请求上下文"中获取对话 ID。**

**群聊场景**（对话类型: 群聊）：
```bash
python scripts/cron_cli.py create \
  --cron "0 9 * * *" \
  --message "该喝水了！" \
  --context-type group \
  --target-type group \
  --context-conversation-id "R:xxx"
```
> `--context-conversation-id` 的值直接从系统提示的"对话 ID"获取

**私聊场景**（对话类型: 私聊）：
```bash
python scripts/cron_cli.py create \
  --cron "0 9 * * *" \
  --message "该喝水了！" \
  --context-type private \
  --target-type self \
  --context-conversation-id "xxx"
```

**复杂任务（触发 Skill）**：
```bash
python scripts/cron_cli.py create \
  --cron "0 7 * * 1" \
  --skill "/timesheet-analysis" \
  --context-type group \
  --target-type group \
  --context-conversation-id "R:xxx"
```

**一次性任务**：添加 `--delete-after-run`

```bash
python scripts/cron_cli.py create \
  --cron "41 18 3 2 *" \
  --message "开会时间到！" \
  --delete-after-run \
  --context-type private \
  --target-type self \
  --context-conversation-id "xxx"
```

## 查看定时任务

```bash
python scripts/cron_cli.py list
```

输出格式：
```
您的定时任务：
1. [job-abc] 每天 07:00 触发 /daily-report → 发给自己
2. [job-def] 每天 09:00 发送 "该喝水了！" → 发给自己
```

## 删除定时任务

```bash
python scripts/cron_cli.py delete --job-id "job-xxx"
```

## 风险校验

### 私聊场景
| 意图 | 处理 |
|-----|------|
| "提醒我" / "给我发" | 自动发给自己 |
| "提醒张三" / "发给某人" | **拒绝**：私聊只能发给自己 |
| "发到某群" | **拒绝**：私聊只能发给自己 |

### 群聊场景
群聊中创建的定时任务**只能发到本群**，不支持私发。

| 意图 | 处理 |
|-----|------|
| 任何提醒请求 | 自动发到本群 |
| "发给张三" / "发到其他群" / "私发给我" | **拒绝**：群聊只能发到本群 |

## 拒绝响应模板

**私聊拒绝**：
> 抱歉，私聊场景下只能给自己发送定时消息。如需发送到群里，请在目标群中 @我 创建。

**群聊拒绝**：
> 抱歉，群聊中创建的定时任务只能发到本群，不支持私发或发到其他群。

## 回复风格

创建成功后，只需简洁确认：
- 告知任务内容和定时信息（如"好的，每天早上9点提醒你喝水"）
- **不要提及**：任务ID、执行一次后删除、技术参数、调度器状态
- **不要使用固定格式**，用自然的对话语气回复

查看任务时，简洁列出即可：
- 只展示任务内容和执行时间
- 不要展示任务ID、创建时间等技术字段

删除任务时，简单确认已取消即可。
