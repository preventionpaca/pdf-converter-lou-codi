import base64
import json
import os
from email import message_from_bytes
from pathlib import Path

import pytest

from lou_codi_pdf_converter.services.google_mail import (
    active_account,
    configured_client_file,
    install_client_file,
    list_accounts,
    list_contacts,
    send_pdf,
    set_active_account,
)


def test_install_oauth_client_copies_private_configuration(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    source = tmp_path / "client.json"
    source.write_text(json.dumps({"installed": {"client_id": "example"}}), encoding="utf-8")

    installed = install_client_file(source, settings)

    assert installed != source
    assert installed.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert configured_client_file(settings) == installed
    if os.name != "nt":
        assert installed.stat().st_mode & 0o077 == 0


def test_rejects_unrelated_json_as_oauth_client(tmp_path: Path) -> None:
    source = tmp_path / "other.json"
    source.write_text(json.dumps({"hello": "world"}), encoding="utf-8")

    with pytest.raises(ValueError, match="identifiant client OAuth"):
        install_client_file(source, tmp_path / "settings.json")


def test_active_account_is_independent_from_account_metadata(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "google_accounts": [
            {"email": "pro@example.org", "display_name": "Compte pro"},
            {"email": "perso@gmail.com", "display_name": "Compte perso"},
        ]
    }), encoding="utf-8")

    set_active_account("perso@gmail.com", settings)

    assert active_account(settings) == "perso@gmail.com"
    assert [account.email for account in list_accounts(settings)] == [
        "pro@example.org", "perso@gmail.com"
    ]


def test_send_pdf_builds_gmail_message_with_attachment(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class Request:
        def execute(self):
            return {"id": "gmail-message-1"}

    class Messages:
        def send(self, *, userId, body):
            captured.update(user_id=userId, raw=body["raw"])
            return Request()

    class Users:
        def messages(self):
            return Messages()

    class Gmail:
        def users(self):
            return Users()

    def build(api, version, **_kwargs):
        assert (api, version) == ("gmail", "v1")
        return Gmail()

    monkeypatch.setattr(
        "lou_codi_pdf_converter.services.google_mail._dependencies",
        lambda: (None, None, None, build),
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.services.google_mail.credentials_for", lambda _email: object()
    )
    attachment = tmp_path / "document.pdf"
    attachment.write_bytes(b"%PDF-test")

    message_id = send_pdf(
        "pro@gmail.com", ["a@yahoo.fr", "b@example.org"], "Documents", "Bonjour", attachment
    )

    parsed = message_from_bytes(base64.urlsafe_b64decode(captured["raw"]))
    assert message_id == "gmail-message-1"
    assert captured["user_id"] == "me"
    assert parsed["From"] == "pro@gmail.com"
    assert parsed["To"] == "a@yahoo.fr, b@example.org"
    assert parsed["Subject"] == "Documents"
    assert parsed.get_payload()[1].get_filename() == "document.pdf"


def test_contacts_include_saved_and_other_contacts(monkeypatch) -> None:
    class Request:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class Connections:
        def list(self, **_kwargs):
            return Request({"connections": [{
                "names": [{"displayName": "Contact enregistré"}],
                "emailAddresses": [{"value": "saved@example.org"}],
            }]})

    class People:
        def connections(self):
            return Connections()

    class OtherContacts:
        def list(self, **_kwargs):
            return Request({"otherContacts": [{
                "names": [{"displayName": "Contact récent"}],
                "emailAddresses": [{"value": "recent@example.org"}],
            }]})

    class Service:
        def people(self):
            return People()

        def otherContacts(self):
            return OtherContacts()

    monkeypatch.setattr(
        "lou_codi_pdf_converter.services.google_mail._dependencies",
        lambda: (None, None, None, lambda *_args, **_kwargs: Service()),
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.services.google_mail.credentials_for", lambda _email: object()
    )

    contacts = list_contacts("pro@example.org")

    assert {contact.email for contact in contacts} == {
        "saved@example.org",
        "recent@example.org",
    }
