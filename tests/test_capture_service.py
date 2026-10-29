from lou_codi_pdf_converter.services import capture_service


def test_service_launches_workshop_with_current_python(monkeypatch) -> None:
    launched = {}

    def fake_popen(command, **options):
        launched["command"] = command
        launched["options"] = options

    monkeypatch.setattr(capture_service.subprocess, "Popen", fake_popen)

    capture_service.launch_workshop("space-id")

    assert launched["command"][1:] == ["-m", "lou_codi_pdf_converter.app"]
    assert launched["options"]["start_new_session"] is True
