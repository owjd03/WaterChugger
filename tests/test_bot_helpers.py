from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import waterbot.bot as bot_module
from waterbot.bot import (
    AWAKE_TEXT,
    DRINK_ENCOURAGEMENT_MESSAGES,
    END_WORKOUT_TEXT,
    SLEEP_TEXT,
    WORKOUT_TEXT,
    awake_keyboard,
    awake_command,
    drink_confirmation_message,
    end_workout_command,
    format_singapore,
    reminder_keyboard,
    sleep_command,
    sleeping_keyboard,
    validate_name,
    validate_timezone,
    workout_command,
    workout_keyboard,
)
from waterbot.messages import WORKOUT_DRINK_ENCOURAGEMENT_MESSAGES


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


def test_workout_confirmation_uses_separate_message_list(monkeypatch) -> None:
    monkeypatch.setattr(bot_module.random, "choice", lambda messages: messages[0])
    value = datetime(2026, 7, 14, 18, 30, tzinfo=UTC)

    assert drink_confirmation_message(value, is_working_out=True).startswith(
        WORKOUT_DRINK_ENCOURAGEMENT_MESSAGES[0]
    )


def test_mode_keyboards_show_only_the_expected_controls() -> None:
    assert [[button.text for button in row] for row in sleeping_keyboard().keyboard] == [
        [AWAKE_TEXT]
    ]
    assert [[button.text for button in row] for row in awake_keyboard().keyboard] == [
        [WORKOUT_TEXT, SLEEP_TEXT]
    ]
    assert [[button.text for button in row] for row in workout_keyboard().keyboard] == [
        [END_WORKOUT_TEXT]
    ]


def test_mode_specific_reminder_callbacks_are_tokenized() -> None:
    normal = reminder_keyboard("normal-token", 15, False)
    workout = reminder_keyboard("workout-token", 15, True)

    assert normal.inline_keyboard[-1][0].callback_data == "sleep:normal-token"
    assert workout.inline_keyboard[-1][0].callback_data == (
        "end_workout:workout-token"
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


@pytest.mark.asyncio
async def test_workout_transitions_send_confirmation_before_reminder(
    monkeypatch,
) -> None:
    events: list[str] = []

    class Repository:
        async def start_workout(self, *_args):
            events.append("start_workout")
            return "started"

        async def end_workout(self, *_args):
            events.append("end_workout")
            return "ended"

    class Reminders:
        async def tick(self):
            events.append("reminder")

    class Message:
        async def reply_text(self, text, **_kwargs):
            events.append("workout_confirmation" if "activated" in text else "end_confirmation")

    async def private_only(_update):
        return True

    async def require_user(_update, _context):
        return SimpleNamespace(
            telegram_user_id=123,
            is_awake=True,
            is_working_out=False,
        )

    repository = Repository()
    reminders = Reminders()
    monkeypatch.setattr(bot_module, "private_only", private_only)
    monkeypatch.setattr(bot_module, "require_user", require_user)
    monkeypatch.setattr(
        bot_module,
        "components",
        lambda _context: (
            SimpleNamespace(workout_reminder_interval_minutes=15),
            repository,
            reminders,
        ),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123), effective_message=Message()
    )

    await workout_command(update, SimpleNamespace())
    await end_workout_command(update, SimpleNamespace())

    assert events == [
        "start_workout",
        "workout_confirmation",
        "reminder",
        "end_workout",
        "end_confirmation",
        "reminder",
    ]


@pytest.mark.asyncio
async def test_sleep_command_requires_workout_to_end(monkeypatch) -> None:
    replies: list[tuple[str, object]] = []

    class Repository:
        async def stop_day(self, *_args):
            return "working_out"

    class Message:
        async def reply_text(self, text, **kwargs):
            replies.append((text, kwargs["reply_markup"]))

    async def private_only(_update):
        return True

    async def require_user(_update, _context):
        return SimpleNamespace(telegram_user_id=123)

    monkeypatch.setattr(bot_module, "private_only", private_only)
    monkeypatch.setattr(bot_module, "require_user", require_user)
    monkeypatch.setattr(
        bot_module,
        "components",
        lambda _context: (SimpleNamespace(), Repository(), SimpleNamespace()),
    )
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=123), effective_message=Message()
    )

    await sleep_command(update, SimpleNamespace())

    assert replies[0][0].startswith("Finish Pump Mode")
    assert replies[0][1].keyboard[0][0].text == END_WORKOUT_TEXT
