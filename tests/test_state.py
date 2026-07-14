from datetime import UTC, datetime, timedelta

from waterbot.state import GuestSession


NOW = datetime(2026, 7, 14, 0, 0, tzinfo=UTC)


def test_guest_hourly_schedule_and_confirm_are_idempotent() -> None:
    session = GuestSession.start(NOW, max_awake_hours=18)

    first = session.claim_due(NOW, interval_minutes=60)
    assert first is not None
    assert session.next_due_at == NOW + timedelta(minutes=60)
    assert session.confirm(first.id) is True
    assert session.confirm(first.id) is False


def test_snooze_delays_current_reminder_and_resets_hourly_cadence() -> None:
    session = GuestSession.start(NOW, max_awake_hours=18)
    first = session.claim_due(NOW, interval_minutes=60)
    assert first is not None

    assert session.snooze(first.id, NOW, snooze_minutes=15) is True
    assert session.next_due_at == NOW + timedelta(minutes=15)
    assert session.claim_due(NOW + timedelta(minutes=14), 60) is None

    snoozed = session.claim_due(NOW + timedelta(minutes=15), 60)
    assert snoozed is not None
    assert session.next_due_at == NOW + timedelta(minutes=75)
    assert session.snooze(first.id, NOW, 15) is False


def test_session_stops_after_max_awake_window() -> None:
    session = GuestSession.start(NOW, max_awake_hours=18)
    assert session.claim_due(NOW + timedelta(hours=18), 60) is None
    assert session.active is False
