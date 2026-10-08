from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.domain import AnalyticsConsent, AnalyticsEvent
from app.schemas.admin import AnalyticsInput, ConsentInput
from app.services.runtime_store import store

router = APIRouter(tags=["Analytics & Offline"])


@router.post("/analytics/consent")
async def set_analytics_consent(body: ConsentInput, session: AsyncSession | None = Depends(get_session)):
    if body.accepted:
        token = str(uuid4())
        if session is None:
            store.consents[token] = True
        else:
            session.add(AnalyticsConsent(token=token, accepted=True))
            await session.commit()
        return {"accepted": True, "consent_token": token}
    if body.token:
        if session is None:
            store.consents[body.token] = False
            store.analytics[:] = [event for event in store.analytics if event.get("consent_token") != body.token]
        else:
            consent = await session.get(AnalyticsConsent, body.token)
            if consent:
                consent.accepted = False
                consent.revoked_at = datetime.now(timezone.utc)
                await session.execute(delete(AnalyticsEvent).where(AnalyticsEvent.consent_token == body.token))
                await session.commit()
    return {"accepted": False, "consent_token": None}


@router.post("/analytics/events", status_code=202)
async def record_event(body: AnalyticsInput, session: AsyncSession | None = Depends(get_session)):
    if session is None:
        accepted = store.consents.get(body.consent_token, False)
    else:
        consent = await session.get(AnalyticsConsent, body.consent_token)
        accepted = bool(consent and consent.accepted and consent.revoked_at is None)
    if not accepted:
        raise HTTPException(status_code=403, detail="Analytics consent is required")
    safe_metadata = {key: value for key, value in body.metadata.items() if key in {"locale", "duration_seconds", "source"} and isinstance(value, (str, int, float, bool))}
    row = {"id": str(uuid4()), "consent_token": body.consent_token, "session_id": body.session_id, "event_type": body.event_type, "poi_id": body.poi_id, "metadata": safe_metadata, "created_at": datetime.now(timezone.utc).isoformat()}
    if session is None:
        store.analytics.append(row)
        del store.analytics[:-10000]
    else:
        session.add(AnalyticsEvent(id=row["id"], consent_token=body.consent_token, session_id=body.session_id, event_type=body.event_type, poi_id=body.poi_id, metadata_json=safe_metadata))
        await session.commit()
    return {"accepted": True}


@router.get("/offline/manifest")
async def offline_manifest(session: AsyncSession | None = Depends(get_session)):
    from app.repositories.poi_repository import POIRepository
    from app.services.content_service import audio_for, list_contents, localizations_for

    pois = await POIRepository(session).list_published()
    versions = [version for version in await list_contents() if version["status"] == "PUBLISHED"]
    latest = {}
    for version in versions:
        if version["poi_id"] not in latest or version["version"] > latest[version["poi_id"]]["version"]:
            latest[version["poi_id"]] = version
    packages = []
    for poi in pois:
        content = latest.get(poi["id"])
        package = {"poi": poi, "localizations": {}, "audio": {}}
        if content:
            package["localizations"] = await localizations_for(content["id"])
            package["audio"] = await audio_for(content["id"])
        packages.append(package)
    return {"version": "1", "generated_at": datetime.now(timezone.utc).isoformat(), "count": len(packages), "packages": packages}
