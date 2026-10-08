"""ARQ worker entry point. Run from backend with: arq app.worker.WorkerSettings"""
from datetime import datetime, time, timedelta, timezone
import socket
from uuid import uuid4

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import Date, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import close_db, connect_db, db
from app.core.security import bootstrap_admin
from app.models.domain import AnalyticsDailySummary, AnalyticsEvent, QueueOutbox, WorkflowTask
from app.services.content_service import process_localization_audio, process_wikipedia_generation

LEASE_MINUTES = 35


async def startup(ctx):
    await connect_db(connect_queue=False)
    await bootstrap_admin()
    ctx["worker_id"] = f"{socket.gethostname()}:{uuid4().hex[:8]}"
    await recover_expired_tasks(ctx)
    await relay_pending_outbox(ctx)


async def shutdown(ctx):
    await close_db()


async def process_workflow_task(ctx, task_id: str):
    now = datetime.now(timezone.utc)
    worker_id = ctx.get("worker_id", "arq-worker")
    if db.session_factory is None:
        raise RuntimeError("PostgreSQL is required by the distributed worker")

    async with db.session_factory() as session:
        claimed = await session.execute(
            update(WorkflowTask)
            .where(
                WorkflowTask.id == task_id,
                WorkflowTask.status.in_(["PENDING", "RETRY_PENDING", "PROCESSING"]),
                or_(WorkflowTask.lease_until.is_(None), WorkflowTask.lease_until <= now),
                or_(WorkflowTask.next_run_at.is_(None), WorkflowTask.next_run_at <= now),
            )
            .values(
                status="PROCESSING",
                current_step="CLAIMED",
                attempts=WorkflowTask.attempts + 1,
                lease_until=now + timedelta(minutes=LEASE_MINUTES),
                worker_id=worker_id,
                next_run_at=None,
                updated_at=now,
            )
            .returning(WorkflowTask.id)
        )
        if claimed.scalar_one_or_none() is None:
            return {"skipped": True, "reason": "task already claimed or finished"}
        task = await session.get(WorkflowTask, task_id)
        poi_id, actor_id, task_type, content_id = task.poi_id, task.requested_by, task.task_type, task.content_version_id

    try:
        if task_type == "CONTENT_GENERATION":
            await process_wikipedia_generation(task_id, poi_id, actor_id or "")
        elif task_type == "LOCALIZATION_TTS" and content_id:
            await process_localization_audio(task_id, content_id)
        else:
            raise ValueError(f"Unsupported workflow task: {task_type}")
    except Exception as exc:
        async with db.session_factory() as session:
            task = await session.get(WorkflowTask, task_id)
            if task:
                if task.attempts >= task.max_attempts:
                    task.status, task.current_step = "FAILED", "FAILED"
                else:
                    task.status, task.current_step = "RETRY_PENDING", "RETRY_PENDING"
                    delay = min(2 ** task.attempts, 300)
                    task.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                task.error_message = str(exc)[:4000]
                task.lease_until = None
                task.worker_id = None
                if task.status == "RETRY_PENDING":
                    outbox = await session.get(QueueOutbox, task_id)
                    if outbox:
                        outbox.published_at = None
                await session.commit()
        return {"task_id": task_id, "status": task.status if task else "missing"}
    finally:
        async with db.session_factory() as session:
            task = await session.get(WorkflowTask, task_id)
            if task and task.status in {"COMPLETED", "FAILED"}:
                task.lease_until = None
                task.worker_id = None
                task.next_run_at = None
                await session.commit()

    return {"task_id": task_id, "status": "processed"}


