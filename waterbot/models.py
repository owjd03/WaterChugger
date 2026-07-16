from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    String,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_last_activity_at", "last_activity_at"),
        Index("ix_users_due_reminders", "is_awake", "next_reminder_at"),
        CheckConstraint(
            "NOT is_working_out OR is_awake",
            name="ck_users_workout_requires_awake",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(start=1), primary_key=True
    )
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(String(50))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Singapore'")
    )
    onboarding_step: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'name'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_drank_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_awake: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_working_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    session_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    next_reminder_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    session_stop_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    current_reminder_token: Mapped[str | None] = mapped_column(String(36))
