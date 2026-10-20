from __future__ import annotations

import json
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote

from ..i18n import settings_path


@dataclass
class EmailSettings:
    recipient: str = ""
    subject: str = "Document {document}"
    body: str = "Bonjour,\n\nVeuillez trouver le document en pièce jointe.\n"
    signature: str = ""


def load_email_settings(path: Path | None = None) -> EmailSettings:
    target = path or settings_path()
    try:
        values = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return EmailSettings()
    raw = values.get("document_email", {}) if isinstance(values, dict) else {}
    if not isinstance(raw, dict):
        return EmailSettings()
    return EmailSettings(**{
        field: str(raw.get(field, getattr(EmailSettings(), field)))
        for field in ("recipient", "subject", "body", "signature")
    })


def save_email_settings(settings: EmailSettings, path: Path | None = None) -> None:
    target = path or settings_path()
    try:
        values = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    values["document_email"] = asdict(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


def prepared_message(settings: EmailSettings, document_name: str) -> tuple[str, str]:
    subject = settings.subject.replace("{document}", document_name)
    body = settings.body.replace("{document}", document_name).rstrip()
    if settings.signature.strip():
        body += "\n\n" + settings.signature.strip()
    return subject, body


def email_command(settings: EmailSettings, attachment: Path) -> list[str] | None:
    subject, body = prepared_message(settings, attachment.stem)
    if sys.platform != "win32" and sys.platform != "darwin" and shutil.which("xdg-email"):
        command = ["xdg-email", "--attach", str(attachment), "--subject", subject, "--body", body]
        if settings.recipient.strip():
            command.append(settings.recipient.strip())
        return command
    return None


def open_email_draft(settings: EmailSettings, attachment: Path) -> bool:
    """Open a reviewed draft. This function never sends a message."""
    command = email_command(settings, attachment)
    if command is not None:
        subprocess.Popen(command, start_new_session=True)
        return True
    subject, body = prepared_message(settings, attachment.stem)
    mailto = (
        f"mailto:{quote(settings.recipient.strip())}?subject={quote(subject)}&body={quote(body)}"
    )
    return webbrowser.open(mailto, new=2)
