from __future__ import annotations

import logging
from dataclasses import dataclass
from os import getenv

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


def _positive_int(name: str, default: int) -> int:
    raw = getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Config:
    telegram_token: str
    database_url: str
    reminder_interval_minutes: int = 60
    snooze_minutes: int = 15
    max_awake_hours: int = 18
    idle_expiry_hours: int = 24
    cleanup_interval_seconds: int = 300
    scheduler_interval_seconds: int = 15
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token or token == "replace_with_your_bot_token":
            raise ConfigError("TELEGRAM_BOT_TOKEN is required")

        database_url = normalize_database_url(getenv("DATABASE_URL", "").strip())
        if not database_url:
            raise ConfigError("DATABASE_URL is required")

        log_level = getenv("LOG_LEVEL", "INFO").upper()
        if log_level not in logging.getLevelNamesMapping():
            raise ConfigError("LOG_LEVEL is not a recognized Python logging level")

        return cls(
            telegram_token=token,
            database_url=database_url,
            reminder_interval_minutes=_positive_int("REMINDER_INTERVAL_MINUTES", 60),
            snooze_minutes=_positive_int("SNOOZE_MINUTES", 15),
            max_awake_hours=_positive_int("MAX_AWAKE_HOURS", 18),
            idle_expiry_hours=_positive_int("IDLE_EXPIRY_HOURS", 24),
            cleanup_interval_seconds=_positive_int("CLEANUP_INTERVAL_SECONDS", 300),
            scheduler_interval_seconds=_positive_int("SCHEDULER_INTERVAL_SECONDS", 15),
            log_level=log_level,
        )


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url
