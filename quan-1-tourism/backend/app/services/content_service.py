import asyncio
import hashlib
import random
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import db
from app.models.domain import AudioAsset, ContentLocalization, ContentVersion, QueueOutbox, WorkflowTask
from app.models.poi import POIRecord
from app.providers.ai.adapter import AIAdapter
from app.providers.translation.adapter import TranslationAdapter
from app.providers.tts.adapter import TTSAdapter
from app.providers.wikipedia.adapter import WikipediaAdapter
from app.repositories.poi_repository import POIRepository
from app.services.runtime_store import store


def _time(value):
    return value.isoformat() if value else None


def _serialize_content(item):
    if isinstance(item, dict):
        return item
    return {"id": item.id, "poi_id": item.poi_id, "version": item.version, "status": item.status, "source_url": item.source_url, "source_revision": item.source_revision, "source_snapshot": item.source_snapshot, "input_hash": item.input_hash, "script_vi": item.script_vi, "script_en": item.script_en, "ai_model": item.ai_model, "prompt_version": item.prompt_version, "review_note": item.review_note, "created_at": _time(item.created_at), "approved_at": _time(item.approved_at), "published_at": _time(item.published_at)}


def _serialize_task(item):
    if isinstance(item, dict):
        return item
    return {"id": item.id, "poi_id": item.poi_id, "content_version_id": item.content_version_id, "task_type": item.task_type, "status": item.status, "current_step": item.current_step, "attempts": item.attempts, "max_attempts": item.max_attempts, "error_message": item.error_message, "created_at": _time(item.created_at), "updated_at": _time(item.updated_at)}


