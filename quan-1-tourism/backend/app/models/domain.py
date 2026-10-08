from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.poi import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint("length(trim(username)) > 0", name="ck_admin_users_username_nonempty"),
        CheckConstraint("role IN ('ADMIN', 'REVIEWER', 'USER')", name="ck_admin_users_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="ADMIN")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_expires", "user_id", "expires_at"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserFavorite(Base):
    __tablename__ = "user_favorites"

    user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), primary_key=True)
    poi_id: Mapped[str] = mapped_column(ForeignKey("pois.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContentVersion(Base):
    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("poi_id", "version", name="uq_content_poi_version"),
        CheckConstraint("version > 0", name="ck_content_versions_positive_version"),
        CheckConstraint("status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'LOCALIZED', 'AUDIO_READY', 'PUBLISHED', 'UNPUBLISHED')", name="ck_content_versions_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    poi_id: Mapped[str] = mapped_column(ForeignKey("pois.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT", index=True)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_revision: Mapped[str | None] = mapped_column(String(120))
    source_snapshot: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    ai_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    script_vi: Mapped[str | None] = mapped_column(Text)
    script_en: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentLocalization(Base):
    __tablename__ = "content_localizations"
    __table_args__ = (
        UniqueConstraint("content_version_id", "locale", name="uq_localization_version_locale"),
        CheckConstraint("locale IN ('vi-VN', 'en-US')", name="ck_content_localizations_locale"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content_version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id", ondelete="CASCADE"), index=True)
    locale: Mapped[str] = mapped_column(String(12), nullable=False)
    script: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="LOCALIZED")


class AudioAsset(Base):
    __tablename__ = "audio_assets"
    __table_args__ = (
        UniqueConstraint("content_version_id", "locale", "voice", name="uq_audio_version_locale_voice"),
        CheckConstraint("locale IN ('vi-VN', 'en-US')", name="ck_audio_assets_locale"),
        CheckConstraint("length(trim(audio_url)) > 0", name="ck_audio_assets_url_nonempty"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    content_version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id", ondelete="CASCADE"), index=True)
    locale: Mapped[str] = mapped_column(String(12), nullable=False)
    voice: Mapped[str] = mapped_column(String(120), nullable=False)
    audio_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowTask(Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workflow_tasks_idempotency_key"),
        Index("ix_workflow_tasks_status_next_run", "status", "next_run_at"),
        CheckConstraint("task_type IN ('CONTENT_GENERATION', 'LOCALIZATION_TTS')", name="ck_workflow_tasks_type"),
        CheckConstraint("status IN ('PENDING', 'PROCESSING', 'RETRY_PENDING', 'COMPLETED', 'FAILED')", name="ck_workflow_tasks_status"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts", name="ck_workflow_tasks_attempts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    poi_id: Mapped[str] = mapped_column(ForeignKey("pois.id", ondelete="CASCADE"), index=True)
    content_version_id: Mapped[str | None] = mapped_column(ForeignKey("content_versions.id", ondelete="SET NULL"))
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    current_step: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class QueueOutbox(Base):
    __tablename__ = "queue_outbox"

    task_id: Mapped[str] = mapped_column(ForeignKey("workflow_tasks.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AnalyticsConsent(Base):
    __tablename__ = "analytics_consents"
    __table_args__ = (
        CheckConstraint("accepted OR revoked_at IS NOT NULL", name="ck_analytics_consents_revocation"),
    )

    token: Mapped[str] = mapped_column(String(36), primary_key=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_event_type_created", "event_type", "created_at"),
        CheckConstraint("event_type IN ('poi_view', 'narration_started', 'narration_completed', 'language_changed', 'offline_downloaded')", name="ck_analytics_events_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consent_token: Mapped[str] = mapped_column(ForeignKey("analytics_consents.token", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    poi_id: Mapped[str | None] = mapped_column(String(36), index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AnalyticsDailySummary(Base):
    __tablename__ = "analytics_daily_summaries"
    __table_args__ = (UniqueConstraint("day", "event_type", "poi_id", name="uq_analytics_daily_summary_dimension"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    poi_id: Mapped[str | None] = mapped_column(String(36), index=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
