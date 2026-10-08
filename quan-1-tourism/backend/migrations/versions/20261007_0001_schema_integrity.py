"""Create/upgrade the application schema and enforce core data invariants.

Revision ID: 20261007_0001
Revises:
"""
from alembic import op
from sqlalchemy import inspect, text

from app.models import domain  # noqa: F401
from app.models.poi import Base

revision = "20261007_0001"
down_revision = None
branch_labels = None
depends_on = None


def _add_poi_column_if_missing(name: str, sql_type: str) -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("pois")}
    if name not in columns:
        op.execute(text(f"ALTER TABLE pois ADD COLUMN {name} {sql_type}"))


def _add_check_if_missing(table: str, name: str, expression: str) -> None:
    op.execute(text(f"""
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{name}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression});
            END IF;
        END;
        $migration$;
    """))


def upgrade() -> None:
    # Create tables on a fresh database; existing tables remain untouched by create_all.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    _add_poi_column_if_missing("category", "VARCHAR(80)")
    _add_poi_column_if_missing("address", "VARCHAR(300)")
    _add_poi_column_if_missing("opening_hours", "VARCHAR(300)")

    checks = [
        ("pois", "ck_pois_latitude_range", "latitude BETWEEN -90 AND 90"),
        ("pois", "ck_pois_longitude_range", "longitude BETWEEN -180 AND 180"),
        ("pois", "ck_pois_geofence_radius", "geofence_radius > 0 AND geofence_radius <= 1000"),
        ("pois", "ck_pois_status", "status IN ('DRAFT', 'PUBLISHED', 'APPROVED')"),
        ("admin_users", "ck_admin_users_username_nonempty", "length(trim(username)) > 0"),
        ("admin_users", "ck_admin_users_role", "role IN ('ADMIN', 'REVIEWER')"),
        ("content_versions", "ck_content_versions_positive_version", "version > 0"),
        ("content_versions", "ck_content_versions_status", "status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'LOCALIZED', 'AUDIO_READY', 'PUBLISHED', 'UNPUBLISHED')"),
        ("content_localizations", "ck_content_localizations_locale", "locale IN ('vi-VN', 'en-US')"),
        ("audio_assets", "ck_audio_assets_locale", "locale IN ('vi-VN', 'en-US')"),
        ("audio_assets", "ck_audio_assets_url_nonempty", "length(trim(audio_url)) > 0"),
        ("workflow_tasks", "ck_workflow_tasks_type", "task_type IN ('CONTENT_GENERATION', 'LOCALIZATION_TTS')"),
        ("workflow_tasks", "ck_workflow_tasks_status", "status IN ('PENDING', 'PROCESSING', 'RETRY_PENDING', 'COMPLETED', 'FAILED')"),
        ("workflow_tasks", "ck_workflow_tasks_attempts", "attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts"),
        ("analytics_consents", "ck_analytics_consents_revocation", "accepted OR revoked_at IS NOT NULL"),
        ("analytics_events", "ck_analytics_events_type", "event_type IN ('poi_view', 'narration_started', 'narration_completed', 'language_changed', 'offline_downloaded')"),
    ]
    for table, name, expression in checks:
        _add_check_if_missing(table, name, expression)


def downgrade() -> None:
    # This baseline revision also adopts existing installations; dropping its schema
    # would destroy application data, so rollback is intentionally non-destructive.
    pass
