from waterbot.bot import validate_name, validate_timezone


def test_name_validation() -> None:
    assert validate_name("  Ada   Lovelace ") == "Ada Lovelace"
    assert validate_name("") is None
    assert validate_name("x" * 51) is None


def test_timezone_validation() -> None:
    assert validate_timezone("Asia/Singapore") == "Asia/Singapore"
    assert validate_timezone("Not/A_Timezone") is None

