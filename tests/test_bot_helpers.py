from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import waterbot.bot as bot_module
from waterbot.bot import (
    DRINK_ENCOURAGEMENT_MESSAGES,
    awake_command,
    drink_confirmation_message,
    format_singapore,
    validate_name,
    validate_timezone,
)


def test_name_validation() -> None:
    assert validate_name("  Ada   Lovelace ") == "Ada Lovelace"
    assert validate_name("") is None
    assert validate_name("x" * 51) is None


def test_timezone_validation() -> None:
    assert validate_timezone("Asia/Singapore") == "Asia/Singapore"
    assert validate_timezone("Not/A_Timezone") is None


def test_singapore_time_formatting_crosses_utc_date_boundary() -> None:
    value = datetime(2026, 7, 14, 18, 30, tzinfo=UTC)
    assert format_singapore(value) == "15 Jul 2026, 02:30 SGT"


def test_drink_confirmation_uses_hardcoded_fun_message(monkeypatch) -> None:
    monkeypatch.setattr(
        bot_module.random,
        "choice",
        lambda messages: messages[0],
    )
    value = datetime(2026, 7, 14, 18, 30, tzinfo=UTC)

    assert drink_confirmation_message(value) == (
        f"{DRINK_ENCOURAGEMENT_MESSAGES[0]}\n"
        "Last drink: 15 Jul 2026, 02:30 SGT."
    )


@pytest.mark.asyncio
async def test_awake_confirmation_precedes_immediate_reminder(monkeypatch) -> None:
    events: list[str] = []

    class Repository:
        async def start_day(self, *_args):
            events.append("start")
            return None, True

    class Reminders:
        async def tick(self):
            events.append("reminder")

    class Message:
        async def reply_text(self, text, **_kwargs):
            assert text.startswith("Your day has started.")
            events.append("confirmation")

    async def private_only(_update):
        return True

    async def require_user(_update, _context):
        return SimpleNamespace(
            telegram_user_id=123,
            name="Jun Duan",
            onboarding_step="none",
        )

    monkeypatch.setattr(bot_module, "private_only", private_only)
    monkeypatch.setattr(bot_module, "require_user", require_user)
    monkeypatch.setattr(
        bot_module,
        "components",
        lambda _context: (
            SimpleNamespace(max_awake_hours=18),
            Repository(),
            Reminders(),
        ),
    )

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123),
        effective_message=Message(),
    )
    await awake_command(update, SimpleNamespace())

    assert events == ["start", "confirmation", "reminder"]
