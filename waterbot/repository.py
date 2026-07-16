from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from waterbot.models import User


@dataclass(frozen=True, slots=True)
class DueReminder:
    user_id: int
    telegram_user_id: int
    chat_id: int
    name: str
    token: str
    is_working_out: bool


@dataclass(frozen=True, slots=True)
class DrinkConfirmation:
    is_working_out: bool


class UserRepository:
    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(select(1))

    async def close(self) -> None:
        await self.engine.dispose()

    async def get(self, telegram_user_id: int) -> User | None:
        async with self.sessions() as db:
            return await db.scalar(
                select(User).where(User.telegram_user_id == telegram_user_id)
            )

    async def create_or_touch(
        self,
        telegram_user_id: int,
        chat_id: int,
        now: datetime,
        idle_threshold: datetime,
    ) -> tuple[User, bool]:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if user and user.last_activity_at <= idle_threshold:
                await db.delete(user)
                await db.flush()
                user = None
            if user:
                user.chat_id = chat_id
                user.last_activity_at = now
                user.updated_at = now
                return user, False
            user = User(
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                timezone="Asia/Singapore",
                onboarding_step="name",
                created_at=now,
                updated_at=now,
                last_activity_at=now,
            )
            db.add(user)
            await db.flush()
            return user, True

    async def touch(
        self,
        telegram_user_id: int,
        chat_id: int,
        now: datetime,
        idle_threshold: datetime,
    ) -> User | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            if user.last_activity_at <= idle_threshold:
                await db.delete(user)
                return None
            user.chat_id = chat_id
            user.last_activity_at = now
            user.updated_at = now
            return user

    async def set_name(
        self, telegram_user_id: int, name: str, now: datetime
    ) -> User | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            was_update = user.onboarding_step == "name_update"
            user.name = name
            user.onboarding_step = "none" if was_update else "timezone"
            user.last_activity_at = now
            user.updated_at = now
            return user

    async def set_timezone(
        self, telegram_user_id: int, timezone: str, now: datetime
    ) -> User | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            user.timezone = timezone
            user.onboarding_step = "none" if user.name else "name"
            user.last_activity_at = now
            user.updated_at = now
            return user

    async def set_onboarding_step(
        self, telegram_user_id: int, step: str, now: datetime
    ) -> bool:
        async with self.sessions.begin() as db:
            result = await db.execute(
                update(User)
                .where(User.telegram_user_id == telegram_user_id)
                .values(
                    onboarding_step=step,
                    last_activity_at=now,
                    updated_at=now,
                )
            )
            return result.rowcount == 1

    async def start_day(
        self, telegram_user_id: int, now: datetime, max_awake_hours: int
    ) -> tuple[User | None, bool]:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None, False
            user.last_activity_at = now
            user.updated_at = now
            if user.is_awake:
                return user, False
            user.is_awake = True
            user.is_working_out = False
            user.session_started_at = now
            user.next_reminder_at = now
            user.session_stop_at = now + timedelta(hours=max_awake_hours)
            user.current_reminder_token = None
            return user, True

    async def stop_day(self, telegram_user_id: int, now: datetime) -> str | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            user.last_activity_at = now
            user.updated_at = now
            if user.is_working_out:
                return "working_out"
            if not user.is_awake:
                return "inactive"
            self._clear_session(user)
            return "stopped"

    async def stop_day_from_reminder(
        self, telegram_user_id: int, token: str, now: datetime
    ) -> str | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            user.last_activity_at = now
            user.updated_at = now
            if user.is_working_out:
                return "working_out"
            if not user.is_awake or user.current_reminder_token != token:
                return "stale"
            self._clear_session(user)
            return "stopped"

    async def start_workout(
        self, telegram_user_id: int, now: datetime
    ) -> str | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            user.last_activity_at = now
            user.updated_at = now
            if not user.is_awake:
                return "not_awake"
            if user.is_working_out:
                return "already_working_out"
            user.is_working_out = True
            user.next_reminder_at = now
            user.current_reminder_token = None
            return "started"

    async def end_workout(
        self,
        telegram_user_id: int,
        now: datetime,
        token: str | None = None,
    ) -> str | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            user.last_activity_at = now
            user.updated_at = now
            if not user.is_awake or not user.is_working_out:
                return "not_working_out"
            if token is not None and user.current_reminder_token != token:
                return "stale"
            user.is_working_out = False
            user.next_reminder_at = now
            user.current_reminder_token = None
            return "ended"

    async def claim_due(
        self,
        now: datetime,
        normal_interval_minutes: int,
        workout_interval_minutes: int,
        idle_threshold: datetime,
    ) -> list[DueReminder]:
        claimed: list[DueReminder] = []
        async with self.sessions.begin() as db:
            users = list(
                (
                    await db.scalars(
                        select(User)
                        .where(
                            User.is_awake.is_(True),
                            User.next_reminder_at <= now,
                            User.session_stop_at > now,
                            User.last_activity_at > idle_threshold,
                            User.name.is_not(None),
                            User.onboarding_step == "none",
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for user in users:
                token = str(uuid.uuid4())
                interval_minutes = (
                    workout_interval_minutes
                    if user.is_working_out
                    else normal_interval_minutes
                )
                user.current_reminder_token = token
                user.next_reminder_at = now + timedelta(minutes=interval_minutes)
                user.updated_at = now
                claimed.append(
                    DueReminder(
                        user.id,
                        user.telegram_user_id,
                        user.chat_id,
                        user.name or "Friend",
                        token,
                        user.is_working_out,
                    )
                )
        return claimed

    async def retry_delivery(
        self, user_id: int, token: str, retry_at: datetime
    ) -> None:
        async with self.sessions.begin() as db:
            await db.execute(
                update(User)
                .where(User.id == user_id, User.current_reminder_token == token)
                .values(next_reminder_at=retry_at, current_reminder_token=None)
            )

    async def confirm_drink(
        self, telegram_user_id: int, token: str, now: datetime
    ) -> DrinkConfirmation | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            if not user.is_awake or user.current_reminder_token != token:
                return None
            is_working_out = user.is_working_out
            user.current_reminder_token = None
            user.last_drank_at = now
            user.last_activity_at = now
            user.updated_at = now
            return DrinkConfirmation(is_working_out=is_working_out)

    async def snooze(
        self, telegram_user_id: int, token: str, now: datetime, minutes: int
    ) -> bool | None:
        async with self.sessions.begin() as db:
            user = await db.scalar(
                select(User)
                .where(User.telegram_user_id == telegram_user_id)
                .with_for_update()
            )
            if not user:
                return None
            if not user.is_awake or user.current_reminder_token != token:
                return False
            user.current_reminder_token = None
            user.next_reminder_at = now + timedelta(minutes=minutes)
            user.last_activity_at = now
            user.updated_at = now
            return True

    async def expire_sessions(self, now: datetime) -> None:
        async with self.sessions.begin() as db:
            users = list(
                (
                    await db.scalars(
                        select(User)
                        .where(User.is_awake.is_(True), User.session_stop_at <= now)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for user in users:
                self._clear_session(user)
                user.updated_at = now

    async def delete_expired(self, threshold: datetime) -> int:
        async with self.sessions.begin() as db:
            result = await db.execute(
                delete(User).where(User.last_activity_at <= threshold)
            )
            return int(result.rowcount or 0)

    async def delete_user(self, telegram_user_id: int) -> bool:
        async with self.sessions.begin() as db:
            result = await db.execute(
                delete(User).where(User.telegram_user_id == telegram_user_id)
            )
            return result.rowcount == 1

    @staticmethod
    def _clear_session(user: User) -> None:
        user.is_awake = False
        user.is_working_out = False
        user.session_started_at = None
        user.next_reminder_at = None
        user.session_stop_at = None
        user.current_reminder_token = None
