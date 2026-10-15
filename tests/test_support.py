import json

from lou_codi_pdf_converter.support import (
    REMINDER_EVERY_LAUNCHES,
    mark_support_reminder_shown,
    mark_welcome_seen,
    register_launch,
)


def test_welcome_is_only_requested_until_seen(tmp_path) -> None:
    settings = tmp_path / "preferences.json"
    first = register_launch(settings)
    assert first.show_welcome
    assert not first.show_support_reminder

    mark_welcome_seen(settings)
    second = register_launch(settings)
    assert not second.show_welcome
    assert not second.show_support_reminder


def test_support_reminder_is_due_every_twenty_launches(tmp_path) -> None:
    settings = tmp_path / "preferences.json"
    mark_welcome_seen(settings)
    state = None
    for _ in range(REMINDER_EVERY_LAUNCHES):
        state = register_launch(settings)
    assert state is not None and state.show_support_reminder

    mark_support_reminder_shown(state.launch_count, path=settings)
    assert not register_launch(settings).show_support_reminder
    for _ in range(REMINDER_EVERY_LAUNCHES - 1):
        state = register_launch(settings)
    assert state is not None and state.show_support_reminder


def test_user_can_disable_future_support_reminders(tmp_path) -> None:
    settings = tmp_path / "preferences.json"
    mark_welcome_seen(settings)
    for _ in range(REMINDER_EVERY_LAUNCHES):
        state = register_launch(settings)
    mark_support_reminder_shown(
        state.launch_count,
        disable_future_reminders=True,
        path=settings,
    )
    for _ in range(REMINDER_EVERY_LAUNCHES * 2):
        state = register_launch(settings)
    assert not state.show_support_reminder
    assert json.loads(settings.read_text(encoding="utf-8"))["support_reminders_enabled"] is False
