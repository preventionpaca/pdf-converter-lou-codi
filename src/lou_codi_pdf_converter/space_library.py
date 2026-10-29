from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

from .paths import application_data_directory


@dataclass
class SpaceResource:
    identifier: str
    title: str
    kind: str
    target: str
    tags: list[str] = field(default_factory=list)
    account_email: str = ""
    details: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CodiSpace:
    identifier: str
    title: str
    account_email: str = ""
    drive_folder: str = ""
    tags: list[str] = field(default_factory=list)
    resources: list[SpaceResource] = field(default_factory=list)
    group: str = ""
    parent_id: str = ""
    photo_archive_folder: str = ""


def library_path() -> Path:
    return application_data_directory() / "codi-spaces.json"


def new_identifier() -> str:
    return uuid.uuid4().hex


def inbox_space(account_email: str = "") -> CodiSpace:
    return CodiSpace(identifier="inbox", title="À classer", account_email=account_email)


def space_deletion_blocker(space: CodiSpace) -> str:
    if space.identifier == "inbox":
        return "L’espace « À classer » est permanent et ne peut pas être supprimé."
    if space.resources:
        return "Retirez d’abord toutes les ressources de cet espace."
    if space.drive_folder.strip():
        return "Détachez d’abord le dossier Google Drive lié à cet espace."
    return ""


def all_tags(spaces: list[CodiSpace]) -> list[str]:
    """Return the shared tag dictionary, alphabetically and without case duplicates."""
    values: dict[str, str] = {}
    for space in spaces:
        for tag in [*space.tags, *(tag for resource in space.resources for tag in resource.tags)]:
            cleaned = tag.strip()
            if cleaned:
                values.setdefault(cleaned.casefold(), cleaned)
    return sorted(values.values(), key=str.casefold)


def ai_conversation_kind(value: str, *, knowledge: bool = False) -> str:
    """Return a stable provider-specific kind for a supported AI conversation URL."""
    host = (urlparse(value).hostname or "").casefold()
    provider = ""
    if host in {"chatgpt.com", "chat.openai.com"} or host.endswith(".chatgpt.com"):
        provider = "chatgpt"
    elif host == "claude.ai" or host.endswith(".claude.ai"):
        provider = "claude"
    elif host == "gemini.google.com" or host.endswith(".gemini.google.com"):
        provider = "gemini"
    if not provider:
        return "ai_knowledge" if knowledge else ""
    return f"ai_{provider}_knowledge" if knowledge else f"ai_{provider}_conversation"


def ai_provider_label(kind: str) -> str:
    if "chatgpt" in kind:
        return "ChatGPT"
    if "claude" in kind:
        return "Claude"
    if "gemini" in kind:
        return "Gemini"
    return "IA"


def _looks_like_conversation_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value, re.I))


def resource_from_drop(value: str, account_email: str = "") -> SpaceResource | None:
    """Convert a desktop/browser drop value into a Còdi resource."""
    raw = value.strip().strip("{}")
    if not raw:
        return None
    title_hint = ""
    embedded_url = re.search(r"https?://[^\s{}<>\"]+", raw)
    if embedded_url:
        url = embedded_url.group(0).rstrip(").,;'")
        title_hint = f"{raw[:embedded_url.start()]} {raw[embedded_url.end():]}".strip(" <>\t\r\n-—{}")
        raw = url
    if raw.startswith("file://"):
        parsed_file = urlparse(raw)
        raw = unquote(parsed_file.path)
        if parsed_file.netloc:
            raw = f"//{parsed_file.netloc}{raw}"
    candidate = Path(raw).expanduser()
    if candidate.exists():
        return SpaceResource(
            identifier=new_identifier(),
            title=candidate.name or str(candidate),
            kind="local_folder" if candidate.is_dir() else "local_file",
            target=str(candidate.resolve()),
            account_email=account_email,
        )
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        host = parsed.netloc.casefold()
        if "mail.google.com" in host:
            kind = "gmail_message"
            title = "Courriel Gmail"
        elif "docs.google.com" in host and "/spreadsheets/" in parsed.path:
            kind = "google_sheets"
            title = "Tableur Google Sheets"
        elif "drive.google.com" in host and "/folders/" in parsed.path:
            kind = "google_drive_folder"
            title = "Dossier Google Drive"
        elif "drive.google.com" in host or "docs.google.com" in host:
            kind = "google_drive_document"
            title = "Document Google Drive"
        elif "photos.google.com" in host:
            kind = "google_photos_album"
            title = "Album Google Photos"
        else:
            kind = ai_conversation_kind(raw) or "web_link"
            title = (
                f"Conversation {ai_provider_label(kind)}"
                if kind.startswith("ai_")
                else parsed.netloc or raw
            )
        return SpaceResource(
            identifier=new_identifier(),
            title=title_hint or title,
            kind=kind,
            target=raw,
            account_email=account_email,
        )
    return None


