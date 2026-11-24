"""custom_shops: shops a user adds, searched with every search

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

import app.core.db

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_shops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("host", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("search_url", sa.String(length=1000), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("state_detail", sa.String(length=300), nullable=True),
        sa.Column("checked_at", app.core.db.TZDateTime(timezone=True), nullable=True),
        sa.Column("paused_until", app.core.db.TZDateTime(timezone=True), nullable=True),
        sa.Column("found_total", sa.Integer(), nullable=False),
        sa.Column("created_at", app.core.db.TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", app.core.db.TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_custom_shops_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_shops")),
        sa.UniqueConstraint("user_id", "host", name="uq_custom_shop_user_host"),
    )
    op.create_index(op.f("ix_custom_shops_user_id"), "custom_shops", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_custom_shops_user_id"), table_name="custom_shops")
    op.drop_table("custom_shops")
