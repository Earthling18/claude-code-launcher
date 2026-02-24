#!/usr/bin/env python3
"""
定时任务 CLI 工具

用法：
    # 获取服务器时间（创建任务前必须先调用）
    python cron_cli.py time

    # 简单提醒（自动从上下文获取用户信息）
    python cron_cli.py create --cron "0 9 * * *" --message "⏰ 该喝水了！"

    # 复杂任务（触发 Skill）
    python cron_cli.py create --cron "0 7 * * *" --skill "/daily-report"

    # 一次性任务
    python cron_cli.py create --cron "0 10 15 1 *" --message "开会提醒" --delete-after-run

    # 列出任务（自动从上下文获取用户信息）
    python cron_cli.py list

    # 删除任务
    python cron_cli.py delete --job-id "xxx"

上下文自动识别：
    脚本会自动读取 workspace/.request_context.json 获取：
    - user_id, user_name: 当前用户
    - conversation_id: 对话 ID
    - group_chat_name: 群聊名称（非空表示群聊）
    - is_group: 是否群聊

    群聊中创建的任务会自动设置 target_type="group"，发到本群。
    私聊中创建的任务自动设置 target_type="self"，发给自己。
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path


# 配置文件路径（项目根目录）
# scripts/cron_cli.py -> cron-manager -> skills -> .claude -> 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
CRON_JOBS_FILE = PROJECT_ROOT / "cron_jobs.json"

# 请求上下文文件（由服务端写入）
# workspace 目录是 PROJECT_ROOT / "workspace" / user_id
# 但我们需要从当前工作目录找到它
REQUEST_CONTEXT_FILENAME = ".request_context.json"


def _load_context_from_file() -> dict:
    """
    从文件加载请求上下文（内部辅助函数）

    搜索路径：
    1. 环境变量 CLAUDE_USER_WORKSPACE 指定的目录
    2. 当前工作目录（回退）
    """
    # 1. 优先使用环境变量指定的 workspace（SDK 调用时会设置此变量）
    user_workspace = os.environ.get("CLAUDE_USER_WORKSPACE")
    if user_workspace:
        env_context = Path(user_workspace) / REQUEST_CONTEXT_FILENAME
        if env_context.exists():
            try:
                return json.loads(env_context.read_text(encoding="utf-8"))
            except Exception:
                pass

    # 2. 回退：尝试当前工作目录（用于测试或直接调用）
    cwd_context = Path.cwd() / REQUEST_CONTEXT_FILENAME
    if cwd_context.exists():
        try:
            return json.loads(cwd_context.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {}


def load_request_context() -> dict:
    """
    加载请求上下文（优先使用环境变量，解决并发覆盖问题）

    并发场景下，同一用户在不同群聊创建定时任务时，文件可能被后到的请求覆盖。
    通过环境变量传递 conversation_id 和 is_group 可以避免这个问题，
    因为环境变量的设置和 SDK 调用在同一个同步代码块中。

    优先级：
    1. 环境变量 CLAUDE_CONVERSATION_ID 和 CLAUDE_IS_GROUP（并发安全）
    2. 文件 .request_context.json（向后兼容）

    Returns:
        上下文字典，包含 user_id, user_name, conversation_id, group_chat_name, is_group
        如果未找到返回空字典
    """
    # 1. 优先从环境变量读取关键字段（并发安全）
    env_conv_id = os.environ.get("CLAUDE_CONVERSATION_ID")
    env_is_group = os.environ.get("CLAUDE_IS_GROUP")

    # 从文件读取基础上下文（用户名等非关键字段）
    file_context = _load_context_from_file()

    if env_conv_id:
        # 环境变量优先：覆盖文件中的 conversation_id 和 is_group
        # 这是并发安全的，因为环境变量在 SDK 调用前同步设置
        context = file_context.copy()
        context["conversation_id"] = env_conv_id
        context["is_group"] = (env_is_group == "true") if env_is_group else file_context.get("is_group", False)
        return context

    # 2. 回退到文件读取（向后兼容）
    return file_context


def load_jobs() -> dict:
    """加载任务配置"""
    if not CRON_JOBS_FILE.exists():
        return {"jobs": []}

    try:
        return json.loads(CRON_JOBS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error loading jobs: {e}", file=sys.stderr)
        return {"jobs": []}


def save_jobs(config: dict) -> None:
    """保存任务配置"""
    CRON_JOBS_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def notify_cron_service_reload() -> dict:
    """
    通知 CronService 重新加载任务配置

    调用 /api/v1/cron/reload 接口，使新创建的任务立即生效。
    使用 PowerShell 发送请求以避免 Python urlopen 的兼容性问题。

    Returns:
        dict: {"success": bool, "loaded": int, "message": str}
    """
    try:
        # 使用 PowerShell 发送 POST 请求（避免 Python urlopen 502 问题）
        cmd = [
            "powershell", "-Command",
            "Invoke-RestMethod -Uri 'http://localhost:8000/api/v1/cron/reload' -Method Post | ConvertTo-Json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            return {
                "success": data.get("success", False),
                "loaded": data.get("loaded", 0),
                "message": data.get("message", "Reload completed")
            }
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            return {"success": False, "message": f"请求失败: {error_msg}"}

    except subprocess.TimeoutExpired:
        return {"success": False, "message": "请求超时"}
    except json.JSONDecodeError as e:
        return {"success": False, "message": f"响应解析失败: {e}"}
    except Exception as e:
        return {"success": False, "message": f"通知失败: {str(e)}"}


def show_time(args) -> None:
    """显示服务器当前时间和请求上下文"""
    now = datetime.now()
    context = load_request_context()

    result = {
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": now.isoformat(),
        "weekday": now.strftime("%A"),
        "weekday_num": now.isoweekday(),  # 1=周一, 7=周日
        # 上下文信息（用于判断群聊/私聊）
        "context": {
            "is_group": context.get("is_group", False),
            "conversation_type": context.get("conversation_type", ""),
            "conversation_id": context.get("conversation_id", ""),
            "user_name": context.get("user_name", ""),
        }
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def validate_cron_not_expired(cron: str, is_one_time: bool) -> tuple:
    """
    校验 cron 时间是否已过期（对于一次性任务）

    Args:
        cron: Cron 表达式（5段式）
        is_one_time: 是否是一次性任务（有具体日期）

    Returns:
        (is_valid, error_message, scheduled_time)
    """
    parts = cron.split()
    if len(parts) != 5:
        return False, "Cron 表达式格式错误，需要 5 段", None

    minute, hour, day, month, weekday = parts
    now = datetime.now()

    # 检查是否是一次性任务（日期和月份都是具体数字）
    if day != "*" and month != "*":
        try:
            scheduled = datetime(
                year=now.year,
                month=int(month),
                day=int(day),
                hour=int(hour) if hour != "*" else 0,
                minute=int(minute) if minute != "*" else 0
            )

            if scheduled < now:
                return False, (
                    f"[ERROR] 定时任务时间 {scheduled.strftime('%H:%M')} 已过期! "
                    f"当前服务器时间是 {now.strftime('%Y-%m-%d %H:%M:%S')}. "
                    f"请先执行 `python scripts/cron_cli.py time` 获取服务器时间, "
                    f"然后基于返回的 server_time 重新计算正确的 cron 表达式."
                ), scheduled

            return True, None, scheduled
        except ValueError as e:
            return False, f"Cron 表达式解析失败: {e}", None

    # 周期性任务不校验
    return True, None, None


def create_job(args) -> None:
    """创建定时任务"""
    # 验证 message 和 skill 二选一
    has_message = args.message is not None and args.message.strip()
    has_skill = args.skill is not None and args.skill.strip()

    if not has_message and not has_skill:
        print(json.dumps({
            "success": False,
            "message": "必须指定 --message 或 --skill"
        }, ensure_ascii=False, indent=2))
        return

    if has_message and has_skill:
        print(json.dumps({
            "success": False,
            "message": "--message 和 --skill 不能同时指定，请选择其一"
        }, ensure_ascii=False, indent=2))
        return

    # 校验 cron 时间是否已过期
    is_one_time = args.delete_after_run or False
    is_valid, error_msg, scheduled_time = validate_cron_not_expired(args.cron, is_one_time)
    if not is_valid:
        print(json.dumps({
            "success": False,
            "message": error_msg,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hint": "请先调用 `python scripts/cron_cli.py time` 获取服务器时间"
        }, ensure_ascii=False, indent=2))
        return

    # ======== 自动从上下文获取用户信息 ========
    context = load_request_context()
    ctx_user_id = context.get("user_id", "")
    ctx_user_name = context.get("user_name", "")
    ctx_conversation_id = context.get("conversation_id", "")
    ctx_group_chat_name = context.get("group_chat_name", "")
    ctx_is_group = context.get("is_group", False)
    ctx_user_token = context.get("user_token", "")

    # ======== 并发安全：优先使用命令行传递的 conversation_id ========
    # 在 asyncio 并发场景下，同一用户在不同群聊创建定时任务时：
    # - 文件 .request_context.json 可能被后到的请求覆盖
    # - 环境变量在 await 期间也会被其他协程覆盖
    # 唯一可靠的方式是让 Agent 在调用 cron_cli.py 时显式传递 conversation_id
    if args.context_conversation_id:
        # 命令行参数优先（并发安全）
        owner_conversation_id = args.context_conversation_id
        owner_name = ctx_user_name or args.owner_name or "用户"
    elif ctx_conversation_id:
        # 回退到上下文文件（向后兼容，单请求场景仍然有效）
        owner_conversation_id = ctx_conversation_id
        owner_name = ctx_user_name or args.owner_name or "用户"
    else:
        # 最后回退到其他命令行参数
        owner_conversation_id = args.owner_conversation_id or ""
        owner_name = args.owner_name or ctx_user_name or "用户"

    # 如果没有 owner 信息，报错
    if not owner_conversation_id:
        print(json.dumps({
            "success": False,
            "message": "缺少 owner_conversation_id，请确保在正确的上下文中运行",
            "context_found": bool(context),
            "hint": "请通过企业微信与 Agent 对话来创建定时任务"
        }, ensure_ascii=False, indent=2))
        return

    # ======== 自动确定 context_type 和 target_type ========
    # 如果命令行指定了，使用命令行的值；否则根据上下文自动判断
    if args.context_type:
        context_type = args.context_type
    else:
        context_type = "group" if ctx_is_group else "private"

    if args.target_type:
        target_type = args.target_type
    else:
        # 群聊中默认发到群，私聊中只能发给自己
        target_type = "group" if ctx_is_group else "self"

    # 群聊信息
    group_conversation_id = args.group_conversation_id or (ctx_conversation_id if ctx_is_group else "")
    group_name = args.group_name or ctx_group_chat_name

    config = load_jobs()

    # 生成唯一 ID
    job_id = f"job-{uuid.uuid4().hex[:8]}"

    # 构建任务配置
    job = {
        "id": job_id,
        "cron": args.cron,
        "context_type": context_type,
        "target_type": target_type,
        "owner_conversation_id": owner_conversation_id,
        "owner_name": owner_name,
        "created_at": datetime.now().isoformat(),
        "enabled": True,
        "user_token": ctx_user_token,
    }

    # message 或 skill 二选一
    if has_message:
        job["message"] = args.message
    else:
        # 防御 Git Bash MSYS 路径转换：
        # "/timesheet-analysis" 可能被转为 "C:/Program Files/Git/timesheet-analysis"
        # 提取最后一段作为 skill 名称
        skill_name = args.skill.strip().rstrip("/")
        skill_name = skill_name.split("/")[-1]
        job["skill"] = skill_name

    # 群聊场景需要记录群信息
    if context_type == "group":
        job["group_conversation_id"] = group_conversation_id
        job["group_name"] = group_name

    # 确定发送目标
    if target_type == "self":
        # 发给自己
        job["target_conversation_id"] = owner_conversation_id
        job["target_name"] = owner_name
    elif target_type == "group":
        # 发到群
        job["target_conversation_id"] = group_conversation_id
        job["target_name"] = group_name

    # 可选字段
    if args.start_date:
        job["start_date"] = args.start_date
    if args.end_date:
        job["end_date"] = args.end_date
    if args.delete_after_run:
        job["delete_after_run"] = True

    config["jobs"].append(job)
    save_jobs(config)

    # 通知服务 reload（使新任务立即生效）
    reload_result = notify_cron_service_reload()

    # 确定任务类型描述
    task_type = "简单提醒" if has_message else "定时Skill"

    output = {
        "success": True,
        "job_id": job_id,
        "message": f"{task_type}创建成功",
        "job": job,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reload": reload_result,
        "context_auto_detected": {
            "is_group": ctx_is_group,
            "context_type": context_type,
            "target_type": target_type,
        }
    }

    # 如果 reload 成功，显示已加载的任务数
    if reload_result.get("success"):
        output["message"] = f"{task_type}创建成功，已加载到调度器"

    print(json.dumps(output, ensure_ascii=False, indent=2))


def list_jobs(args) -> None:
    """列出用户的定时任务"""
    # 自动从上下文获取 owner_conversation_id
    context = load_request_context()
    owner_conversation_id = args.owner_conversation_id or context.get("conversation_id", "")

    if not owner_conversation_id:
        print(json.dumps({
            "success": False,
            "message": "缺少 owner_conversation_id，请确保在正确的上下文中运行",
            "hint": "请通过企业微信与 Agent 对话来查询定时任务"
        }, ensure_ascii=False, indent=2))
        return

    config = load_jobs()

    # 过滤当前用户的任务
    user_jobs = [
        job for job in config["jobs"]
        if job.get("owner_conversation_id") == owner_conversation_id
        and job.get("enabled", True)
    ]

    if not user_jobs:
        print(json.dumps({
            "success": True,
            "jobs": [],
            "message": "您还没有创建任何定时任务"
        }, ensure_ascii=False, indent=2))
        return

    # 格式化输出
    formatted_jobs = []
    for job in user_jobs:
        # 确定任务类型和内容
        message = job.get("message")
        skill = job.get("skill") or job.get("command")  # 兼容旧数据
        if message:
            task_type = "message"
            task_content = message
        else:
            task_type = "skill"
            task_content = skill

        formatted_job = {
            "id": job["id"],
            "cron": job["cron"],
            "cron_desc": cron_to_chinese(job["cron"]),
            "task_type": task_type,
            "task_content": task_content,
            "target": job.get("target_name", "自己"),
            "context_type": job.get("context_type", "private"),
            "created_at": job.get("created_at", "")
        }

        # 可选字段
        if job.get("end_date"):
            formatted_job["end_date"] = job["end_date"]
        if job.get("delete_after_run"):
            formatted_job["delete_after_run"] = True

        formatted_jobs.append(formatted_job)

    print(json.dumps({
        "success": True,
        "jobs": formatted_jobs,
        "message": f"找到 {len(formatted_jobs)} 个定时任务"
    }, ensure_ascii=False, indent=2))


def delete_job(args) -> None:
    """删除定时任务"""
    config = load_jobs()

    # 查找任务
    job_index = None
    for i, job in enumerate(config["jobs"]):
        if job["id"] == args.job_id:
            job_index = i
            break

    if job_index is None:
        print(json.dumps({
            "success": False,
            "message": f"未找到任务: {args.job_id}"
        }, ensure_ascii=False, indent=2))
        return

    # 删除任务
    deleted_job = config["jobs"].pop(job_index)
    save_jobs(config)

    print(json.dumps({
        "success": True,
        "message": f"定时任务已删除",
        "deleted_job": deleted_job
    }, ensure_ascii=False, indent=2))


def cron_to_chinese(cron: str) -> str:
    """将 cron 表达式转换为中文描述"""
    parts = cron.split()
    if len(parts) != 5:
        return cron

    minute, hour, day, month, weekday = parts

    # 简单的转换逻辑
    desc_parts = []

    # 周几
    weekday_map = {
        "*": "",
        "1-5": "工作日",
        "0": "周日",
        "1": "周一",
        "2": "周二",
        "3": "周三",
        "4": "周四",
        "5": "周五",
        "6": "周六",
    }
    if weekday in weekday_map:
        if weekday_map[weekday]:
            desc_parts.append(weekday_map[weekday])
    elif weekday != "*":
        desc_parts.append(f"每周{weekday}")

    # 月份
    if month != "*":
        desc_parts.append(f"{month}月")

    # 日期
    if day != "*":
        desc_parts.append(f"{day}号")

    # 时间
    if hour != "*" and minute != "*":
        desc_parts.append(f"{hour}:{minute.zfill(2)}")
    elif hour != "*":
        desc_parts.append(f"{hour}点")

    if not desc_parts:
        return "每分钟"

    # 添加"每天"如果只有时间
    if weekday == "*" and month == "*" and day == "*" and hour != "*":
        desc_parts.insert(0, "每天")

    return " ".join(desc_parts)


def main():
    parser = argparse.ArgumentParser(description="定时任务管理工具（自动从上下文获取用户信息）")
    subparsers = parser.add_subparsers(dest="action", help="操作类型")

    # create 子命令
    create_parser = subparsers.add_parser("create", help="创建定时任务")
    create_parser.add_argument("--cron", required=True, help="Cron 表达式")
    # message 和 skill 二选一
    create_parser.add_argument("--message", help="直接发送的消息（简单提醒，与 --skill 二选一）")
    create_parser.add_argument("--skill", help="要触发的 Skill（复杂任务，如 /timesheet-analysis）")
    # 以下参数可选，不指定时从上下文自动获取
    create_parser.add_argument("--context-type", choices=["private", "group"], help="上下文类型（自动检测）")
    create_parser.add_argument("--target-type", choices=["self", "group"], help="发送目标（自动检测）")
    create_parser.add_argument("--owner-conversation-id", help="创建者对话ID（自动获取）")
    create_parser.add_argument("--owner-name", help="创建者名称（自动获取）")
    create_parser.add_argument("--group-conversation-id", help="群聊对话ID（自动获取）")
    create_parser.add_argument("--group-name", help="群聊名称（自动获取）")
    create_parser.add_argument("--start-date", help="生效开始时间（ISO 格式）")
    create_parser.add_argument("--end-date", help="到期时间（ISO 格式，到期后自动删除）")
    create_parser.add_argument("--delete-after-run", action="store_true", help="执行一次后自动删除（一次性任务）")
    # 并发安全参数：Agent 从 time 命令获取 conversation_id 后显式传递
    create_parser.add_argument("--context-conversation-id",
        help="当前对话ID（由Agent从time命令获取并传递，解决并发覆盖问题）")

    # list 子命令
    list_parser = subparsers.add_parser("list", help="列出定时任务")
    list_parser.add_argument("--owner-conversation-id", help="创建者对话ID（自动获取）")

    # delete 子命令
    delete_parser = subparsers.add_parser("delete", help="删除定时任务")
    delete_parser.add_argument("--job-id", required=True)

    # time 子命令
    subparsers.add_parser("time", help="显示服务器当前时间")

    args = parser.parse_args()

    if args.action == "create":
        create_job(args)
    elif args.action == "list":
        list_jobs(args)
    elif args.action == "delete":
        delete_job(args)
    elif args.action == "time":
        show_time(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
