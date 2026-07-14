from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Step(str, Enum):
    NONE = "none"
    NAME = "name"
    NAME_UPDATE = "name_update"
    TIMEZONE = "timezone"


@dataclass(slots=True)
class Profile:
    user_id: int
    chat_id: int
    name: str | None = None
    timezone: str | None = None
    step: Step = Step.NONE

    @property
    def complete(self) -> bool:
        return bool(self.name and self.timezone)


@dataclass(slots=True)
class GuestReminder:
    id: str
    scheduled_at: datetime
    confirmed: bool = False
    snoozed: bool = False


@dataclass(slots=True)
class GuestSession:
    awake_at: datetime
    stop_at: datetime
    next_due_at: datetime
    active: bool = True
    reminders: dict[str, GuestReminder] = field(default_factory=dict)
    current_reminder_id: str | None = None

    @classmethod
    def start(cls, now: datetime, max_awake_hours: int) -> "GuestSession":
        return cls(awake_at=now, stop_at=now + timedelta(hours=max_awake_hours), next_due_at=now)

    def claim_due(self, now: datetime, interval_minutes: int) -> GuestReminder | None:
        if not self.active or now < self.next_due_at:
            return None
        if now >= self.stop_at:
            self.active = False
            return None
        reminder = GuestReminder(id=str(uuid.uuid4()), scheduled_at=self.next_due_at)
        self.reminders[reminder.id] = reminder
        self.current_reminder_id = reminder.id
        self.next_due_at = now + timedelta(minutes=interval_minutes)
        return reminder

    def snooze(self, reminder_id: str, now: datetime, snooze_minutes: int) -> bool:
        reminder = self.reminders.get(reminder_id)
        if (
            not self.active
            or reminder is None
            or reminder.confirmed
            or reminder.snoozed
            or self.current_reminder_id != reminder_id
        ):
            return False
        reminder.snoozed = True
        self.next_due_at = now + timedelta(minutes=snooze_minutes)
        return True

    def confirm(self, reminder_id: str) -> bool:
        reminder = self.reminders.get(reminder_id)
        if reminder is None or reminder.confirmed:
            return False
        reminder.confirmed = True
        return True

    def stop(self) -> bool:
        was_active = self.active
        self.active = False
        return was_active


class RuntimeState:
    def __init__(self) -> None:
        self.profiles: dict[int, Profile] = {}
        self.guest_sessions: dict[int, GuestSession] = {}

    def profile(self, user_id: int, chat_id: int) -> Profile:
        profile = self.profiles.get(user_id)
        if profile is None:
            profile = Profile(user_id=user_id, chat_id=chat_id)
            self.profiles[user_id] = profile
        else:
            profile.chat_id = chat_id
        return profile
