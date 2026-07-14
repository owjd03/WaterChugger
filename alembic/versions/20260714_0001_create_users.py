"""create users table

Revision ID: 20260714_0001
Revises:
Create Date: 2026-07-14
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(start=1),
            nullable=False,
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Singapore'"),
            nullable=False,
        ),
        sa.Column(
            "onboarding_step",
            sa.String(length=20),
            server_default=sa.text("'name'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_drank_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_awake", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_stop_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_reminder_token", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index("ix_users_last_activity_at", "users", ["last_activity_at"])
    op.create_index(
        "ix_users_due_reminders", "users", ["is_awake", "next_reminder_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_users_due_reminders", table_name="users")
    op.drop_index("ix_users_last_activity_at", table_name="users")
    op.drop_table("users")