async def create_task(
    poi_id: str,
    task_type: str,
    actor_id: str,
    idempotency_key: str | None = None,
    content_version_id: str | None = None,
) -> str:
    idempotency_key = idempotency_key or str(uuid4())
    task_id = str(uuid4())
    row = {"id": task_id, "poi_id": poi_id, "content_version_id": content_version_id, "task_type": task_type, "status": "PENDING", "current_step": "QUEUED", "attempts": 0, "max_attempts": 3, "error_message": None, "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(), "actor_id": actor_id, "idempotency_key": idempotency_key}
    if db.session_factory is None:
        existing = next((task for task in store.tasks.values() if task.get("idempotency_key") == idempotency_key), None)
        if existing:
            matches = (existing["poi_id"], existing["task_type"], existing.get("actor_id")) == (poi_id, task_type, actor_id)
            matches = matches and (content_version_id is None or existing.get("content_version_id") == content_version_id)
            if not matches:
                raise ValueError("Idempotency-Key was already used for a different task")
            return existing["id"]
        store.tasks[task_id] = row
    else:
        async with db.session_factory() as session:
            existing = await session.scalar(select(WorkflowTask).where(WorkflowTask.idempotency_key == idempotency_key))
            if existing:
                matches = (existing.poi_id, existing.task_type, existing.requested_by) == (poi_id, task_type, actor_id)
                matches = matches and (content_version_id is None or existing.content_version_id == content_version_id)
                if not matches:
                    raise ValueError("Idempotency-Key was already used for a different task")
                return existing.id
            session.add(WorkflowTask(id=task_id, poi_id=poi_id, task_type=task_type, requested_by=actor_id, content_version_id=content_version_id, idempotency_key=idempotency_key))
            if settings.REDIS_ENABLED:
                session.add(QueueOutbox(task_id=task_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(select(WorkflowTask).where(WorkflowTask.idempotency_key == idempotency_key))
                if existing:
                    matches = (existing.poi_id, existing.task_type, existing.requested_by) == (poi_id, task_type, actor_id)
                    matches = matches and (content_version_id is None or existing.content_version_id == content_version_id)
                    if not matches:
                        raise ValueError("Idempotency-Key was already used for a different task")
                    return existing.id
                raise
    return task_id


async def find_task_by_idempotency_key(idempotency_key: str | None) -> dict | None:
    if not idempotency_key:
        return None
    if db.session_factory is None:
        task = next((task for task in store.tasks.values() if task.get("idempotency_key") == idempotency_key), None)
        if task is None:
            return None
        return {**task, "requested_by": task.get("actor_id")}
    async with db.session_factory() as session:
        task = await session.scalar(select(WorkflowTask).where(WorkflowTask.idempotency_key == idempotency_key))
        if task is None:
            return None
        return {
            "id": task.id,
            "poi_id": task.poi_id,
            "task_type": task.task_type,
            "content_version_id": task.content_version_id,
            "requested_by": task.requested_by,
            "status": task.status,
        }


def claim_local_task(task_id: str, task: dict | None) -> bool:
    if task is None or task.get("status") in {"COMPLETED", "FAILED"} or task_id in store.active_tasks:
        return False
    store.active_tasks.add(task_id)
    return True


async def run_local_task(task_id: str, poi_id: str, actor_id: str, task_type: str, content_id: str | None = None) -> None:
    try:
        if task_type == "CONTENT_GENERATION":
            await process_wikipedia_generation(task_id, poi_id, actor_id)
        elif task_type == "LOCALIZATION_TTS" and content_id:
            await process_localization_audio(task_id, content_id)
        else:
            await update_task(task_id, status="FAILED", current_step="FAILED", error_message="Unsupported workflow task")
    finally:
        store.active_tasks.discard(task_id)


async def dispatch_task(task_id: str) -> bool:
    """Publish a persisted task; the outbox makes a Redis outage recoverable."""
    if db.redis_pool is None or db.session_factory is None:
        return False
    async with db.session_factory() as session:
        outbox = await session.get(QueueOutbox, task_id)
        task = await session.get(WorkflowTask, task_id)
        if not outbox or not task:
            return False
        if task.status in {"COMPLETED", "FAILED"}:
            return True
        if outbox.published_at:
            return True
        try:
            await db.redis_pool.enqueue_job(
                "process_workflow_task", task_id,
                _job_id=f"q1-task:{task_id}:dispatch:{outbox.attempts + 1}",
            )
            outbox.published_at = datetime.now(timezone.utc)
            outbox.attempts += 1
            outbox.last_error = None
            await session.commit()
            return True
        except Exception as exc:
            outbox.attempts += 1
            outbox.last_error = str(exc)[:2000]
            await session.commit()
            return False


async def update_task(task_id: str, **changes):
    if db.session_factory is None:
        task = store.tasks.get(task_id)
        if task:
            task.update(changes)
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
        return
    async with db.session_factory() as session:
        task = await session.get(WorkflowTask, task_id)
        if task:
            for key, value in changes.items():
                setattr(task, key, value)
            if changes.get("status") in {"COMPLETED", "FAILED"}:
                task.lease_until = None
                task.worker_id = None
                task.next_run_at = None
            await session.commit()


async def get_task(task_id: str):
    if db.session_factory is None:
        return store.tasks.get(task_id)
    async with db.session_factory() as session:
        task = await session.get(WorkflowTask, task_id)
        return _serialize_task(task) if task else None


async def list_tasks(limit: int = 100):
    if db.session_factory is None:
        return sorted(store.tasks.values(), key=lambda item: item["created_at"], reverse=True)[:limit]
    async with db.session_factory() as session:
        rows = await session.scalars(select(WorkflowTask).order_by(WorkflowTask.created_at.desc()).limit(limit))
        return [_serialize_task(row) for row in rows.all()]


async def list_contents(poi_id: str | None = None):
    if db.session_factory is None:
        rows = list(store.contents.values())
        if poi_id:
            rows = [row for row in rows if row["poi_id"] == poi_id]
        return sorted(rows, key=lambda row: row["version"], reverse=True)
    async with db.session_factory() as session:
        query = select(ContentVersion).order_by(ContentVersion.created_at.desc())
        if poi_id:
            query = query.where(ContentVersion.poi_id == poi_id)
        rows = await session.scalars(query.limit(200))
        return [_serialize_content(row) for row in rows.all()]


async def get_content(content_id: str):
    if db.session_factory is None:
        return store.contents.get(content_id)
    async with db.session_factory() as session:
        content = await session.get(ContentVersion, content_id)
        return _serialize_content(content) if content else None


async def _write_generated_content(task_id: str, poi: dict, wiki: dict, script: str, ai_model: str, actor_id: str):
    content_id = str(uuid4())
    input_hash = hashlib.sha256((wiki.get("extract", "") + "\0prompt-v1").encode()).hexdigest()
    if db.session_factory is None:
        version = max((item["version"] for item in store.contents.values() if item["poi_id"] == poi["id"]), default=0) + 1
        content = {"id": content_id, "poi_id": poi["id"], "version": version, "status": "IN_REVIEW", "source_url": wiki["url"], "source_revision": str(wiki.get("revision") or ""), "source_snapshot": wiki.get("extract", ""), "input_hash": input_hash, "script_vi": script, "script_en": None, "ai_model": ai_model, "prompt_version": "v1", "review_note": None, "created_at": datetime.now(timezone.utc).isoformat(), "approved_at": None, "published_at": None}
        store.contents[content_id] = content
        store.localizations[content_id] = {"vi-VN": script}
        store.tasks[task_id]["content_version_id"] = content_id
        return
    async with db.session_factory() as session:
        next_version = (await session.scalar(select(func.max(ContentVersion.version)).where(ContentVersion.poi_id == poi["id"])) or 0) + 1
        session.add(ContentVersion(id=content_id, poi_id=poi["id"], version=next_version, status="IN_REVIEW", source_url=wiki["url"], source_revision=str(wiki.get("revision") or ""), source_snapshot=wiki.get("extract", ""), input_hash=input_hash, script_vi=script, ai_model=ai_model, prompt_version="v1", created_by=actor_id))
        session.add(ContentLocalization(id=str(uuid4()), content_version_id=content_id, locale="vi-VN", script=script))
        task = await session.get(WorkflowTask, task_id)
        if task:
            task.content_version_id = content_id
        await session.commit()


async def process_wikipedia_generation(task_id: str, poi_id: str, actor_id: str):
    await update_task(task_id, status="PROCESSING", current_step="WIKIPEDIA_SYNC")
    for attempt in range(1, 4):
        await update_task(task_id, attempts=attempt, status="PROCESSING", current_step="WIKIPEDIA_SYNC", error_message=None)
        try:
            if db.session_factory is None:
                poi = store.pois.get(poi_id)
            else:
                async with db.session_factory() as session:
                    poi = await POIRepository(session).get_by_id(poi_id)
            if poi is None:
                raise ValueError("Không tìm thấy POI")
            source = (poi.get("source_ref") or {}).get("url")
            if not source:
                raise ValueError("POI chưa cấu hình nguồn Wikipedia")
            wiki = await WikipediaAdapter().fetch_article_text(source)
            await update_task(task_id, current_step="AI_DRAFT")
            script, model = await AIAdapter().draft_narration(poi["title"], wiki["extract"])
            await update_task(task_id, current_step="SAVE_REVIEW_DRAFT")
            await _write_generated_content(task_id, poi, wiki, script, model, actor_id)
            await update_task(task_id, status="COMPLETED", current_step="IN_REVIEW", error_message=None)
            return
        except Exception as exc:
            if attempt == 3 or isinstance(exc, ValueError):
                await update_task(task_id, status="FAILED", current_step="FAILED", error_message=str(exc))
                return
            await update_task(task_id, status="RETRY_PENDING", current_step="RETRY_PENDING", error_message=str(exc))
            await asyncio.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))


async def recover_pending_tasks():
    # Distributed tasks belong to the ARQ worker. Running them in the API process
    # as well would bypass leases and could process the same task twice.
    if (settings.REDIS_ENABLED and db.redis_pool is not None) or db.session_factory is None:
        return
    async with db.session_factory() as session:
        rows = await session.scalars(select(WorkflowTask).where(WorkflowTask.status.in_(["PENDING", "PROCESSING", "RETRY_PENDING"])))
        pending = rows.all()
        for task in pending:
            task.status = "RETRY_PENDING"
            task.error_message = "Worker restarted; task resumed automatically"
        await session.commit()
        jobs = [(task.id, task.poi_id, task.requested_by, task.task_type, task.content_version_id) for task in pending]
    for task_id, poi_id, actor_id, task_type, content_id in jobs:
        if task_type == "CONTENT_GENERATION":
            asyncio.create_task(process_wikipedia_generation(task_id, poi_id, actor_id or ""))
        elif task_type == "LOCALIZATION_TTS" and content_id:
            asyncio.create_task(process_localization_audio(task_id, content_id))


async def update_draft(content_id: str, script_vi: str, review_note: str | None, actor_id: str):
    if db.session_factory is None:
        content = store.contents.get(content_id)
        if not content or content["status"] != "IN_REVIEW":
            return None
        content.update({"script_vi": script_vi, "review_note": review_note})
        store.localizations[content_id]["vi-VN"] = script_vi
        return content
    async with db.session_factory() as session:
        content = await session.get(ContentVersion, content_id)
        if not content or content.status != "IN_REVIEW":
            return None
        content.script_vi, content.review_note, content.reviewed_by = script_vi, review_note, actor_id
        localization = await session.scalar(select(ContentLocalization).where(ContentLocalization.content_version_id == content_id, ContentLocalization.locale == "vi-VN"))
        if localization:
            localization.script = script_vi
        else:
            session.add(ContentLocalization(id=str(uuid4()), content_version_id=content_id, locale="vi-VN", script=script_vi))
        await session.commit()
        await session.refresh(content)
        return _serialize_content(content)


async def approve_content(content_id: str, actor_id: str):
    now = datetime.now(timezone.utc)
    if db.session_factory is None:
        content = store.contents.get(content_id)
        if not content or content["status"] != "IN_REVIEW":
            return None
        content.update({"status": "APPROVED", "approved_at": now.isoformat(), "reviewed_by": actor_id})
        return content
    async with db.session_factory() as session:
        content = await session.get(ContentVersion, content_id)
        if not content or content.status != "IN_REVIEW":
            return None
        content.status, content.approved_at, content.reviewed_by = "APPROVED", now, actor_id
        await session.commit()
        await session.refresh(content)
        return _serialize_content(content)


async def save_localization(content_id: str, locale: str, script: str):
    if db.session_factory is None:
        content = store.contents.get(content_id)
        if not content or content["status"] not in {"APPROVED", "LOCALIZED"}:
            return None
        store.localizations.setdefault(content_id, {})[locale] = script
        content["status"] = "LOCALIZED"
        return content
    async with db.session_factory() as session:
        content = await session.get(ContentVersion, content_id)
        if not content or content.status not in {"APPROVED", "LOCALIZED"}:
            return None
        localization = await session.scalar(select(ContentLocalization).where(ContentLocalization.content_version_id == content_id, ContentLocalization.locale == locale))
        if localization:
            localization.script = script
        else:
            session.add(ContentLocalization(id=str(uuid4()), content_version_id=content_id, locale=locale, script=script))
        if locale == "en-US":
            content.script_en = script
        content.status = "LOCALIZED"
        await session.commit()
        await session.refresh(content)
        return _serialize_content(content)


async def localizations_for(content_id: str) -> dict[str, str]:
    if db.session_factory is None:
        return store.localizations.get(content_id, {})
    async with db.session_factory() as session:
        rows = await session.scalars(select(ContentLocalization).where(ContentLocalization.content_version_id == content_id))
        return {row.locale: row.script for row in rows.all()}


async def audio_for(content_id: str) -> dict[str, dict]:
    if db.session_factory is None:
        return store.audio.get(content_id, {})
    async with db.session_factory() as session:
        rows = await session.scalars(select(AudioAsset).where(AudioAsset.content_version_id == content_id))
        return {row.locale: {"audio_url": row.audio_url, "checksum": row.checksum, "voice": row.voice} for row in rows.all()}


async def process_localization_audio(task_id: str, content_id: str):
    for attempt in range(1, 4):
        await update_task(task_id, status="PROCESSING", current_step="LOCALIZATION", attempts=attempt, error_message=None)
        try:
            await _process_localization_audio_once(task_id, content_id)
            if db.session_factory is None:
                store.contents[content_id]["status"] = "AUDIO_READY"
            else:
                async with db.session_factory() as session:
                    row = await session.get(ContentVersion, content_id)
                    row.status = "AUDIO_READY"
                    await session.commit()
            await update_task(task_id, status="COMPLETED", current_step="AUDIO_READY", error_message=None)
            return
        except Exception as exc:
            retryable = isinstance(exc, httpx.RequestError) or isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500)
            if not retryable or attempt == 3:
                await update_task(task_id, status="FAILED", current_step="FAILED", error_message=str(exc))
                return
            await update_task(task_id, status="RETRY_PENDING", current_step="RETRY_PENDING", error_message=str(exc))
            await asyncio.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))


