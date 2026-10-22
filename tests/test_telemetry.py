import json
from pathlib import Path

from lou_codi_pdf_converter import telemetry


def test_statistics_are_not_queued_without_consent(tmp_path: Path, monkeypatch) -> None:
    preferences = tmp_path / "preferences.json"
    queue = tmp_path / "events.json"
    monkeypatch.setattr(telemetry, "settings_path", lambda: preferences)
    monkeypatch.setattr(telemetry, "queue_path", lambda: queue)

    telemetry.track_event("pdf_studio", "open")

    assert not queue.exists()


def test_event_contains_no_user_or_file_identifier(tmp_path: Path, monkeypatch) -> None:
    preferences = tmp_path / "preferences.json"
    queue = tmp_path / "events.json"
    monkeypatch.setattr(telemetry, "settings_path", lambda: preferences)
    monkeypatch.setattr(telemetry, "queue_path", lambda: queue)
    telemetry.set_analytics_consent(True, preferences)

    telemetry.track_event("documents_to_pdf", "convert", format="docx", engine="lightweight")

    content = queue.read_text(encoding="utf-8")
    assert "documents_to_pdf" in content
    assert "installation_id" not in content
    assert "filename" not in content


def test_flush_requires_endpoint_and_write_token(tmp_path: Path, monkeypatch) -> None:
    preferences = tmp_path / "preferences.json"
    queue = tmp_path / "events.json"
    monkeypatch.setattr(telemetry, "settings_path", lambda: preferences)
    monkeypatch.setattr(telemetry, "queue_path", lambda: queue)
    monkeypatch.setattr(telemetry, "ANALYTICS_ENDPOINT", "https://example.invalid/exec")
    monkeypatch.setattr(telemetry, "CLIENT_TOKEN", "")
    telemetry.set_analytics_consent(True, preferences)
    queue.write_text('[{"module":"workshop","action":"open"}]', encoding="utf-8")

    assert telemetry.flush_events() is False
    assert queue.exists()


def test_flush_sends_write_token_without_document_data(tmp_path: Path, monkeypatch) -> None:
    preferences = tmp_path / "preferences.json"
    queue = tmp_path / "events.json"
    monkeypatch.setattr(telemetry, "settings_path", lambda: preferences)
    monkeypatch.setattr(telemetry, "queue_path", lambda: queue)
    monkeypatch.setattr(telemetry, "ANALYTICS_ENDPOINT", "https://example.invalid/exec")
    monkeypatch.setattr(telemetry, "CLIENT_TOKEN", "write-only-token")
    telemetry.set_analytics_consent(True, preferences)
    queue.write_text('[{"module":"workshop","action":"open"}]', encoding="utf-8")
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(outgoing, timeout: int):
        captured["body"] = outgoing.data.decode("utf-8")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", fake_urlopen)

    assert telemetry.flush_events() is True
    payload = json.loads(captured["body"])
    assert payload["client_token"] == "write-only-token"
    assert "file" not in captured["body"].lower()
    assert captured["timeout"] == 5
