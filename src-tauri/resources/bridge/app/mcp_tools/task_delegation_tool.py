"""
任务委托自定义工具

提供 delegate_task 和 cancel_task 两个 MCP 工具，
让主 Agent 可以将长任务委托给独立的后台 WorkerSession 执行。

使用闭包捕获 context_getter，与 file_output_tool.py 同模式。
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict

from claude_agent_sdk import tool, create_sdk_mcp_server

from app.core.task_registry import task_registry, BackgroundTask, TaskStatus

logger = logging.getLogger(__name__)


def create_task_delegation_server(context_getter: Callable[[], Dict[str, Any]]):
    """
    创建任务委托 SDK MCP 服务器

    使用闭包捕获 context_getter，确保工具调用时能获取最新的用户上下文。

    Args:
        context_getter: 返回用户上下文 dict 的 callable
            必须包含: user_id, session_key, conversation_id, user_name,
                      group_chat_name, is_group, user_token, workspace

    Returns:
        SDK MCP 服务器配置
    """
    captured_getter = context_getter

    @tool(
        "delegate_task",
        "将耗时任务委派独立处理，完成后自动通知。description 必须自包含（worker 无对话历史），涉及 Skill 需注明名称。",
        {"task_type": str, "description": str},
    )
    async def delegate_task(args: Dict[str, Any]) -> Dict[str, Any]:
        """委托长任务给后台 WorkerSession"""
        from app.core.worker_session import WorkerSession

        ctx = captured_getter()
        user_id = ctx.get("user_id")
        if not user_id:
            return {
                "content": [{"type": "text", "text": "错误: 委托上下文未初始化"}],
                "is_error": True,
            }

        task_type = args.get("task_type", "general")
        description = args.get("description", "")

        if not description:
            return {
                "content": [{"type": "text", "text": "错误: description 参数不能为空"}],
                "is_error": True,
            }

        # 创建任务记录
        task_id = task_registry.generate_task_id(user_id)
        bg_task = BackgroundTask(
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            description=description,
        )
        task_registry.register(bg_task)

        # 构建 pusher 上下文（完整传递，保证单聊/群聊都能正确发送）
        pusher_context = {
            "conversation_id": ctx.get("conversation_id"),
            "user_name": ctx.get("user_name"),
            "group_chat_name": ctx.get("group_chat_name"),
            "is_group": ctx.get("is_group"),
            "user_token": ctx.get("user_token"),
            "workspace": ctx.get("workspace"),
            "channel": ctx.get("channel", "wecom"),
        }

        workspace = Path(ctx.get("workspace", "."))

        worker = WorkerSession(
            task=bg_task,
            workspace=workspace,
            pusher_context=pusher_context,
            notify_session_key=ctx.get("session_key", user_id),
        )

        # 启动后台 asyncio.Task
        asyncio_task = asyncio.create_task(worker.run())
        bg_task._asyncio_task = asyncio_task

        logger.info(f"[DELEGATE] Task {task_id} delegated: {task_type} - {description[:100]}")

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"已安排处理，完成后会将结果发给用户。",
                }
            ]
        }

    @tool(
        "cancel_task",
        "取消正在进行的任务。",
        {"task_id": str},
    )
    async def cancel_task(args: Dict[str, Any]) -> Dict[str, Any]:
        """取消后台任务"""
        task_id = args.get("task_id", "")
        if not task_id:
            return {
                "content": [{"type": "text", "text": "错误: task_id 参数不能为空"}],
                "is_error": True,
            }

        success = task_registry.cancel(task_id)
        status = "已取消" if success else "取消失败（任务不存在或已结束）"
        return {"content": [{"type": "text", "text": status}]}

    @tool(
        "query_task_status",
        "查询当前所有任务的详细状态和进度。当用户询问任务进展、想了解具体情况或考虑是否取消时使用。",
        {},
    )
    async def query_task_status(args: Dict[str, Any]) -> Dict[str, Any]:
        """查询委托任务详细状态"""
        ctx = captured_getter()
        user_id = ctx.get("user_id")
        if not user_id:
            return {
                "content": [{"type": "text", "text": "无法获取用户信息"}],
                "is_error": True,
            }

        all_tasks = task_registry.get_user_tasks(user_id)
        active = [t for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]

        if not active:
            return {"content": [{"type": "text", "text": "当前没有正在处理的任务。"}]}

        lines = []
        for t in active:
            elapsed = f"{t.elapsed_seconds:.0f}秒"
            desc = t.description[:100]
            line = f"  {t.task_type}，已运行{elapsed}，说明：{desc}"
            if t.progress_snapshot:
                line += f"（进展：{t.progress_snapshot}）"
            line += f"\n  [内部ID: {t.task_id}，用于取消]"
            lines.append(line)

        text = f"当前有{len(active)}个任务正在处理：\n\n" + "\n\n".join(lines)
        return {"content": [{"type": "text", "text": text}]}

    return create_sdk_mcp_server(
        name="task-mgr",
        version="1.0.0",
        tools=[delegate_task, cancel_task, query_task_status],
    )
