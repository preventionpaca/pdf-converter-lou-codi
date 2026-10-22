from __future__ import annotations

import json
import os
from pathlib import Path


def endpoint() -> str:
    return _value("LOU_CODI_SERVICE_URL", "endpoint")


def client_token() -> str:
    return _value("LOU_CODI_CLIENT_TOKEN", "client_token")


def _value(environment_name: str, config_name: str) -> str:
    environment = os.environ.get(environment_name, "").strip()
    if environment:
        return environment
    try:
        payload = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(payload.get(config_name, "")).strip() if isinstance(payload, dict) else ""


def config_path() -> Path:
    return Path(__file__).with_name("assets") / "service-config.json"
