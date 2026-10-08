"""Add durable job dispatch, rotating refresh sessions, and analytics read models.

Revision ID: 20261007_0002
Revises: 20261007_0001
"""
from alembic import op
from sqlalchemy import inspect, text

from app.models import domain  # noqa: F401
from app.models.poi import Base

revision = "20261007_0002"
down_revision = "20261007_0001"
branch_labels = None
depends_on = None


def _ensure_column(table: str, name: str, sql_type: str) -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns(table)}
    if name not in columns:
        op.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def _ensure_index(table: str, name: str, columns: list[str]) -> None:
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns)


def upgrade() -> None:
    # New tables are created from metadata; existing tables are altered explicitly below.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)
    _ensure_column("workflow_tasks", "idempotency_key", "VARCHAR(160)")
    _ensure_column("workflow_tasks", "next_run_at", "TIMESTAMP WITH TIME ZONE")
    _ensure_column("workflow_tasks", "lease_until", "TIMESTAMP WITH TIME ZONE")
    _ensure_column("workflow_tasks", "worker_id", "VARCHAR(120)")
    op.execute(text("""
        DO $migration$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_workflow_tasks_idempotency_key'
                  AND conrelid = 'workflow_tasks'::regclass
            ) THEN
                ALTER TABLE workflow_tasks
                    ADD CONSTRAINT uq_workflow_tasks_idempotency_key UNIQUE (idempotency_key);
            END IF;
        END;
        $migration$;
    """))
    _ensure_index("workflow_tasks", "ix_workflow_tasks_status_next_run", ["status", "next_run_at"])
    _ensure_index("workflow_tasks", "ix_workflow_tasks_next_run_at", ["next_run_at"])
    _ensure_index("workflow_tasks", "ix_workflow_tasks_lease_until", ["lease_until"])
    # Adopt tasks created before the transactional outbox existed. PROCESSING rows
    # from the old in-process runner have no lease and must be returned to the queue.
    op.execute(text("""
        UPDATE workflow_tasks
        SET status = 'RETRY_PENDING', current_step = 'RETRY_PENDING',
            next_run_at = now(),
            error_message = COALESCE(error_message, 'Recovered during queue migration')
        WHERE status = 'PROCESSING'
    """))
    op.execute(text("""
        INSERT INTO queue_outbox (task_id, attempts)
        SELECT id, 0 FROM workflow_tasks
        WHERE status IN ('PENDING', 'RETRY_PENDING')
        ON CONFLICT (task_id) DO NOTHING
    """))


def downgrade() -> None:
    # Session and job history are operational records; keep them during rollback.
    pass
