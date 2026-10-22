import json
from pathlib import Path

from lou_codi_pdf_converter import service_config


def test_packaged_service_configuration_is_used_without_environment(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "service-config.json"
    target.write_text(
        json.dumps({"endpoint": "https://example.invalid/exec", "client_token": "write-token"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("LOU_CODI_SERVICE_URL", raising=False)
    monkeypatch.delenv("LOU_CODI_CLIENT_TOKEN", raising=False)
    monkeypatch.setattr(service_config, "config_path", lambda: target)

    assert service_config.endpoint() == "https://example.invalid/exec"
    assert service_config.client_token() == "write-token"


def test_environment_overrides_packaged_configuration(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "service-config.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(service_config, "config_path", lambda: target)
    monkeypatch.setenv("LOU_CODI_SERVICE_URL", "https://override.invalid/exec")
    monkeypatch.setenv("LOU_CODI_CLIENT_TOKEN", "override-token")

    assert service_config.endpoint() == "https://override.invalid/exec"
    assert service_config.client_token() == "override-token"
