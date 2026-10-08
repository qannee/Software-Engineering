from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_session
from app.repositories.poi_repository import POIRepository
from app.services.content_service import audio_for, list_contents, localizations_for

router = APIRouter(prefix="/poi", tags=["POI"])

@router.get("/manifest")
async def get_poi_manifest(session = Depends(get_session)):
    repo = POIRepository(session)
    pois = await repo.list_published()
    versions = [item for item in await list_contents() if item["status"] == "PUBLISHED"]
    latest = {}
    for version in versions:
        if version["poi_id"] not in latest or version["version"] > latest[version["poi_id"]]["version"]:
            latest[version["poi_id"]] = version
    for poi in pois:
        content = latest.get(poi["id"])
        if content:
            poi["localizations"] = await localizations_for(content["id"])
            poi["audio"] = await audio_for(content["id"])
    return {"status": "success", "count": len(pois), "data": pois}

@router.get("/{poi_id}")
async def get_poi_detail(poi_id: str, session = Depends(get_session)):
    repo = POIRepository(session)
    poi = await repo.get_by_id(poi_id)
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    return poi
