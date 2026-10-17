from __future__ import annotations

import json
import os
import platform
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .i18n import settings_path
from .paths import application_data_directory

ANALYTICS_ENDPOINT = os.environ.get("LOU_CODI_ANALYTICS_URL", "").strip()
QUEUE_LIMIT = 200


def analytics_consent(path: Path | None = None) -> bool | None:
    preferences = _read_json(path or settings_path(), {})
    value = preferences.get("anonymous_usage_statistics")
    return value if isinstance(value, bool) else None


def set_analytics_consent(enabled: bool, path: Path | None = None) -> None:
    target = path or settings_path()
    preferences = _read_json(target, {})
    preferences["anonymous_usage_statistics"] = bool(enabled)
    _write_json(target, preferences)
    if not enabled:
        queue_path().unlink(missing_ok=True)


def track_event(module: str, action: str, result: str = "ok", **dimensions: str) -> None:
    """Queue a deliberately non-identifying usage event after explicit consent."""
    if analytics_consent() is not True:
        return
    event = {
        "time": datetime.now(UTC).replace(minute=0, second=0, microsecond=0).isoformat(),
        "app_version": __version__,
        "os": platform.system().lower(),
        "module": _safe(module),
        "action": _safe(action),
        "result": _safe(result),
        "dimensions": {key: _safe(value) for key, value in dimensions.items()},
    }
    target = queue_path()
    events = _read_json(target, [])
    if not isinstance(events, list):
        events = []
    events.append(event)
    _write_json(target, events[-QUEUE_LIMIT:])
    if ANALYTICS_ENDPOINT:
        threading.Thread(target=flush_events, daemon=True).start()


def flush_events() -> bool:
    if analytics_consent() is not True or not ANALYTICS_ENDPOINT:
        return False
    target = queue_path()
    events = _read_json(target, [])
    if not isinstance(events, list) or not events:
        return True
    body = json.dumps({"events": events}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        ANALYTICS_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "LouCodiWorkshop"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if not 200 <= response.status < 300:
                return False
    except OSError:
        return False
    target.unlink(missing_ok=True)
    return True


def queue_path() -> Path:
    return application_data_directory() / "anonymous-usage-events.json"


def _safe(value: object) -> str:
    return str(value).replace("/", "_").replace("\\", "_")[:80]


def _read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
