from __future__ import annotations

import base64
import json
import mimetypes
import shutil
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from pathlib import Path

from ..i18n import settings_path

SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/contacts.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)
KEYRING_SERVICE = "lou-codi-google-oauth"


class GoogleMailUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleAccount:
    email: str
    display_name: str = ""


@dataclass(frozen=True)
class GoogleRecipient:
    name: str
    email: str


@dataclass(frozen=True)
class GoogleContactGroup:
    resource_name: str
    name: str
    member_count: int = 0


def _load_preferences(path: Path | None = None) -> dict:
    target = path or settings_path()
    try:
        values = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return values if isinstance(values, dict) else {}


def _save_preferences(values: dict, path: Path | None = None) -> None:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


def configured_client_file(path: Path | None = None) -> Path | None:
    value = _load_preferences(path).get("google_oauth_client_file", "")
    candidate = Path(value) if value else None
    return candidate if candidate and candidate.is_file() else None


def install_client_file(source: Path, path: Path | None = None) -> Path:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Le fichier OAuth Google n’est pas un JSON valide.") from exc
    if not isinstance(payload, dict) or not ({"installed", "web"} & payload.keys()):
        raise ValueError("Ce fichier n’est pas un identifiant client OAuth Google.")
    destination = (path or settings_path()).parent / "google-oauth-client.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o600)
    values = _load_preferences(path)
    values["google_oauth_client_file"] = str(destination)
    _save_preferences(values, path)
    return destination


def list_accounts(path: Path | None = None) -> list[GoogleAccount]:
    raw = _load_preferences(path).get("google_accounts", [])
    if not isinstance(raw, list):
        return []
    accounts = []
    for value in raw:
        if isinstance(value, dict) and value.get("email"):
            accounts.append(GoogleAccount(str(value["email"]), str(value.get("display_name", ""))))
    return accounts


def active_account(path: Path | None = None) -> str:
    return str(_load_preferences(path).get("active_google_account", ""))


def set_active_account(email: str, path: Path | None = None) -> None:
    values = _load_preferences(path)
    values["active_google_account"] = email
    _save_preferences(values, path)


def _dependencies():
    try:
        import keyring
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleMailUnavailable(
            "Les composants Google de Lou Còdi ne sont pas installés dans ce paquet."
        ) from exc
    return keyring, Credentials, InstalledAppFlow, build


def connect_account(path: Path | None = None) -> GoogleAccount:
    client_file = configured_client_file(path)
    if client_file is None:
        raise GoogleMailUnavailable("Configurez d’abord le fichier client OAuth Google.")
    keyring, _credentials, InstalledAppFlow, build = _dependencies()
    credentials = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES).run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message="Ouverture de Google…",
        prompt="select_account",
    )
    oauth = build("oauth2", "v2", credentials=credentials, cache_discovery=False)
    profile = oauth.userinfo().get().execute()
    email = str(profile.get("email", "")).strip()
    if not email:
        raise GoogleMailUnavailable("Google n’a pas retourné l’adresse du compte connecté.")
    account = GoogleAccount(email=email, display_name=str(profile.get("name", "")))
    keyring.set_password(KEYRING_SERVICE, email, credentials.to_json())
    values = _load_preferences(path)
    accounts = [item for item in list_accounts(path) if item.email != email] + [account]
    values["google_accounts"] = [asdict(item) for item in accounts]
    values["active_google_account"] = email
    _save_preferences(values, path)
    return account


def disconnect_account(email: str, path: Path | None = None) -> None:
    keyring, *_ = _dependencies()
    try:
        keyring.delete_password(KEYRING_SERVICE, email)
    except keyring.errors.PasswordDeleteError:
        pass
    values = _load_preferences(path)
    accounts = [item for item in list_accounts(path) if item.email != email]
    values["google_accounts"] = [asdict(item) for item in accounts]
    if values.get("active_google_account") == email:
        values["active_google_account"] = accounts[0].email if accounts else ""
    _save_preferences(values, path)


def credentials_for(email: str):
    keyring, Credentials, *_ = _dependencies()
    token = keyring.get_password(KEYRING_SERVICE, email)
    if not token:
        raise GoogleMailUnavailable("Ce compte doit être reconnecté à Google.")
    return Credentials.from_authorized_user_info(json.loads(token), SCOPES)


def list_contacts(email: str) -> list[GoogleRecipient]:
    *_, build = _dependencies()
    service = build("people", "v1", credentials=credentials_for(email), cache_discovery=False)
    recipients: dict[str, GoogleRecipient] = {}
    token = None
    while True:
        response = service.people().connections().list(
            resourceName="people/me", personFields="names,emailAddresses", pageSize=1000,
            pageToken=token,
        ).execute()
        for person in response.get("connections", []):
            name = next((item.get("displayName", "") for item in person.get("names", [])), "")
            for address in person.get("emailAddresses", []):
                value = str(address.get("value", "")).strip()
                if value:
                    recipients[value.casefold()] = GoogleRecipient(name=name, email=value)
        token = response.get("nextPageToken")
        if not token:
            return sorted(recipients.values(), key=lambda item: (item.name.casefold(), item.email.casefold()))


def list_contact_groups(email: str) -> list[GoogleContactGroup]:
    *_, build = _dependencies()
    service = build("people", "v1", credentials=credentials_for(email), cache_discovery=False)
    response = service.contactGroups().list(pageSize=1000).execute()
    return sorted((
        GoogleContactGroup(
            resource_name=str(group.get("resourceName", "")),
            name=str(group.get("name", "")),
            member_count=int(group.get("memberCount", 0)),
        )
        for group in response.get("contactGroups", []) if group.get("resourceName")
    ), key=lambda item: item.name.casefold())


def group_members(email: str, resource_name: str) -> list[GoogleRecipient]:
    *_, build = _dependencies()
    service = build("people", "v1", credentials=credentials_for(email), cache_discovery=False)
    group = service.contactGroups().get(resourceName=resource_name, maxMembers=1000).execute()
    names = group.get("memberResourceNames", [])
    if not names:
        return []
    response = service.people().getBatchGet(
        resourceNames=names, personFields="names,emailAddresses"
    ).execute()
    recipients = []
    for result in response.get("responses", []):
        person = result.get("person", {})
        name = next((item.get("displayName", "") for item in person.get("names", [])), "")
        address = next((item.get("value", "") for item in person.get("emailAddresses", [])), "")
        if address:
            recipients.append(GoogleRecipient(name=name, email=address))
    return sorted(recipients, key=lambda item: (item.name.casefold(), item.email.casefold()))


def send_pdf(
    account_email: str,
    recipients: list[str],
    subject: str,
    body: str,
    attachment: Path,
) -> str:
    if not recipients:
        raise ValueError("Choisissez au moins un destinataire.")
    *_, build = _dependencies()
    message = EmailMessage()
    message["From"] = account_email
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    mime, _encoding = mimetypes.guess_type(attachment.name)
    maintype, subtype = (mime or "application/pdf").split("/", 1)
    message.add_attachment(
        attachment.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment.name
    )
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    service = build("gmail", "v1", credentials=credentials_for(account_email), cache_discovery=False)
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return str(result.get("id", ""))
