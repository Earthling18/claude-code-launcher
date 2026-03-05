"""
定时任务管理 MCP 工具

提供 cron_get_time、cron_create、cron_list、cron_delete 四个 MCP 工具，
替代原 cron-manager Skill + cron_cli.py CLI 脚本方案。

使用闭包捕获 context_getter，与 task_delegation_tool.py 同模式。
"""
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict

from claude_agent_sdk import tool, create_sdk_mcp_server

logger = logging.getLogger(__name__)


def cron_to_chinese(cron: str) -> str:
    """将 cron 表达式转换为中文描述"""
    parts = cron.split()
    if len(parts) != 5:
        return cron

    minute, hour, day, month, weekday = parts

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


def create_cron_server(context_getter: Callable[[], Dict[str, Any]]):
    """
    创建定时任务管理 SDK MCP 服务器

    使用闭包捕获 context_getter，确保工具调用时能获取最新的用户上下文。

    Args:
        context_getter: 返回用户上下文 dict 的 callable
            必须包含: user_id, conversation_id, user_name,
                      group_chat_name, is_group, user_token

    Returns:
        SDK MCP 服务器配置
    """
    captured_getter = context_getter

    @tool(
        "cron_get_time",
        "获取服务器当前时间。对于'X分钟后'的任务不需要调用此工具（直接用 cron_create 的 delay_minutes 参数）。"
        "仅在需要知道当前是周几、几点来决定 cron 表达式时使用（如'下周一'、'今天晚上8点'）。",
        {},
    )
    async def cron_get_time(args: Dict[str, Any]) -> Dict[str, Any]:
        """获取服务器当前时间"""
        now = datetime.now()
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday_num = now.isoweekday()  # 1=周一, 7=周日

        result = {
            "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": weekday_names[weekday_num - 1],
            "weekday_num": weekday_num,
        }
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    @tool(
        "cron_create",
        "创建定时任务。支持两种类型："
        "1) 简单提醒(message)：固定文本直发，如'提醒我喝水'、'提醒我开会'；"
        "2) 复杂任务(skill)：触发AI技能动态生成内容，如'发晨报'、'生成报告'、'分析数据'。"
        "message 和 skill 二选一。"
        "时间设置有两种方式（二选一）："
        "- delay_minutes: 相对时间，N分钟后触发（如'5分钟后提醒我'→delay_minutes=5），系统自动计算精确时间，执行后自动删除；"
        "- cron: 5段格式（分 时 日 月 周），用于周期任务。"
        "cron 周（day_of_week）约定：0=周日, 1=周一, 2=周二, 3=周三, 4=周四, 5=周五, 6=周六。"
        "常用模式：'* * * * *'=每分钟, '0 9 * * *'=每天9点, '0 9 * * 1-5'=工作日9点, '0 9 * * 1'=每周一9点。"
        "重要：用户说'每天'时 day_of_week 必须用 *，不要自作主张改为工作日 1-5。"
        "发送目标由系统自动确定（私聊→发给自己，群聊→发到本群），无需指定。",
        {
            "type": "object",
            "properties": {
                "cron": {
                    "type": "string",
                    "description": "标准 cron 表达式（5段：分 时 日 月 周）。"
                                   "周的取值：0=周日,1=周一,...,6=周六。"
                                   "示例：'0 9 * * *'(每天9点), '0 9 * * 1-5'(工作日9点)。与 delay_minutes 二选一",
                },
                "delay_minutes": {
                    "type": "integer",
                    "description": "相对时间，N分钟后触发，执行后自动删除。与 cron 二选一",
                },
                "message": {
                    "type": "string",
                    "description": "简单提醒的固定文本内容。与 skill 二选一",
                },
                "skill": {
                    "type": "string",
                    "description": "要触发的技能名称。与 message 二选一",
                },
            },
            "required": [],
        },
    )
    async def cron_create(args: Dict[str, Any]) -> Dict[str, Any]:
        """创建定时任务"""
        from app.core.cron_service import cron_service

        ctx = captured_getter()

        conversation_id = ctx.get("conversation_id")
        if not conversation_id:
            return {
                "content": [{"type": "text", "text": json.dumps(
                    {"success": False, "message": "缺少对话上下文，请确保在正确的上下文中运行"},
                    ensure_ascii=False,
                )}],
                "is_error": True,
            }

        # cron 和 delay_minutes 互斥校验
        cron_arg = args.get("cron")
        delay_minutes = args.get("delay_minutes")
        if cron_arg and delay_minutes is not None:
            return {
                "content": [{"type": "text", "text": json.dumps(
                    {"success": False, "message": "cron 和 delay_minutes 不能同时指定，请选择其一：cron 用于周期任务，delay_minutes 用于一次性延迟任务"},
                    ensure_ascii=False,
                )}],
                "is_error": True,
            }

        # delay_minutes → 自动计算 cron
        if delay_minutes is not None:
            if delay_minutes < 1:
                return {
                    "content": [{"type": "text", "text": json.dumps(
                        {"success": False, "message": "delay_minutes 必须 >= 1"},
                        ensure_ascii=False,
                    )}],
                    "is_error": True,
                }
            now = datetime.now()
            target = now + timedelta(minutes=delay_minutes)
            cron_expr = f"{target.minute} {target.hour} {target.day} {target.month} *"
            delete_after_run = True  # 延迟任务自动一次性
        else:
            # 验证 cron 表达式
            cron_expr = args.get("cron", "")
            parts = cron_expr.split()
            if len(parts) != 5:
                return {
                    "content": [{"type": "text", "text": json.dumps(
                        {"success": False, "message": "Cron 表达式格式错误，需要5段：分 时 日 月 周"},
                        ensure_ascii=False,
                    )}],
                    "is_error": True,
                }

        # 验证 message 和 skill 二选一
        has_message = bool(args.get("message", "").strip()) if args.get("message") else False
        has_skill = bool(args.get("skill", "").strip()) if args.get("skill") else False

        if not has_message and not has_skill:
            return {
                "content": [{"type": "text", "text": json.dumps(
                    {"success": False, "message": "必须指定 message 或 skill"},
                    ensure_ascii=False,
                )}],
                "is_error": True,
            }

        if has_message and has_skill:
            return {
                "content": [{"type": "text", "text": json.dumps(
                    {"success": False, "message": "message 和 skill 不能同时指定，请选择其一"},
                    ensure_ascii=False,
                )}],
                "is_error": True,
            }

        # 校验一次性任务的 cron 时间是否已过期（delay_minutes 路径跳过，时间由系统计算）
        if delay_minutes is None:
            minute, hour, day, month, weekday = parts
            # 自动判断：day 和 month 都是具体值 → 一次性任务，否则为周期性任务
            delete_after_run = (day != "*" and month != "*")
            if day != "*" and month != "*":
                try:
                    now = datetime.now()
                    scheduled = datetime(
                        year=now.year,
                        month=int(month),
                        day=int(day),
                        hour=int(hour) if hour != "*" else 0,
                        minute=int(minute) if minute != "*" else 0,
                    )
                    if scheduled < now:
                        return {
                            "content": [{"type": "text", "text": json.dumps(
                                {
                                    "success": False,
                                    "message": f"定时任务时间已过期！当前服务器时间是 {now.strftime('%Y-%m-%d %H:%M:%S')}，请重新计算 cron 表达式。",
                                    "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                                },
                                ensure_ascii=False,
                            )}],
                            "is_error": True,
                        }
                except ValueError as e:
                    return {
                        "content": [{"type": "text", "text": json.dumps(
                            {"success": False, "message": f"Cron 表达式解析失败: {e}"},
                            ensure_ascii=False,
                        )}],
                        "is_error": True,
                    }

        # 自动推导场景
        is_group = ctx.get("is_group", False)
        user_name = ctx.get("user_name", "用户")

        job_config = {
            "id": f"job-{uuid.uuid4().hex[:8]}",
            "cron": cron_expr,
            "channel": ctx.get("channel", "wecom"),
            "context_type": "group" if is_group else "private",
            "target_type": "group" if is_group else "self",
            "owner_conversation_id": conversation_id,
            "owner_name": user_name,
            "target_conversation_id": conversation_id,
            "target_name": ctx.get("group_chat_name") if is_group else user_name,
            "user_token": ctx.get("user_token"),
            "created_at": datetime.now().isoformat(),
            "enabled": True,
            "delete_after_run": delete_after_run,
        }

        # message / skill 二选一
        if has_message:
            job_config["message"] = args["message"]
        else:
            # 防御路径转换：提取最后一段作为 skill 名称
            skill_name = args["skill"].strip().rstrip("/")
            skill_name = skill_name.split("/")[-1]
            job_config["skill"] = skill_name

        # 群聊额外字段
        if is_group:
            job_config["group_conversation_id"] = conversation_id
            job_config["group_name"] = ctx.get("group_chat_name", "")

        success = await cron_service.add_job_live(job_config)

        if success:
            schedule_desc = cron_to_chinese(cron_expr)
            result = {
                "success": True,
                "job_id": job_config["id"],
                "schedule": schedule_desc,
                "one_time": delete_after_run,
                "message": "定时任务创建成功",
                "note": "向用户确认时用自然语言描述执行时间即可，禁止提及 job_id、skill 名称等内部标识。",
            }
        else:
            result = {
                "success": False,
                "message": "任务创建失败，请检查 cron 表达式是否正确",
            }

        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    @tool(
        "cron_list",
        "查看当前用户的所有定时任务。返回任务列表，包含任务内容、执行时间等信息。",
        {},
    )
    async def cron_list(args: Dict[str, Any]) -> Dict[str, Any]:
        """查看当前用户的定时任务"""
        from app.core.cron_service import cron_service

        ctx = captured_getter()
        conversation_id = ctx.get("conversation_id")

        if not conversation_id:
            return {
                "content": [{"type": "text", "text": json.dumps(
                    {"success": False, "message": "缺少对话上下文"},
                    ensure_ascii=False,
                )}],
                "is_error": True,
            }

        user_jobs = cron_service.list_user_jobs(conversation_id)

        if not user_jobs:
            result = {
                "success": True,
                "jobs": [],
                "message": "您还没有创建任何定时任务",
            }
        else:
            formatted_jobs = []
            for job in user_jobs:
                message = job.get("message")
                skill = job.get("skill") or job.get("command")

                formatted_job = {
                    "id": job["id"],
                    "cron": job["cron"],
                    "cron_desc": cron_to_chinese(job["cron"]),
                    "task_type": "message" if message else "skill",
                    "task_content": message if message else skill,
                    "target": job.get("target_name", "自己"),
                    "context_type": job.get("context_type", "private"),
                    "created_at": job.get("created_at", ""),
                }

                if job.get("end_date"):
                    formatted_job["end_date"] = job["end_date"]
                if job.get("delete_after_run"):
                    formatted_job["delete_after_run"] = True

                formatted_jobs.append(formatted_job)

            result = {
                "success": True,
                "jobs": formatted_jobs,
                "message": f"找到 {len(formatted_jobs)} 个定时任务",
            }

        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    @tool(
        "cron_delete",
        "删除指定的定时任务。",
        {"job_id": str},
    )
    async def cron_delete(args: Dict[str, Any]) -> Dict[str, Any]:
        """删除定时任务"""
        from app.core.cron_service import cron_service

        job_id = args.get("job_id", "")
        if not job_id:
            return {
                "content": [{"type": "text", "text": json.dumps(
                    {"success": False, "message": "job_id 参数不能为空"},
                    ensure_ascii=False,
                )}],
                "is_error": True,
            }

        success = await cron_service.remove_job(job_id)

        if success:
            result = {"success": True, "message": "定时任务已删除"}
        else:
            result = {"success": False, "message": f"未找到任务: {job_id}"}

        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    return create_sdk_mcp_server(
        name="cron-mgr",
        version="1.0.0",
        tools=[cron_get_time, cron_create, cron_list, cron_delete],
    )
