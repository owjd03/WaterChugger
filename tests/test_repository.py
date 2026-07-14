from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from waterbot.repository import UserRepository

pytestmark = pytest.mark.asyncio
NOW = datetime(2026, 7, 14, 0, 0, tzinfo=UTC)


def repository_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for repository integration tests")
    return url


async def clean(repository: UserRepository) -> None:
    async with repository.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users RESTART IDENTITY"))


async def test_identity_and_unique_telegram_user() -> None:
    repository = UserRepository(repository_database_url())
    await clean(repository)
    first, created = await repository.create_or_touch(
        1001, 1001, NOW, NOW - timedelta(hours=24)
    )
    assert created is True
    assert first.id == 1

    same, created = await repository.create_or_touch(
        1001, 1001, NOW + timedelta(minutes=1), NOW - timedelta(hours=24)
    )
    assert created is False
    assert same.id == first.id
    await repository.close()


async def test_onboarding_and_schedule_recovery_fields() -> None:
    repository = UserRepository(repository_database_url())
    await clean(repository)
    user, _ = await repository.create_or_touch(1001, 1001, NOW, NOW - timedelta(hours=24))
    assert user.onboarding_step == "name"
    user = await repository.set_name(1001, "Ada", NOW)
    assert user and user.onboarding_step == "timezone"
    user = await repository.set_timezone(1001, "Asia/Singapore", NOW)
    assert user and user.onboarding_step == "none"

    user, started = await repository.start_day(1001, NOW, 18)
    assert started is True
    assert user and user.next_reminder_at == NOW
    due = await repository.claim_due(NOW, 60, NOW - timedelta(hours=24))
    assert len(due) == 1
    saved = await repository.get(1001)
    assert saved and saved.current_reminder_token == due[0].token
    assert saved.next_reminder_at == NOW + timedelta(minutes=60)
    await repository.close()


async def test_drink_confirmation_is_idempotent_and_singapore_safe() -> None:
    repository = UserRepository(repository_database_url())
    await clean(repository)
    await repository.create_or_touch(1001, 1001, NOW, NOW - timedelta(hours=24))
    await repository.set_name(1001, "Ada", NOW)
    await repository.set_timezone(1001, "Asia/Singapore", NOW)
    await repository.start_day(1001, NOW, 18)
    reminder = (await repository.claim_due(NOW, 60, NOW - timedelta(hours=24)))[0]

    drank_at = NOW + timedelta(minutes=2)
    assert await repository.confirm_drink(1001, reminder.token, drank_at) is True
    assert await repository.confirm_drink(1001, reminder.token, drank_at) is False
    saved = await repository.get(1001)
    assert saved and saved.last_drank_at == drank_at
    await repository.close()


async def test_snooze_and_wrong_user_token() -> None:
    repository = UserRepository(repository_database_url())
    await clean(repository)
    for telegram_id in (1001, 1002):
        await repository.create_or_touch(
            telegram_id, telegram_id, NOW, NOW - timedelta(hours=24)
        )
        await repository.set_name(telegram_id, f"User {telegram_id}", NOW)
        await repository.set_timezone(telegram_id, "Asia/Singapore", NOW)
        await repository.start_day(telegram_id, NOW, 18)
    reminders = await repository.claim_due(NOW, 60, NOW - timedelta(hours=24))
    first = next(item for item in reminders if item.telegram_user_id == 1001)
    assert await repository.snooze(1002, first.token, NOW, 15) is False
    assert await repository.snooze(1001, first.token, NOW, 15) is True
    saved = await repository.get(1001)
    assert saved and saved.next_reminder_at == NOW + timedelta(minutes=15)
    await repository.close()


async def test_expiry_and_forget_delete_complete_rows() -> None:
    repository = UserRepository(repository_database_url())
    await clean(repository)
    await repository.create_or_touch(1001, 1001, NOW, NOW - timedelta(hours=24))
    assert await repository.delete_expired(NOW - timedelta(minutes=1)) == 0
    assert await repository.delete_expired(NOW) == 1
    assert await repository.get(1001) is None

    await repository.create_or_touch(
        1002, 1002, NOW + timedelta(days=1), NOW
    )
    assert await repository.delete_user(1002) is True
    assert await repository.get(1002) is None
    await repository.close()
