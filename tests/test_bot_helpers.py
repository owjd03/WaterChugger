from datetime import UTC, datetime

from waterbot.bot import format_singapore, validate_name, validate_timezone


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
