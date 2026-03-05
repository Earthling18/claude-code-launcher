"""
数据看板指标采集器

单例模式，fire-and-forget 异步写入 SQLite，失败只 log 不阻塞业务。
WAL 模式保证读写并发性能。
"""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

# SQLite 建表语句
_INIT_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS request_events (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    date TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT DEFAULT '',
    query_text TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER DEFAULT 0,
    status TEXT DEFAULT 'started',
    error_message TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS skill_events (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    date TEXT NOT NULL,
    user_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    request_event_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_events (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    date TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT DEFAULT '',
    event_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cron_events (
    id TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    date TEXT NOT NULL,
    job_id TEXT NOT NULL,
    job_type TEXT DEFAULT '',
    status TEXT DEFAULT 'completed',
    error_message TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_request_date ON request_events(date);
CREATE INDEX IF NOT EXISTS idx_request_user ON request_events(user_id);
CREATE INDEX IF NOT EXISTS idx_skill_date ON skill_events(date);
CREATE INDEX IF NOT EXISTS idx_session_date ON session_events(date);
CREATE INDEX IF NOT EXISTS idx_cron_date ON cron_events(date);
"""


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> float:
    return time.time()


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class MetricsCollector:
    """指标采集器单例"""

    def __init__(self):
        self._db: Optional[aiosqlite.Connection] = None
        self._db_path = settings.dashboard_db_path
        self._started = False
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动采集器"""
        if not settings.dashboard_enabled:
            logger.info("[METRICS] Dashboard disabled, skipping metrics collector")
            return

        db_path = Path(self._db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._db = await aiosqlite.connect(str(db_path))
        await self._db.executescript(_INIT_SQL)
        await self._db.commit()

        self._started = True
        self._writer_task = asyncio.create_task(self._write_loop())
        logger.info(f"[METRICS] Started, db={db_path}")

    async def stop(self):
        """停止采集器"""
        self._started = False
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        # drain remaining items
        await self._drain_queue()
        if self._db:
            await self._db.close()
            self._db = None
        logger.info("[METRICS] Stopped")

    async def _write_loop(self):
        """后台写入循环"""
        while self._started:
            try:
                sql, params = await asyncio.wait_for(
                    self._write_queue.get(), timeout=5.0
                )
                await self._execute(sql, params)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[METRICS] Write loop error: {e}")

    async def _drain_queue(self):
        """清空队列中剩余的写入"""
        while not self._write_queue.empty():
            try:
                sql, params = self._write_queue.get_nowait()
                await self._execute(sql, params)
            except Exception:
                break

    async def _execute(self, sql: str, params: tuple):
        """执行 SQL"""
        if not self._db:
            return
        try:
            await self._db.execute(sql, params)
            await self._db.commit()
        except Exception as e:
            logger.warning(f"[METRICS] SQL error: {e}")

    def _enqueue(self, sql: str, params: tuple):
        """Fire-and-forget 入队"""
        if not self._started:
            return
        try:
            self._write_queue.put_nowait((sql, params))
        except asyncio.QueueFull:
            logger.warning("[METRICS] Write queue full, dropping metric")

    # ---- 采集接口 ----

    def record_request_start(
        self, user_id: str, user_name: str = "", query_text: str = ""
    ) -> str:
        """记录请求开始，返回 event_id"""
        event_id = _gen_id()
        self._enqueue(
            "INSERT INTO request_events (id, timestamp, date, user_id, user_name, query_text, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'started')",
            (event_id, _now(), _today(), user_id, user_name, query_text[:200]),
        )
        return event_id

    def record_request_complete(
        self,
        event_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
    ):
        """记录请求完成"""
        self._enqueue(
            "UPDATE request_events SET status='completed', "
            "input_tokens=?, output_tokens=?, cost_usd=?, duration_ms=? "
            "WHERE id=?",
            (input_tokens, output_tokens, cost_usd, duration_ms, event_id),
        )

    def record_request_error(self, event_id: str, error_message: str = ""):
        """记录请求错误"""
        self._enqueue(
            "UPDATE request_events SET status='error', error_message=? WHERE id=?",
            (error_message[:500], event_id),
        )

    def record_skill(
        self, user_id: str, skill_name: str, request_event_id: str = ""
    ):
        """记录技能调用"""
        self._enqueue(
            "INSERT INTO skill_events (id, timestamp, date, user_id, skill_name, request_event_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_gen_id(), _now(), _today(), user_id, skill_name, request_event_id),
        )

    def record_session_event(
        self, user_id: str, event_type: str, user_name: str = ""
    ):
        """记录会话事件 (created/destroyed/expired)"""
        self._enqueue(
            "INSERT INTO session_events (id, timestamp, date, user_id, user_name, event_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_gen_id(), _now(), _today(), user_id, user_name, event_type),
        )

    def record_cron_event(
        self, job_id: str, job_type: str = "", status: str = "completed",
        error_message: str = ""
    ):
        """记录定时任务执行"""
        self._enqueue(
            "INSERT INTO cron_events (id, timestamp, date, job_id, job_type, status, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_gen_id(), _now(), _today(), job_id, job_type, status, error_message),
        )

    # ---- 查询接口 ----

    async def _query(self, sql: str, params: tuple = ()) -> list:
        """查询并返回字典列表"""
        if not self._db:
            return []
        try:
            self._db.row_factory = aiosqlite.Row
            async with self._db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.warning(f"[METRICS] Query error: {e}")
            return []

    async def get_overview(self) -> dict:
        """获取概览数据（今日 + 近7天）"""
        today = _today()
        seven_days_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")

        # 今日数据
        today_requests = await self._query(
            "SELECT COUNT(*) as cnt, "
            "COALESCE(SUM(input_tokens), 0) as input_tokens, "
            "COALESCE(SUM(output_tokens), 0) as output_tokens, "
            "COALESCE(SUM(cost_usd), 0.0) as cost_usd "
            "FROM request_events WHERE date=?", (today,)
        )
        today_sessions = await self._query(
            "SELECT COUNT(*) as cnt FROM session_events WHERE date=? AND event_type='created'",
            (today,)
        )
        today_users = await self._query(
            "SELECT COUNT(DISTINCT user_id) as cnt FROM request_events WHERE date=?",
            (today,)
        )
        today_skills = await self._query(
            "SELECT COUNT(*) as cnt FROM skill_events WHERE date=?", (today,)
        )

        # 近7天数据
        week_requests = await self._query(
            "SELECT COUNT(*) as cnt, "
            "COALESCE(SUM(input_tokens), 0) as input_tokens, "
            "COALESCE(SUM(output_tokens), 0) as output_tokens, "
            "COALESCE(SUM(cost_usd), 0.0) as cost_usd "
            "FROM request_events WHERE date>=?", (seven_days_ago,)
        )
        week_sessions = await self._query(
            "SELECT COUNT(*) as cnt FROM session_events WHERE date>=? AND event_type='created'",
            (seven_days_ago,)
        )
        week_users = await self._query(
            "SELECT COUNT(DISTINCT user_id) as cnt FROM request_events WHERE date>=?",
            (seven_days_ago,)
        )
        week_skills = await self._query(
            "SELECT COUNT(*) as cnt FROM skill_events WHERE date>=?",
            (seven_days_ago,)
        )

        tr = today_requests[0] if today_requests else {}
        wr = week_requests[0] if week_requests else {}

        return {
            "today": {
                "sessions": today_sessions[0]["cnt"] if today_sessions else 0,
                "requests": tr.get("cnt", 0),
                "input_tokens": tr.get("input_tokens", 0),
                "output_tokens": tr.get("output_tokens", 0),
                "cost_usd": round(tr.get("cost_usd", 0.0), 4),
                "active_users": today_users[0]["cnt"] if today_users else 0,
                "skills": today_skills[0]["cnt"] if today_skills else 0,
            },
            "week": {
                "sessions": week_sessions[0]["cnt"] if week_sessions else 0,
                "requests": wr.get("cnt", 0),
                "input_tokens": wr.get("input_tokens", 0),
                "output_tokens": wr.get("output_tokens", 0),
                "cost_usd": round(wr.get("cost_usd", 0.0), 4),
                "active_users": week_users[0]["cnt"] if week_users else 0,
                "skills": week_skills[0]["cnt"] if week_skills else 0,
            },
        }

    async def get_timeline(self) -> list:
        """获取近7天每日趋势"""
        seven_days_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        return await self._query(
            "SELECT date, COUNT(*) as requests, "
            "COALESCE(SUM(input_tokens), 0) as input_tokens, "
            "COALESCE(SUM(output_tokens), 0) as output_tokens "
            "FROM request_events WHERE date>=? "
            "GROUP BY date ORDER BY date",
            (seven_days_ago,),
        )

    async def get_top_users(self, limit: int = 5) -> list:
        """获取近7天活跃用户 Top N"""
        seven_days_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        return await self._query(
            "SELECT user_id, user_name, COUNT(*) as requests "
            "FROM request_events WHERE date>=? "
            "GROUP BY user_id ORDER BY requests DESC LIMIT ?",
            (seven_days_ago, limit),
        )

    async def get_skill_stats(self) -> list:
        """获取近7天技能排行"""
        seven_days_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        return await self._query(
            "SELECT skill_name, COUNT(*) as count "
            "FROM skill_events WHERE date>=? "
            "GROUP BY skill_name ORDER BY count DESC",
            (seven_days_ago,),
        )

    async def get_hourly_distribution(self) -> list:
        """获取近7天每小时请求分布"""
        seven_days_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
        rows = await self._query(
            "SELECT CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) as hour, "
            "COUNT(*) as count "
            "FROM request_events WHERE date>=? "
            "GROUP BY hour ORDER BY hour",
            (seven_days_ago,),
        )
        # 填充所有 24 小时
        hour_map = {r["hour"]: r["count"] for r in rows}
        return [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    async def get_recent_requests(self, limit: int = 20) -> list:
        """获取最近 N 条请求"""
        return await self._query(
            "SELECT id, timestamp, user_id, user_name, query_text, "
            "input_tokens, output_tokens, cost_usd, duration_ms, status, error_message "
            "FROM request_events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )


# 全局单例
metrics_collector = MetricsCollector()