async def _process_localization_audio_once(task_id: str, content_id: str):
    content = await get_content(content_id)
    if not content or content["status"] not in {"APPROVED", "LOCALIZED"}:
        raise ValueError("Chỉ có thể xử lý nội dung đã được duyệt")
    scripts = await localizations_for(content_id)
    if "en-US" not in scripts:
        translated = await TranslationAdapter().translate_to_english(content["script_vi"])
        await save_localization(content_id, "en-US", translated)
        scripts["en-US"] = translated
    scripts.setdefault("vi-VN", content["script_vi"])
    await update_task(task_id, current_step="TTS_GENERATION")
    for locale in ("vi-VN", "en-US"):
        asset = await TTSAdapter().synthesize(scripts[locale], locale)
        if db.session_factory is None:
            store.audio.setdefault(content_id, {})[locale] = asset
        else:
            async with db.session_factory() as session:
                existing = await session.scalar(select(AudioAsset).where(AudioAsset.content_version_id == content_id, AudioAsset.locale == locale, AudioAsset.voice == asset["voice"]))
                if existing:
                    existing.audio_url, existing.checksum = asset["audio_url"], asset["checksum"]
                else:
                    session.add(AudioAsset(id=str(uuid4()), content_version_id=content_id, locale=locale, voice=asset["voice"], audio_url=asset["audio_url"], checksum=asset["checksum"]))
                await session.commit()


