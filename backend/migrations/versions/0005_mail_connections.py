"""mail_connections: a user's own mailbox, read for Ricardo / tutti alert mails

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

import app.core.db

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("folder", sa.String(length=120), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("uidvalidity", sa.BigInteger(), nullable=True),
        sa.Column("last_uid", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("state_detail", sa.String(length=300), nullable=True),
        sa.Column("checked_at", app.core.db.TZDateTime(timezone=True), nullable=True),
        sa.Column("last_alert_at", app.core.db.TZDateTime(timezone=True), nullable=True),
        sa.Column(
            "stats",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", app.core.db.TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", app.core.db.TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_mail_connections_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_connections")),
    )
    op.create_index(op.f("ix_mail_connections_user_id"), "mail_connections", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_mail_connections_user_id"), table_name="mail_connections")
    op.drop_table("mail_connections")
