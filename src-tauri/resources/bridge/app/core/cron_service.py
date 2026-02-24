"""
定时任务服务 - 基于 APScheduler 的定时调度器

功能：
- 从 cron_jobs.json 加载任务配置
- APScheduler 定时触发
- 支持 message 直发（简单提醒）和 command 模式（复杂任务）
- 到期任务自动清理（end_date / delete_after_run）
- 风险控制：严格按照 context_type 发送

使用方式：
1. 通过 cron-manager Skill 创建任务（自然语言交互）
2. 或直接编辑 cron_jobs.json 配置文件
3. 服务启动时自动加载并调度任务
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# 配置文件路径
CRON_JOBS_FILE = Path("cron_jobs.json")


class CronService:
    """
    定时任务服务

    核心职责：
    - 加载和管理定时任务配置
    - 使用 APScheduler 调度任务执行
    - 支持 message 直发和 command 执行两种模式
    - 到期任务自动清理
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.jobs: Dict[str, dict] = {}
        self._started = False

    def _save_jobs(self, config: dict) -> None:
        """保存任务配置到文件"""
        CRON_JOBS_FILE.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"[CRON] Saved {len(config.get('jobs', []))} jobs to config file")

    async def _remove_job(self, job_id: str) -> bool:
        """
        从配置文件和调度器中删除任务

        Args:
            job_id: 任务ID

        Returns:
            是否删除成功
        """
        if not CRON_JOBS_FILE.exists():
            return False

        try:
            config = json.loads(CRON_JOBS_FILE.read_text(encoding="utf-8"))
            original_count = len(config.get("jobs", []))
            config["jobs"] = [j for j in config.get("jobs", []) if j["id"] != job_id]

            if len(config["jobs"]) < original_count:
                self._save_jobs(config)
                # 从调度器移除
                if job_id in self.jobs:
                    try:
                        self.scheduler.remove_job(job_id)
                    except Exception:
                        pass
                    del self.jobs[job_id]
                logger.info(f"[CRON] Removed job: {job_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"[CRON] Failed to remove job {job_id}: {e}")
            return False

    def load_jobs(self) -> None:
        """从配置文件加载任务（启动时清理过期任务）"""
        if not CRON_JOBS_FILE.exists():
            logger.info("[CRON] No cron_jobs.json found, skipping")
            return

        try:
            config = json.loads(CRON_JOBS_FILE.read_text(encoding="utf-8"))
            now = datetime.now()

            active_jobs = []
            expired_count = 0
            loaded_count = 0

            for job in config.get("jobs", []):
                # 检查是否已过期
                end_date = job.get("end_date")
                if end_date:
                    try:
                        if datetime.fromisoformat(end_date) < now:
                            expired_count += 1
                            logger.info(f"[CRON] Removing expired job: {job['id']} (end_date: {end_date})")
                            continue
                    except ValueError as e:
                        logger.warning(f"[CRON] Invalid end_date format for job {job['id']}: {e}")

                # 保留未过期的任务
                active_jobs.append(job)

                # 添加到调度器
                if job.get("enabled", True):
                    if self._add_job(job):
                        loaded_count += 1

            # 如果有过期任务被清理，保存更新后的配置
            if expired_count > 0:
                config["jobs"] = active_jobs
                self._save_jobs(config)
                logger.info(f"[CRON] Cleaned {expired_count} expired jobs")

            logger.info(f"[CRON] Loaded {loaded_count} jobs")
        except Exception as e:
            logger.error(f"[CRON] Failed to load jobs: {e}")

    def reload_jobs(self) -> int:
        """
        热重载任务配置

        Returns:
            加载的任务数量
        """
        # 清除现有任务
        for job_id in list(self.jobs.keys()):
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
        self.jobs.clear()

        # 重新加载
        self.load_jobs()
        return len(self.jobs)

    def _add_job(self, job_config: dict) -> bool:
        """
        添加单个任务到调度器

        Args:
            job_config: 任务配置

        Returns:
            是否添加成功
        """
        job_id = job_config.get("id")
        cron_expr = job_config.get("cron")

        if not job_id or not cron_expr:
            logger.error(f"[CRON] Invalid job config: missing id or cron")
            return False

        # 解析 cron 表达式（5 段格式：分 时 日 月 周）
        parts = cron_expr.split()
        if len(parts) != 5:
            logger.error(f"[CRON] Invalid cron expression: {cron_expr}")
            return False

        try:
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4]
            )

            # 添加有效期限制
            start_date = job_config.get("start_date")
            end_date = job_config.get("end_date")
            if start_date:
                trigger.start_date = datetime.fromisoformat(start_date)
            if end_date:
                trigger.end_date = datetime.fromisoformat(end_date)

            self.scheduler.add_job(
                self._execute_job,
                trigger,
                args=[job_config],
                id=job_id,
                replace_existing=True
            )

            self.jobs[job_id] = job_config
            # 显示 message 或 command
            task_desc = job_config.get("message", job_config.get("command", "N/A"))
            if task_desc and len(task_desc) > 30:
                task_desc = task_desc[:30] + "..."
            target_name = job_config.get("target_name", "N/A")
            logger.info(f"[CRON] Added job: {job_id} ({cron_expr}) -> {task_desc} -> {target_name}")
            return True

        except Exception as e:
            logger.error(f"[CRON] Failed to add job {job_id}: {e}")
            return False

    async def _execute_job(self, job_config: dict) -> None:
        """
        执行定时任务

        支持三种模式：
        - message 直发模式：简单提醒，直接发送固定文本
        - command 模式：复杂任务，调用 Agent 执行
        - skill 模式：触发指定的 Skill（转换为 /skill-name 格式）

        流程：
        1. 判断执行模式（message / command / skill）
        2. 获取响应内容
        3. 根据 target_type 推送结果
        4. 检查是否需要执行后删除
        """
        job_id = job_config.get("id", "unknown")
        message = job_config.get("message")
        command = job_config.get("command")
        skill = job_config.get("skill")  # 新增 skill 支持
        target_type = job_config.get("target_type", "self")
        owner_conversation_id = job_config.get("owner_conversation_id", "")
        owner_name = job_config.get("owner_name", "")
        target_conversation_id = job_config.get("target_conversation_id", "")
        target_name = job_config.get("target_name", "")

        logger.info(f"[CRON] Executing job: {job_id}")

        try:
            # 延迟导入避免循环依赖
            from app.services.proactive_messenger import proactive_messenger

            # 1. 判断执行模式并获取响应内容
            if message:
                # message 直发模式：简单提醒，不调用 Agent
                response_text = message
                task_label = "提醒"
                logger.info(f"[CRON] Direct message mode: {message[:50]}...")
            elif command or skill:
                # command/skill 模式：使用非阻塞 UserSession 架构（与正常聊天一致）
                from app.core.request_router import request_router
                from app.core.session_manager import session_manager
                from app.core.query_parser import ParsedQuery

                query = command if command else f"/{skill}"
                logger.info(f"[CRON] {'Command' if command else 'Skill'} mode (async): {query}")

                # 获取 workspace
                session = await session_manager.get_or_create(
                    user_id=owner_conversation_id,
                    user_name=owner_name
                )

                is_group = target_type == "group"
                user_token = job_config.get("user_token")
                parsed = ParsedQuery(text=query, files=[], has_text_item=True)

                await request_router.route_request_immediate_async(
                    user_id=owner_conversation_id,
                    parsed=parsed,
                    session_id=f"cron-{job_id}",
                    user_name=target_name,
                    user_token=user_token,
                    process_func=None,
                    async_context={
                        "conversation_id": target_conversation_id,
                        "user_name": target_name,
                        "group_chat_name": target_name if is_group else None,
                        "workspace": session.workspace,
                        "conversation_type": "GROUP" if is_group else "PRIVATE",
                    },
                )

                logger.info(f"[CRON] Job {job_id} dispatched to UserSession (async)")

                # 异步执行已启动，处理 delete_after_run 后直接返回
                if job_config.get("delete_after_run"):
                    removed = await self._remove_job(job_id)
                    if removed:
                        logger.info(f"[CRON] Removed one-time job after dispatch: {job_id}")
                return  # 跳过下面的 message 模式发送逻辑
            else:
                # 配置错误：既没有 message 也没有 command/skill
                logger.error(f"[CRON] Job {job_id} has neither message nor command/skill, skipping")
                return

            # 2. 直接使用响应内容（不添加固定前缀，更自然）
            formatted_response = response_text

            # 3. 发送结果（根据 target_type）
            # 使用 is_group 参数确保正确的 sendType（未命名群聊的 target_name 可能为空）
            if target_type == "group":
                await proactive_messenger.send_text(
                    content=formatted_response,
                    conversation_id=target_conversation_id,
                    group_chat_name=target_name,
                    is_group=True,
                )
                logger.info(f"[CRON] Job {job_id} message sent and confirmed to group: {target_name or '(未命名群聊)'}")
            else:
                await proactive_messenger.send_text(
                    content=formatted_response,
                    conversation_id=target_conversation_id,
                    user_name=target_name,
                    is_group=False,
                )
                logger.info(f"[CRON] Job {job_id} message sent and confirmed to user: {target_name}")

            logger.info(f"[CRON] Job {job_id} completed successfully")

            # 4. 检查是否需要执行后删除（一次性任务）
            if job_config.get("delete_after_run"):
                removed = await self._remove_job(job_id)
                if removed:
                    logger.info(f"[CRON] Removed one-time job after execution: {job_id}")

        except Exception as e:
            logger.error(f"[CRON] Job {job_id} failed: {e}")
            import traceback
            logger.error(f"[CRON] Traceback:\n{traceback.format_exc()}")

            # 尝试发送错误通知给任务创建者
            try:
                from app.services.proactive_messenger import proactive_messenger

                task_desc = message[:30] + "..." if message else command
                error_msg = f"定时任务「{task_desc}」执行遇到问题，稍后会自动重试。如持续失败请联系彦斌。"

                # 根据 context_type 判断发送方式
                context_type = job_config.get("context_type", "private")
                if context_type == "group":
                    # 群聊上下文：发到群里
                    group_conversation_id = job_config.get("group_conversation_id", owner_conversation_id)
                    group_name = job_config.get("group_name", "")
                    await proactive_messenger.send_text(
                        content=error_msg,
                        conversation_id=group_conversation_id,
                        group_chat_name=group_name,
                        is_group=True,
                    )
                else:
                    # 私聊上下文：发给用户
                    await proactive_messenger.send_text(
                        content=error_msg,
                        conversation_id=owner_conversation_id,
                        user_name=owner_name,
                        is_group=False,
                    )
            except Exception as notify_error:
                logger.error(f"[CRON] Failed to send error notification: {notify_error}")

    def get_job_info(self, job_id: str) -> Optional[dict]:
        """获取任务信息"""
        return self.jobs.get(job_id)

    def list_jobs(self) -> list:
        """列出所有任务"""
        return list(self.jobs.values())

    def start(self) -> None:
        """启动调度器"""
        if self._started:
            logger.warning("[CRON] Scheduler already started")
            return

        self.load_jobs()
        self.scheduler.start()
        self._started = True
        logger.info("[CRON] Scheduler started")

    def stop(self) -> None:
        """停止调度器"""
        if not self._started:
            return

        self.scheduler.shutdown(wait=False)
        self._started = False
        logger.info("[CRON] Scheduler stopped")


# 全局实例
cron_service = CronService()