async def relay_pending_outbox(ctx):
    if db.session_factory is None:
        return
    async with db.session_factory() as session:
        rows = await session.execute(
            select(QueueOutbox, WorkflowTask)
            .join(WorkflowTask, WorkflowTask.id == QueueOutbox.task_id)
            .where(
                QueueOutbox.published_at.is_(None),
                WorkflowTask.status.in_(["PENDING", "RETRY_PENDING"]),
                or_(WorkflowTask.next_run_at.is_(None), WorkflowTask.next_run_at <= datetime.now(timezone.utc)),
            )
            .order_by(QueueOutbox.created_at)
            .limit(100)
        )
        pending = [(outbox, task) for outbox, task in rows.all()]
        for outbox, task in pending:
            try:
                await ctx["redis"].enqueue_job(
                    "process_workflow_task", task.id,
                    _job_id=f"q1-task:{task.id}:dispatch:{outbox.attempts + 1}",
                )
                outbox.published_at = datetime.now(timezone.utc)
                outbox.attempts += 1
                outbox.last_error = None
            except Exception as exc:
                outbox.attempts += 1
                outbox.last_error = str(exc)[:2000]
        if pending:
            await session.commit()


async def recover_expired_tasks(ctx):
    if db.session_factory is None:
        return
    now = datetime.now(timezone.utc)
    async with db.session_factory() as session:
        rows = await session.scalars(
            select(WorkflowTask).where(
                WorkflowTask.status == "PROCESSING",
                WorkflowTask.lease_until.is_not(None),
                WorkflowTask.lease_until <= now,
            ).order_by(WorkflowTask.created_at).limit(100)
        )
        candidates = rows.all()
        for task in candidates:
            if task.attempts >= task.max_attempts:
                task.status, task.current_step = "FAILED", "FAILED"
                task.error_message = task.error_message or "Task lease expired after maximum attempts"
                task.lease_until = None
                task.worker_id = None
                continue
            task.status = "RETRY_PENDING"
            task.lease_until = None
            task.worker_id = None
            task.next_run_at = now
            task.error_message = task.error_message or "Worker lease expired; task recovered"
            outbox = await session.get(QueueOutbox, task.id)
            if outbox:
                outbox.published_at = None
        if candidates:
            await session.commit()


async def aggregate_daily_analytics(ctx):
    if db.session_factory is None:
        return
    today = datetime.now(timezone.utc).date()
    first_day = today - timedelta(days=29)
    day_start = datetime.combine(first_day, time.min, timezone.utc)
    day_value = cast(func.timezone("UTC", AnalyticsEvent.created_at), Date)
    async with db.session_factory() as session:
        # Rebuild the small 30-day read model so revoked-consent events disappear
        # from summaries on the next aggregation run.
        await session.execute(delete(AnalyticsDailySummary).where(AnalyticsDailySummary.day >= first_day))
        rows = await session.execute(
            select(day_value, AnalyticsEvent.event_type, func.coalesce(AnalyticsEvent.poi_id, ""), func.count())
            .where(AnalyticsEvent.created_at >= day_start)
            .group_by(day_value, AnalyticsEvent.event_type, AnalyticsEvent.poi_id)
        )
        for day, event_type, poi_id, count in rows.all():
            stmt = pg_insert(AnalyticsDailySummary).values(
                id=str(uuid4()), day=day, event_type=event_type, poi_id=poi_id or "", event_count=count,
                updated_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_analytics_daily_summary_dimension",
                set_={"event_count": stmt.excluded.event_count, "updated_at": stmt.excluded.updated_at},
            )
            await session.execute(stmt)
        await session.commit()


async def prune_analytics(ctx):
    if db.session_factory is None:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    async with db.session_factory() as session:
        await session.execute(delete(AnalyticsEvent).where(AnalyticsEvent.created_at < cutoff))
        await session.execute(delete(AnalyticsDailySummary).where(AnalyticsDailySummary.day < cutoff.date()))
        await session.commit()


class WorkerSettings:
    functions = [process_workflow_task]
    cron_jobs = [
        cron(relay_pending_outbox, second={0}),
        cron(recover_expired_tasks, second={30}),
        cron(aggregate_daily_analytics, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(prune_analytics, hour={3}, minute={17}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 5
    max_tries = 3
    job_timeout = timedelta(minutes=LEASE_MINUTES)
