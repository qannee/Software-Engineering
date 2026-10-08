import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.security import authenticate, get_current_user, hash_password, issue_refresh_token, issue_token, require_admin, require_reviewer, revoke_refresh_token, revoke_token, rotate_refresh_token, write_audit
from app.models.domain import AdminUser, AnalyticsDailySummary, AnalyticsEvent, AuditLog
from app.repositories.poi_repository import POIRepository
from app.schemas.admin import AdminLogin, AdminUserCreate, DraftReview, LocalizationInput, POIPatch, POIUpsert, SourceRequest
from app.services.content_service import approve_content, claim_local_task, create_task, dispatch_task, find_task_by_idempotency_key, get_content, get_task, list_contents, list_tasks, localizations_for, publish_content, run_local_task, save_localization, unpublish_poi, update_draft
from app.services.runtime_store import store
from app.providers.wikipedia.adapter import WikipediaAdapter

router = APIRouter(prefix="/admin", tags=["Admin"])


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.APP_ENV.lower() == "production",
        samesite=settings.REFRESH_COOKIE_SAMESITE.lower(),
        path=f"{settings.API_V1_STR}/admin/auth",
    )


def _check_auth_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise HTTPException(status_code=403, detail="Origin is not allowed for admin authentication")


@router.post("/auth/login")
async def login(body: AdminLogin, response: Response, session: AsyncSession | None = Depends(get_session)):
    user = await authenticate(body.username, body.password, session)
    if user is None:
        await write_audit(session, {"id": None}, "auth.login.failed", "admin_user", details={"username": body.username})
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu không đúng")
    await write_audit(session, user, "auth.login.succeeded", "admin_user", user["id"], {"username": user["username"], "role": user["role"]})
    refresh_token = await issue_refresh_token(user, session)
    _set_refresh_cookie(response, refresh_token)
    return {"access_token": issue_token(user["id"], user["username"], user["role"]), "token_type": "bearer", "user": {"username": user["username"], "role": user["role"]}}


@router.post("/auth/refresh")
async def refresh_session(request: Request, response: Response, refresh_cookie: str | None = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME), session: AsyncSession | None = Depends(get_session)):
    _check_auth_origin(request)
    rotated = await rotate_refresh_token(refresh_cookie, session)
    if rotated is None:
        raise HTTPException(status_code=401, detail="Refresh session is invalid or expired")
    user, next_refresh = rotated
    _set_refresh_cookie(response, next_refresh)
    await write_audit(session, user, "auth.refresh", "admin_user", user["id"])
    return {"access_token": issue_token(user["id"], user["username"], user["role"]), "token_type": "bearer", "user": {"username": user["username"], "role": user["role"]}}


