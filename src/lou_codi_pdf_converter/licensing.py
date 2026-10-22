from __future__ import annotations

import json
import os
import platform
import urllib.request
import uuid
from pathlib import Path

from . import __version__
from .paths import application_data_directory

SERVICE_ENDPOINT = os.environ.get("LOU_CODI_SERVICE_URL", "").strip()


def service_configured() -> bool:
    return SERVICE_ENDPOINT.startswith("https://")


def license_state(path: Path | None = None) -> dict[str, object]:
    return _read_json(path or state_path(), {})


def is_activated(path: Path | None = None) -> bool:
    state = license_state(path)
    return bool(state.get("activated") and state.get("license_key"))


def request_free_license(email: str) -> str:
    response = _post({"action": "request_license", "email": email})
    return str(response.get("message", "La licence a été envoyée."))


def activate(email: str, license_key: str, path: Path | None = None) -> dict[str, object]:
    response = _post(
        {
            "action": "activate",
            "email": email,
            "license_key": license_key,
            "installation_id": installation_id(),
            "os": platform.system().lower(),
            "app_version": __version__,
        }
    )
    state = {
        "activated": True,
        "email": email.strip().lower(),
        "license_key": license_key.strip().upper(),
        "slots_used": int(response.get("slots_used", 1)),
    }
    _write_json(path or state_path(), state)
    return state


def deactivate(path: Path | None = None) -> None:
    target = path or state_path()
    state = license_state(target)
    if state.get("license_key") and service_configured():
        _post(
            {
                "action": "deactivate",
                "license_key": state["license_key"],
                "installation_id": installation_id(),
            }
        )
    target.unlink(missing_ok=True)


def installation_id(path: Path | None = None) -> str:
    target = path or installation_path()
    try:
        existing = target.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    value = str(uuid.uuid4())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")
    return value


def state_path() -> Path:
    return application_data_directory() / "license.json"


def installation_path() -> Path:
    return application_data_directory() / "installation-id"


def _post(payload: dict[str, object]) -> dict[str, object]:
    if not service_configured():
        raise RuntimeError("Le service de licences n’est pas encore configuré dans cette version.")
    request = urllib.request.Request(
        SERVICE_ENDPOINT,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "LouCodiWorkshop"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Le service de licences est momentanément indisponible.") from exc
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error", "Activation refusée.")))
    return result


def _read_json(path: Path, fallback: dict[str, object]) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback
    return value if isinstance(value, dict) else fallback


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
