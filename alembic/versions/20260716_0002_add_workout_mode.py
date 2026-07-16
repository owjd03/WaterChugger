"""add workout mode

Revision ID: 20260716_0002
Revises: 20260714_0001
Create Date: 2026-07-16
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0002"
down_revision: str | None = "20260714_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_working_out",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_workout_requires_awake",
        "users",
        "NOT is_working_out OR is_awake",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_workout_requires_awake", "users", type_="check"
    )
    op.drop_column("users", "is_working_out")
