from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .i18n import settings_path

SUPPORT_URL = "https://ko-fi.com/P8J628V34K"
REMINDER_EVERY_LAUNCHES = 20


@dataclass(frozen=True)
class LaunchState:
    launch_count: int
    show_welcome: bool
    show_support_reminder: bool


def _read_preferences(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_preferences(path: Path, preferences: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")


def register_launch(path: Path | None = None) -> LaunchState:
    """Record one application launch and decide which information should be shown."""
    target = path or settings_path()
    preferences = _read_preferences(target)
    try:
        launch_count = max(0, int(preferences.get("launch_count", 0))) + 1
    except (TypeError, ValueError):
        launch_count = 1

    welcome_seen = bool(preferences.get("welcome_seen", False))
    reminders_enabled = bool(preferences.get("support_reminders_enabled", True))
    try:
        last_reminder = max(0, int(preferences.get("last_support_reminder", 0)))
    except (TypeError, ValueError):
        last_reminder = 0

    reminder_due = (
        welcome_seen
        and reminders_enabled
        and launch_count >= REMINDER_EVERY_LAUNCHES
        and launch_count - last_reminder >= REMINDER_EVERY_LAUNCHES
    )
    preferences["launch_count"] = launch_count
    _write_preferences(target, preferences)
    return LaunchState(launch_count, not welcome_seen, reminder_due)


def mark_welcome_seen(path: Path | None = None) -> None:
    target = path or settings_path()
    preferences = _read_preferences(target)
    preferences["welcome_seen"] = True
    _write_preferences(target, preferences)


def mark_support_reminder_shown(
    launch_count: int,
    *,
    disable_future_reminders: bool = False,
    path: Path | None = None,
) -> None:
    target = path or settings_path()
    preferences = _read_preferences(target)
    preferences["last_support_reminder"] = max(0, launch_count)
    if disable_future_reminders:
        preferences["support_reminders_enabled"] = False
    _write_preferences(target, preferences)