async def publish_content(content_id: str):
    content = await get_content(content_id)
    if not content or content["status"] != "AUDIO_READY":
        return None, "Nội dung cần có trạng thái AUDIO_READY trước khi xuất bản"
    scripts, assets = await localizations_for(content_id), await audio_for(content_id)
    if not {"vi-VN", "en-US"}.issubset(scripts) or not {"vi-VN", "en-US"}.issubset(assets):
        return None, "Cần đủ bản dịch và audio tiếng Việt, tiếng Anh"
    now = datetime.now(timezone.utc)
    if db.session_factory is None:
        store.contents[content_id].update({"status": "PUBLISHED", "published_at": now.isoformat()})
        poi = store.pois.get(content["poi_id"])
        poi.update({"summary_vi": scripts["vi-VN"], "summary_en": scripts["en-US"], "status": "PUBLISHED", "audio": assets})
        return store.contents[content_id], None
    async with db.session_factory() as session:
        row = await session.get(ContentVersion, content_id)
        poi = await session.get(POIRecord, row.poi_id)
        row.status, row.published_at = "PUBLISHED", now
        poi.summary_vi, poi.summary_en, poi.status = scripts["vi-VN"], scripts["en-US"], "PUBLISHED"
        await session.commit()
        await session.refresh(row)
        return _serialize_content(row), None


async def unpublish_poi(poi_id: str):
    if db.session_factory is None:
        poi = store.pois.get(poi_id)
        if not poi:
            return False
        poi["status"] = "APPROVED"
        for content in store.contents.values():
            if content["poi_id"] == poi_id and content["status"] == "PUBLISHED":
                content["status"] = "UNPUBLISHED"
        return True
    async with db.session_factory() as session:
        poi = await session.get(POIRecord, poi_id)
        if not poi:
            return False
        poi.status = "APPROVED"
        rows = await session.scalars(select(ContentVersion).where(ContentVersion.poi_id == poi_id, ContentVersion.status == "PUBLISHED"))
        for row in rows.all():
            row.status = "UNPUBLISHED"
        await session.commit()
        return True
