import pytest

from waterbot.config import Config, ConfigError, normalize_database_url


def base_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:testing-token")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://waterchugger:password@localhost/waterchugger",
    )


def test_config_uses_privacy_first_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    base_environment(monkeypatch)
    config = Config.from_env()
    assert config.reminder_interval_minutes == 60
    assert config.workout_reminder_interval_minutes == 15
    assert config.snooze_minutes == 15
    assert config.max_awake_hours == 18
    assert config.idle_expiry_hours == 24


def test_missing_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        Config.from_env()


def test_missing_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    base_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "")
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        Config.from_env()


def test_invalid_interval_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    base_environment(monkeypatch)
    monkeypatch.setenv("REMINDER_INTERVAL_MINUTES", "zero")
    with pytest.raises(ConfigError, match="integer"):
        Config.from_env()


def test_non_positive_interval_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    base_environment(monkeypatch)
    monkeypatch.setenv("REMINDER_INTERVAL_MINUTES", "0")
    with pytest.raises(ConfigError, match="greater than zero"):
        Config.from_env()


def test_railway_database_url_is_normalized() -> None:
    assert (
        normalize_database_url("postgresql://user:pass@db/name")
        == "postgresql+asyncpg://user:pass@db/name"
    )
