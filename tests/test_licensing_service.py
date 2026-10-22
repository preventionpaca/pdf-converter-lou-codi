import json
from pathlib import Path

from lou_codi_pdf_converter import licensing


def test_installation_identifier_is_stable(tmp_path: Path) -> None:
    target = tmp_path / "installation-id"
    first = licensing.installation_id(target)
    second = licensing.installation_id(target)
    assert first == second
    assert len(first) == 36


def test_activation_is_persisted(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "license.json"
    monkeypatch.setattr(licensing, "installation_id", lambda: "installation-test")
    monkeypatch.setattr(
        licensing,
        "_post",
        lambda payload: {"ok": True, "activated": True, "slots_used": 2},
    )
    state = licensing.activate("TEST@example.org", "lc-test", target)
    assert state["email"] == "test@example.org"
    assert state["license_key"] == "LC-TEST"
    assert json.loads(target.read_text(encoding="utf-8"))["slots_used"] == 2


def test_service_is_disabled_without_https_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(licensing, "SERVICE_ENDPOINT", "")
    assert licensing.service_configured() is False
