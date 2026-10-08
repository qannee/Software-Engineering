from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, JSON, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class POIRecord(Base):
    __tablename__ = "pois"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_pois_latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_pois_longitude_range"),
        CheckConstraint("geofence_radius > 0 AND geofence_radius <= 1000", name="ck_pois_geofence_radius"),
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'APPROVED')", name="ck_pois_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str | None] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(String(300))
    opening_hours: Mapped[str | None] = mapped_column(String(300))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    geofence_radius: Mapped[float] = mapped_column(Float, nullable=False, default=30)
    summary_vi: Mapped[str | None] = mapped_column(String)
    summary_en: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    source_ref: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
