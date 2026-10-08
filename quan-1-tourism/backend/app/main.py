from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import connect_db, close_db, db
from app.core.security import bootstrap_admin
from app.core.observability import observe_request, render_http_metrics
from app.routers import admin_router, analytics_router, poi_router, user_router
from app.services.content_service import recover_pending_tasks

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs"
)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
app.middleware("http")(observe_request)
Path(settings.AUDIO_DIRECTORY).mkdir(parents=True, exist_ok=True)
app.mount("/media/audio", StaticFiles(directory=settings.AUDIO_DIRECTORY, check_dir=False), name="audio")

@app.on_event("startup")
async def startup_event():
    settings.validate_production()
    await connect_db()
    await bootstrap_admin()
    await recover_pending_tasks()

@app.on_event("shutdown")
async def shutdown_event():
    await close_db()

app.include_router(poi_router.router, prefix=settings.API_V1_STR)
app.include_router(admin_router.router, prefix=settings.API_V1_STR)
app.include_router(user_router.router, prefix=settings.API_V1_STR)
app.include_router(analytics_router.router, prefix=settings.API_V1_STR)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/health/ready")
async def readiness_check():
    database_state = "demo-mode"
    if db.session_factory is not None:
        try:
            from sqlalchemy import text

            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))
            database_state = "connected"
        except Exception:
            database_state = "unavailable"
    redis_state = "disabled"
    if settings.REDIS_ENABLED:
        try:
            if db.redis_pool is None:
                raise RuntimeError("Redis connection is not initialized")
            await db.redis_pool.ping()
            redis_state = "connected"
        except Exception:
            redis_state = "unavailable"
    ready = database_state != "unavailable" and redis_state != "unavailable"
    if settings.APP_ENV.lower() == "production":
        ready = ready and database_state == "connected" and redis_state == "connected"
    if not ready:
        raise HTTPException(status_code=503, detail={"ready": False, "database": database_state, "redis": redis_state})
    return {"ready": True, "database": database_state, "redis": redis_state, "environment": settings.APP_ENV}


@app.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(render_http_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")
