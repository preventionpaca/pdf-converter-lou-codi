import json
from pathlib import Path

from lou_codi_pdf_converter.services.email_share import (
    EmailSettings,
    email_command,
    load_email_settings,
    prepared_message,
    save_email_settings,
)


def test_email_settings_preserve_other_application_preferences(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "fr"}), encoding="utf-8")
    settings = EmailSettings("test@example.org", "Envoi {document}", "Bonjour", "Signature")

    save_email_settings(settings, path)

    assert load_email_settings(path) == settings
    assert json.loads(path.read_text(encoding="utf-8"))["language"] == "fr"


def test_prepared_message_expands_document_and_signature() -> None:
    settings = EmailSettings(subject="Document {document}", body="Voici {document}.", signature="Rudy")
    assert prepared_message(settings, "convention") == (
        "Document convention",
        "Voici convention.\n\nRudy",
    )


def test_linux_email_command_attaches_pdf(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "document.pdf"
    monkeypatch.setattr("lou_codi_pdf_converter.services.email_share.sys.platform", "linux")
    monkeypatch.setattr(
        "lou_codi_pdf_converter.services.email_share.shutil.which",
        lambda command: "/usr/bin/xdg-email" if command == "xdg-email" else None,
    )

    command = email_command(EmailSettings(recipient="a@example.org"), target)

    assert command is not None
    assert command[:3] == ["xdg-email", "--attach", str(target)]
    assert command[-1] == "a@example.org"