@router.get("/auth/me")
async def who_am_i(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"]}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, refresh_cookie: str | None = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME), session: AsyncSession | None = Depends(get_session), user: dict = Depends(get_current_user)):
    _check_auth_origin(request)
    await revoke_token(session, user)
    await revoke_refresh_token(refresh_cookie, session)
    response.delete_cookie(key=settings.REFRESH_COOKIE_NAME, path=f"{settings.API_V1_STR}/admin/auth", secure=settings.APP_ENV.lower() == "production", httponly=True, samesite=settings.REFRESH_COOKIE_SAMESITE.lower())
    await write_audit(session, user, "auth.logout", "admin_user", user["id"], {"username": user["username"]})
    return {"logged_out": True}


@router.get("/pois")
async def admin_pois(session: AsyncSession | None = Depends(get_session), _: dict = Depends(require_reviewer)):
    return {"data": await POIRepository(session).list_all()}


@router.post("/pois", status_code=status.HTTP_201_CREATED)
async def create_poi(body: POIUpsert, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    data = body.model_dump(mode="json")
    try:
        poi_id = await POIRepository(session).create(data)
    except IntegrityError as exc:
        if session:
            await session.rollback()
        raise HTTPException(status_code=409, detail="Slug đã được sử dụng") from exc
    await write_audit(session, user, "poi.create", "poi", poi_id, {"slug": data["slug"]})
    return {"id": poi_id, "status": "DRAFT"}


@router.patch("/pois/{poi_id}")
async def update_poi(poi_id: str, body: POIPatch, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "wikipedia_url" in changes and changes["wikipedia_url"]:
        try:
            WikipediaAdapter.parse_article(changes["wikipedia_url"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        poi = await POIRepository(session).update(poi_id, changes)
    except IntegrityError as exc:
        if session:
            await session.rollback()
        raise HTTPException(status_code=409, detail="Slug đã được sử dụng") from exc
    if poi is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy POI")
    await write_audit(session, user, "poi.update", "poi", poi_id, {"fields": list(changes)})
    return poi


@router.delete("/pois/{poi_id}", status_code=204)
async def delete_poi(poi_id: str, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    if not await POIRepository(session).delete(poi_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy POI")
    await write_audit(session, user, "poi.delete", "poi", poi_id)


@router.put("/pois/{poi_id}/source")
async def set_wikipedia_source(poi_id: str, body: SourceRequest, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    url = str(body.wikipedia_url)
    try:
        WikipediaAdapter.parse_article(url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    poi = await POIRepository(session).update(poi_id, {"wikipedia_url": url})
    if poi is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy POI")
    await write_audit(session, user, "poi.source.configure", "poi", poi_id, {"source_url": url})
    return {"id": poi_id, "source_ref": poi.get("source_ref")}


@router.post("/pois/{poi_id}/generate", status_code=202)
async def trigger_generation(poi_id: str, background_tasks: BackgroundTasks, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=160), session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    poi = await POIRepository(session).get_by_id(poi_id)
    if not poi:
        raise HTTPException(status_code=404, detail="Không tìm thấy POI")
    existing = await find_task_by_idempotency_key(idempotency_key)
    if existing and (existing.get("poi_id"), existing.get("task_type"), existing.get("requested_by")) != (poi_id, "CONTENT_GENERATION", user["id"]):
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for a different task")
    if not existing and not (poi.get("source_ref") or {}).get("url"):
        raise HTTPException(status_code=422, detail="Hãy cấu hình nguồn Wikipedia trước")
    try:
        task_id = await create_task(poi_id, "CONTENT_GENERATION", user["id"], idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    queued = await dispatch_task(task_id)
    if not queued:
        if settings.APP_ENV.lower() == "production":
            raise HTTPException(status_code=503, detail="Task queue is unavailable")
        task = await get_task(task_id)
        if claim_local_task(task_id, task):
            background_tasks.add_task(run_local_task, task_id, poi_id, user["id"], "CONTENT_GENERATION")
    await write_audit(session, user, "content.generation.start", "poi", poi_id, {"task_id": task_id})
    task = await get_task(task_id)
    return {"task_id": task_id, "status": task["status"], "status_url": f"/api/v1/admin/tasks/{task_id}"}


@router.get("/contents")
async def admin_contents(poi_id: str | None = None, _: dict = Depends(require_reviewer)):
    return {"data": await list_contents(poi_id)}


@router.patch("/contents/{content_id}")
async def edit_draft(content_id: str, body: DraftReview, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_reviewer)):
    content = await update_draft(content_id, body.script_vi, body.review_note, user["id"])
    if content is None:
        raise HTTPException(status_code=409, detail="Chỉ có thể sửa nội dung đang chờ duyệt")
    await write_audit(session, user, "content.draft.edit", "content_version", content_id)
    return content


@router.post("/contents/{content_id}/approve")
async def approve_draft(content_id: str, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_reviewer)):
    content = await approve_content(content_id, user["id"])
    if content is None:
        raise HTTPException(status_code=409, detail="Nội dung không còn ở trạng thái IN_REVIEW")
    await write_audit(session, user, "content.approve", "content_version", content_id)
    return content


@router.put("/contents/{content_id}/localizations")
async def set_localization(content_id: str, body: LocalizationInput, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_reviewer)):
    content = await save_localization(content_id, body.locale, body.script)
    if content is None:
        raise HTTPException(status_code=409, detail="Duyệt bản nháp trước khi thêm bản dịch")
    await write_audit(session, user, "content.localization.save", "content_version", content_id, {"locale": body.locale})
    return {"content": content, "localizations": await localizations_for(content_id)}


@router.post("/contents/{content_id}/build-audio", status_code=202)
async def build_audio(content_id: str, background_tasks: BackgroundTasks, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=160), session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    content = await get_content(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Không tìm thấy nội dung")
    existing = await find_task_by_idempotency_key(idempotency_key)
    if existing and (existing.get("poi_id"), existing.get("task_type"), existing.get("content_version_id"), existing.get("requested_by")) != (content["poi_id"], "LOCALIZATION_TTS", content_id, user["id"]):
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for a different task")
    if not existing and content["status"] not in {"APPROVED", "LOCALIZED"}:
        raise HTTPException(status_code=409, detail="Duyệt nội dung trước khi tạo bản dịch và audio")
    try:
        task_id = await create_task(content["poi_id"], "LOCALIZATION_TTS", user["id"], idempotency_key, content_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    queued = await dispatch_task(task_id)
    if not queued:
        if settings.APP_ENV.lower() == "production":
            raise HTTPException(status_code=503, detail="Task queue is unavailable")
        task = await get_task(task_id)
        if claim_local_task(task_id, task):
            background_tasks.add_task(run_local_task, task_id, content["poi_id"], user["id"], "LOCALIZATION_TTS", content_id)
    await write_audit(session, user, "content.audio.start", "content_version", content_id, {"task_id": task_id})
    task = await get_task(task_id)
    return {"task_id": task_id, "status": task["status"]}


@router.post("/contents/{content_id}/publish")
async def publish(content_id: str, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    content, error = await publish_content(content_id)
    if error:
        raise HTTPException(status_code=409, detail=error)
    await write_audit(session, user, "content.publish", "content_version", content_id)
    return content


@router.post("/pois/{poi_id}/unpublish")
async def unpublish(poi_id: str, session: AsyncSession | None = Depends(get_session), user: dict = Depends(require_admin)):
    if not await unpublish_poi(poi_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy POI")
    await write_audit(session, user, "poi.unpublish", "poi", poi_id)
    return {"id": poi_id, "status": "UNPUBLISHED"}


@router.get("/tasks")
async def tasks(limit: int = Query(default=100, ge=1, le=500), _: dict = Depends(require_reviewer)):
    return {"data": await list_tasks(limit)}


@router.get("/tasks/{task_id}")
async def task_detail(task_id: str, _: dict = Depends(require_reviewer)):
    task = await get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy task")
    return task


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, _: dict = Depends(require_reviewer)):
    if await get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy task")

    async def stream():
        last = None
        for _ in range(120):
            task = await get_task(task_id)
            payload = json.dumps(task, ensure_ascii=False)
            if payload != last:
                yield f"event: progress\ndata: {payload}\n\n"
                last = payload
            if task["status"] in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/users")
async def list_users(session: AsyncSession | None = Depends(get_session), _: dict = Depends(require_admin)):
    if session is None:
        return {"data": [{"id": item["id"], "username": item["username"], "role": item["role"], "is_active": item["is_active"]} for item in store.users.values()]}
    rows = await session.scalars(select(AdminUser).where(AdminUser.role.in_(["ADMIN", "REVIEWER"])).order_by(AdminUser.username))
    return {"data": [{"id": row.id, "username": row.username, "role": row.role, "is_active": row.is_active} for row in rows.all()]}


@router.post("/users", status_code=201)
async def create_user(body: AdminUserCreate, session: AsyncSession | None = Depends(get_session), actor: dict = Depends(require_admin)):
    if session is None:
        if any(item["username"] == body.username for item in store.users.values()) or body.username == settings.ADMIN_USERNAME:
            raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại")
        user_id = str(uuid4())
        store.users[user_id] = {"id": user_id, "username": body.username, "password_hash": hash_password(body.password), "role": body.role, "is_active": True}
    else:
        user_id = str(uuid4())
        session.add(AdminUser(id=user_id, username=body.username, password_hash=hash_password(body.password), role=body.role))
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Tên đăng nhập đã tồn tại") from exc
    await write_audit(session, actor, "admin_user.create", "admin_user", user_id, {"username": body.username, "role": body.role})
    return {"id": user_id, "username": body.username, "role": body.role}


@router.get("/audit")
async def audit_log(limit: int = Query(default=100, ge=1, le=500), session: AsyncSession | None = Depends(get_session), _: dict = Depends(require_admin)):
    if session is None:
        return {"data": store.audit[:limit]}
    rows = await session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return {"data": [{"id": row.id, "actor_id": row.actor_id, "action": row.action, "target_type": row.target_type, "target_id": row.target_id, "details": row.details, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows.all()]}


@router.get("/analytics/summary")
async def analytics_summary(session: AsyncSession | None = Depends(get_session), _: dict = Depends(require_admin)):
    if session is None:
        events = store.analytics
        counts = {}
        by_poi = {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        for event in events:
            created_at = datetime.fromisoformat(event["created_at"])
            if created_at < cutoff:
                continue
            counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1
            if event.get("poi_id"):
                by_poi[event["poi_id"]] = by_poi.get(event["poi_id"], 0) + 1
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date()
        type_rows = await session.execute(
            select(AnalyticsDailySummary.event_type, func.sum(AnalyticsDailySummary.event_count))
            .where(AnalyticsDailySummary.day >= cutoff)
            .group_by(AnalyticsDailySummary.event_type)
        )
        poi_rows = await session.execute(
            select(AnalyticsDailySummary.poi_id, func.sum(AnalyticsDailySummary.event_count))
            .where(AnalyticsDailySummary.day >= cutoff, AnalyticsDailySummary.poi_id != "")
            .group_by(AnalyticsDailySummary.poi_id)
            .order_by(func.sum(AnalyticsDailySummary.event_count).desc())
            .limit(10)
        )
        counts, by_poi = dict(type_rows.all()), dict(poi_rows.all())
        # The in-process/local mode has no aggregation worker, so use the raw
        # consented event table until the first daily summary is available.
        if not counts:
            type_rows = await session.execute(select(AnalyticsEvent.event_type, func.count()).group_by(AnalyticsEvent.event_type))
            poi_rows = await session.execute(select(AnalyticsEvent.poi_id, func.count()).where(AnalyticsEvent.poi_id.is_not(None)).group_by(AnalyticsEvent.poi_id).order_by(func.count().desc()).limit(10))
            counts, by_poi = dict(type_rows.all()), dict(poi_rows.all())
    return {"window_days": 30, "total_events": sum(counts.values()), "by_event_type": counts, "top_pois": [{"poi_id": key, "events": count} for key, count in sorted(by_poi.items(), key=lambda item: item[1], reverse=True)[:10]]}
