from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import shutil
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from ..i18n import settings_path

SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts.other.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)
KEYRING_SERVICE = "lou-codi-google-oauth"
DRIVE_LINK_INDEX_NAME = "Lou Còdi Espace — liens.json"
DRIVE_SPACE_INDEX_SUFFIX = ".loucodi-espace"


def drive_space_index_name(space_title: str) -> str:
    """Return a portable, human-readable filename for a shared space index."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", space_title).strip().rstrip(".")
    return f"{cleaned or 'Espace Lou Còdi'}{DRIVE_SPACE_INDEX_SUFFIX}"


def _drive_query_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


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


@dataclass(frozen=True)
class GmailMessageChoice:
    subject: str
    correspondent: str
    date: str = ""


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
    information = json.loads(token)
    granted = information.get("scopes", []) if isinstance(information, dict) else []
    if isinstance(granted, str):
        granted = granted.split()
    if granted and not set(SCOPES).issubset(set(granted)):
        raise GoogleMailUnavailable(
            "Les autorisations Google de ce compte sont anciennes. Cliquez sur « + Compte », "
            "sélectionnez de nouveau ce compte et acceptez l’accès aux contacts, à Google Drive "
            "et la lecture des informations de vos courriels."
        )
    return Credentials.from_authorized_user_info(information, SCOPES)


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
            break
    token = None
    while True:
        response = service.otherContacts().list(
            readMask="names,emailAddresses", pageSize=1000, pageToken=token,
        ).execute()
        for person in response.get("otherContacts", []):
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


@dataclass(frozen=True)
class GoogleDriveItem:
    identifier: str
    name: str
    mime_type: str
    web_url: str


def list_drive_folder(email: str, folder_id: str) -> list[GoogleDriveItem]:
    *_, build = _dependencies()
    service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
    items: list[GoogleDriveItem] = []
    token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken, files(id,name,mimeType,webViewLink)",
            orderBy="folder,name_natural",
            pageSize=1000,
            pageToken=token,
        ).execute()
        for item in response.get("files", []):
            identifier = str(item.get("id", ""))
            name = str(item.get("name", ""))
            if identifier and name != DRIVE_LINK_INDEX_NAME and not name.endswith(DRIVE_SPACE_INDEX_SUFFIX):
                items.append(
                    GoogleDriveItem(
                        identifier=identifier,
                        name=str(item.get("name", identifier)),
                        mime_type=str(item.get("mimeType", "")),
                        web_url=str(item.get("webViewLink", ""))
                        or f"https://drive.google.com/open?id={identifier}",
                    )
                )
        token = response.get("nextPageToken")
        if not token:
            return items


def read_drive_file(email: str, file_id: str) -> bytes:
    """Download a regular Drive file for local viewing without changing it."""
    *_, build = _dependencies()
    service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
    return bytes(service.files().get_media(fileId=file_id).execute())


def upload_drive_file(email: str, folder_id: str, source: Path) -> GoogleDriveItem:
    from googleapiclient.http import MediaFileUpload

    *_, build = _dependencies()
    service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
    media = MediaFileUpload(
        str(source), mimetype=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
        resumable=source.stat().st_size > 5 * 1024 * 1024,
    )
    item = service.files().create(
        body={"name": source.name, "parents": [folder_id]},
        media_body=media,
        fields="id,name,mimeType,webViewLink",
    ).execute()
    identifier = str(item["id"])
    return GoogleDriveItem(
        identifier=identifier,
        name=str(item.get("name", source.name)),
        mime_type=str(item.get("mimeType", "application/octet-stream")),
        web_url=str(item.get("webViewLink", "")) or f"https://drive.google.com/open?id={identifier}",
    )


def load_drive_link_index(email: str, folder_id: str, space_title: str) -> list[dict]:
    *_, build = _dependencies()
    service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
    filename = drive_space_index_name(space_title)
    names = (filename, DRIVE_LINK_INDEX_NAME)
    files = []
    for name in names:
        response = service.files().list(
            q=f"'{folder_id}' in parents and name = '{_drive_query_text(name)}' and trashed = false",
            fields="files(id)", pageSize=1,
        ).execute()
        files = response.get("files", [])
        if files:
            break
    if not files:
        return []
    payload = service.files().get_media(fileId=files[0]["id"]).execute()
    try:
        decoded = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    except (UnicodeDecodeError, ValueError, TypeError):
        return []
    return decoded.get("resources", []) if isinstance(decoded, dict) else []


def save_drive_link_index(
    email: str,
    folder_id: str,
    space_title: str,
    space_id: str,
    space_group: str,
    parent_id: str,
    resources: list[dict],
) -> None:
    from googleapiclient.http import MediaIoBaseUpload

    *_, build = _dependencies()
    service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
    filename = drive_space_index_name(space_title)
    files = []
    for name in (filename, DRIVE_LINK_INDEX_NAME):
        response = service.files().list(
            q=f"'{folder_id}' in parents and name = '{_drive_query_text(name)}' and trashed = false",
            fields="files(id)", pageSize=1,
        ).execute()
        files = response.get("files", [])
        if files:
            break
    content = json.dumps(
        {
            "version": 2,
            "space_id": space_id,
            "space_title": space_title,
            "group": space_group,
            "parent_id": parent_id,
            "account_email": email,
            "drive_folder_id": folder_id,
            "resources": resources,
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json", resumable=False)
    if files:
        service.files().update(
            fileId=files[0]["id"], body={"name": filename}, media_body=media,
        ).execute()
    else:
        service.files().create(
            body={"name": filename, "parents": [folder_id]}, media_body=media,
        ).execute()


def check_drive_access(email: str) -> None:
    """Validate the local authorization and the shared Drive API configuration."""
    *_, build = _dependencies()
    service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
    service.about().get(fields="user(permissionId)").execute()


def _google_file_id(target: str) -> str:
    for pattern in (r"/d/([A-Za-z0-9_-]+)", r"/folders/([A-Za-z0-9_-]+)"):
        match = re.search(pattern, target)
        if match:
            return match.group(1)
    return ""


def _gmail_item_id(target: str) -> str:
    fragment = urlparse(target).fragment
    return fragment.rstrip("/").rsplit("/", 1)[-1] if fragment else ""


def _header_value(headers: list[dict], name: str) -> str:
    return next(
        (
            str(item.get("value", ""))
            for item in headers
            if item.get("name", "").casefold() == name.casefold()
        ),
        "",
    )


def google_resource_metadata(email: str, kind: str, target: str) -> tuple[str, str]:
    """Resolve a display title and optional correspondent for a Google resource."""
    *_, build = _dependencies()
    if kind in {"google_drive_folder", "google_drive_document", "google_sheets"}:
        identifier = _google_file_id(target)
        if identifier:
            service = build("drive", "v3", credentials=credentials_for(email), cache_discovery=False)
            item = service.files().get(fileId=identifier, fields="name").execute()
            return str(item.get("name", "")), ""
    if kind == "gmail_message":
        identifier = _gmail_item_id(target)
        if identifier:
            service = build("gmail", "v1", credentials=credentials_for(email), cache_discovery=False)
            try:
                thread = service.users().threads().get(
                    userId="me", id=identifier, format="metadata",
                    metadataHeaders=["Subject", "From", "To"],
                ).execute()
                messages = thread.get("messages", [])
                item = messages[-1] if messages else {}
            except Exception:  # noqa: BLE001 - the URL may contain a message id instead.
                item = service.users().messages().get(
                    userId="me", id=identifier, format="metadata",
                    metadataHeaders=["Subject", "From", "To"],
                ).execute()
            headers = item.get("payload", {}).get("headers", [])
            subject = _header_value(headers, "Subject") or "Courriel sans objet"
            sender = _header_value(headers, "From")
            recipient = _header_value(headers, "To")
            correspondent = recipient if email.casefold() in sender.casefold() else sender
            return subject, correspondent
    if kind in {"google_photos_album", "web_link"}:
        request = Request(target, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=5) as response:
            page = response.read(2_000_000).decode("utf-8", errors="ignore")
        meta = next(
            (
                tag for tag in re.findall(r"<meta\b[^>]*>", page, re.IGNORECASE)
                if re.search(r'(?:property|name)=["\']og:title["\']', tag, re.IGNORECASE)
            ),
            "",
        )
        match = re.search(r'content=["\']([^"\']+)', meta, re.IGNORECASE) or re.search(
            r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL,
        )
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(), ""
    return "", ""


def gmail_query_from_target(target: str) -> str:
    """Infer the Gmail search scope represented by a browser URL."""
    fragment = urlparse(target).fragment
    decoded_fragment = unquote(fragment)
    query = "in:sent" if decoded_fragment.startswith("sent/") else "in:inbox"
    if fragment.startswith("search/"):
        search_tail = fragment[len("search/"):]
        encoded_query = search_tail.rsplit("/", 1)[0] if "/" in search_tail else search_tail
        query = unquote(encoded_query).replace("+", " ").strip() or query
    return query


def list_gmail_message_choices(
    email: str,
    target: str,
    limit: int = 100,
    query: str = "",
) -> list[GmailMessageChoice]:
    """List likely Gmail messages when a browser permalink uses a non-API identifier."""
    *_, build = _dependencies()
    service = build("gmail", "v1", credentials=credentials_for(email), cache_discovery=False)
    search_query = query.strip() or gmail_query_from_target(target)
    result = service.users().messages().list(
        userId="me", q=search_query, maxResults=limit,
    ).execute()
    summaries = result.get("messages", [])
    messages: dict[str, dict] = {}
    if summaries and hasattr(service, "new_batch_http_request"):
        def collect(request_id: str, response: dict | None, exception: Exception | None) -> None:
            if exception is None and response is not None:
                messages[request_id] = response

        batch = service.new_batch_http_request(callback=collect)
        for summary in summaries:
            batch.add(
                service.users().messages().get(
                    userId="me", id=summary["id"], format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Date"],
                ),
                request_id=str(summary["id"]),
            )
        batch.execute()
    choices = []
    for summary in summaries:
        item = messages.get(str(summary["id"]))
        if item is None:
            item = service.users().messages().get(
                userId="me", id=summary["id"], format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date"],
            ).execute()
        headers = item.get("payload", {}).get("headers", [])
        subject = _header_value(headers, "Subject") or "Courriel sans objet"
        sender = _header_value(headers, "From")
        recipient = _header_value(headers, "To")
        correspondent = recipient if email.casefold() in sender.casefold() else sender
        choices.append(GmailMessageChoice(subject, correspondent, _header_value(headers, "Date")))
    return choices


def google_resource_title(email: str, kind: str, target: str) -> str:
    """Backward-compatible title-only metadata accessor."""
    return google_resource_metadata(email, kind, target)[0]


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
