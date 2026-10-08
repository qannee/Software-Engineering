"""Add public user accounts and per-user POI favorites.

Revision ID: 20261007_0003
Revises: 20261007_0002
"""
from alembic import op
from sqlalchemy import text

from app.models import domain  # noqa: F401
from app.models.poi import Base

revision = "20261007_0003"
down_revision = "20261007_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_admin_users_role", "admin_users", type_="check")
    op.create_check_constraint("ck_admin_users_role", "admin_users", "role IN ('ADMIN', 'REVIEWER', 'USER')")
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute(text("DELETE FROM admin_users WHERE role = 'USER'"))
    op.drop_table("user_favorites")
    op.drop_constraint("ck_admin_users_role", "admin_users", type_="check")
    op.create_check_constraint("ck_admin_users_role", "admin_users", "role IN ('ADMIN', 'REVIEWER')")
