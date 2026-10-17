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
