from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models import domain  # noqa: F401
from app.models.poi import POIRecord


class Database:
    engine = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    redis_pool = None


db = Database()


async def connect_db(connect_queue: bool = True) -> None:
    if settings.REDIS_ENABLED and connect_queue:
        from arq import create_pool
        from arq.connections import RedisSettings

        try:
            db.redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        except Exception as exc:
            db.redis_pool = None
            if settings.APP_ENV.lower() == "production":
                raise RuntimeError("Redis is required in production but could not be reached") from exc
            print(f"Redis unavailable; using local in-process task execution: {exc}")

    if not settings.POSTGRES_ENABLED:
        print("PostgreSQL is disabled; API is using demo data.")
        return

    try:
        db.engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        async with db.engine.begin() as connection:
            await connection.run_sync(_upgrade_schema)
        db.session_factory = async_sessionmaker(db.engine, expire_on_commit=False)
        await seed_demo_pois()
        print("Connected to PostgreSQL successfully.")
    except Exception as exc:
        if db.engine is not None:
            await db.engine.dispose()
        db.engine = None
        db.session_factory = None
        if db.redis_pool is not None:
            await db.redis_pool.aclose()
            db.redis_pool = None
        if settings.APP_ENV.lower() == "production":
            raise RuntimeError("PostgreSQL is required in production but could not be reached") from exc
        print(f"PostgreSQL unavailable; public API will use demo data: {exc}")


def _upgrade_schema(connection) -> None:
    """Apply checked-in Alembic revisions using the app's existing connection."""
    from alembic import command
    from alembic.config import Config

    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[2]
    migration_config = Config(str(backend_dir / "alembic.ini"))
    migration_config.attributes["connection"] = connection
    command.upgrade(migration_config, "head")


async def seed_demo_pois() -> None:
    """Seed starter landmarks and backfill categories on older demo databases."""
    from app.repositories.poi_repository import POIRepository
    from sqlalchemy import select, update

    async with db.session_factory() as session:
        demo_items = POIRepository.demo_data()
        existing_slugs = set((await session.scalars(select(POIRecord.slug))).all())
        for item in demo_items:
            if item["slug"] not in existing_slugs:
                coords = item["location"]["coordinates"]
                session.add(POIRecord(
                    id=item["id"], title=item["title"], title_en=item.get("title_en"),
                    slug=item["slug"], category=item.get("category"), address=item.get("address"),
                    opening_hours=item.get("opening_hours"), longitude=coords[0], latitude=coords[1],
                    geofence_radius=item["geofence_radius"], summary_vi=item.get("summary_vi"),
                    summary_en=item.get("summary_en"), status="PUBLISHED", source_ref=item.get("source_ref"),
                ))
                existing_slugs.add(item["slug"])
            elif item.get("category"):
                await session.execute(
                    update(POIRecord).where(
                        POIRecord.slug == item["slug"], POIRecord.category.is_(None)
                    ).values(category=item["category"])
                )
        await session.commit()


def select_count_pois():
    from sqlalchemy import func, select

    return select(func.count()).select_from(POIRecord)


async def close_db() -> None:
    if db.engine is not None:
        await db.engine.dispose()
        db.engine = None
        db.session_factory = None
        print("Closed PostgreSQL connection.")
    if db.redis_pool is not None:
        await db.redis_pool.aclose()
        db.redis_pool = None


async def get_session() -> AsyncIterator[AsyncSession | None]:
    if db.session_factory is None:
        yield None
        return

    async with db.session_factory() as session:
        yield session