def load_spaces(path: Path | None = None) -> list[CodiSpace]:
    target = path or library_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return [inbox_space()]
    spaces: list[CodiSpace] = []
    for raw_space in payload if isinstance(payload, list) else []:
        if not isinstance(raw_space, dict) or not raw_space.get("title"):
            continue
        resources = []
        for raw_resource in raw_space.get("resources", []):
            if isinstance(raw_resource, dict) and raw_resource.get("target"):
                target_value = str(raw_resource["target"])
                kind_value = str(raw_resource.get("kind") or "link")
                inferred_kind = ai_conversation_kind(target_value)
                if kind_value in {"link", "web_link"} and inferred_kind:
                    kind_value = inferred_kind
                title_value = str(raw_resource.get("title") or target_value)
                if inferred_kind and _looks_like_conversation_identifier(title_value):
                    title_value = f"Conversation {ai_provider_label(inferred_kind)}"
                resources.append(
                    SpaceResource(
                        identifier=str(raw_resource.get("identifier") or new_identifier()),
                        title=title_value,
                        kind=kind_value,
                        target=target_value,
                        tags=[str(tag) for tag in raw_resource.get("tags", []) if str(tag).strip()],
                        account_email=str(raw_resource.get("account_email", "")),
                        details=str(raw_resource.get("details", "")),
                        created_at=str(raw_resource.get("created_at", "")),
                    )
                )
        spaces.append(
            CodiSpace(
                identifier=str(raw_space.get("identifier") or new_identifier()),
                title=str(raw_space["title"]),
                account_email=str(raw_space.get("account_email", "")),
                drive_folder=str(raw_space.get("drive_folder", "")),
                tags=[str(tag) for tag in raw_space.get("tags", []) if str(tag).strip()],
                resources=resources,
                group=str(raw_space.get("group", "")),
                parent_id=str(raw_space.get("parent_id", "")),
                photo_archive_folder=str(raw_space.get("photo_archive_folder", "")),
            )
        )
    if not any(space.identifier == "inbox" for space in spaces):
        spaces.insert(0, inbox_space())
    return spaces


def save_spaces(spaces: list[CodiSpace], path: Path | None = None) -> None:
    target = path or library_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps([asdict(space) for space in spaces], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)


def import_space_index(path: Path, spaces: list[CodiSpace]) -> CodiSpace:
    """Import or refresh a space from a downloaded ``.loucodi-espace`` index."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("space_title"):
        raise ValueError("Ce fichier d’espace Lou Còdi est incomplet ou ancien.")
    identifier = str(payload.get("space_id") or new_identifier())
    resources: list[SpaceResource] = []
    for raw in payload.get("resources", []):
        if not isinstance(raw, dict) or not raw.get("target"):
            continue
        resources.append(
            SpaceResource(
                identifier=str(raw.get("identifier") or new_identifier()),
                title=str(raw.get("title") or raw["target"]),
                kind=str(raw.get("kind") or "web_link"),
                target=str(raw["target"]),
                tags=[str(tag) for tag in raw.get("tags", []) if str(tag).strip()],
                account_email=str(raw.get("account_email") or payload.get("account_email", "")),
                details=str(raw.get("details", "")),
                created_at=str(raw.get("created_at", "")),
            )
        )
    imported = CodiSpace(
        identifier=identifier,
        title=str(payload["space_title"]),
        account_email=str(payload.get("account_email", "")),
        drive_folder=str(payload.get("drive_folder_id", "")),
        resources=resources,
        group=str(payload.get("group", "")),
        parent_id=str(payload.get("parent_id", "")),
        photo_archive_folder=str(payload.get("photo_archive_folder", "")),
    )
    existing = next((space for space in spaces if space.identifier == identifier), None)
    if existing is None:
        spaces.append(imported)
        return imported
    existing.title = imported.title
    existing.account_email = imported.account_email or existing.account_email
    existing.drive_folder = imported.drive_folder or existing.drive_folder
    existing.resources = imported.resources
    existing.group = imported.group or existing.group
    existing.parent_id = imported.parent_id or existing.parent_id
    existing.photo_archive_folder = imported.photo_archive_folder or existing.photo_archive_folder
    return existing


def move_resources_between_spaces(
    spaces: list[CodiSpace],
    source_id: str,
    destination_id: str,
    resource_ids: set[str],
) -> int:
    """Move stored resources between spaces without changing their metadata."""
    if source_id == destination_id or not resource_ids:
        return 0
    source = next((space for space in spaces if space.identifier == source_id), None)
    destination = next((space for space in spaces if space.identifier == destination_id), None)
    if source is None or destination is None:
        return 0
    moving = [resource for resource in source.resources if resource.identifier in resource_ids]
    if not moving:
        return 0
    existing_ids = {resource.identifier for resource in destination.resources}
    destination.resources.extend(resource for resource in moving if resource.identifier not in existing_ids)
    source.resources = [resource for resource in source.resources if resource.identifier not in resource_ids]
    return len(moving)


def space_is_descendant(spaces: list[CodiSpace], candidate_id: str, ancestor_id: str) -> bool:
    """Return true when candidate is below ancestor in the space hierarchy."""
    by_id = {space.identifier: space for space in spaces}
    seen: set[str] = set()
    current = by_id.get(candidate_id)
    while current is not None and current.identifier not in seen:
        if current.parent_id == ancestor_id:
            return True
        seen.add(current.identifier)
        current = by_id.get(current.parent_id)
    return False
