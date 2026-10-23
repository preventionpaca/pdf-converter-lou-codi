from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .paths import application_data_directory


@dataclass
class SpaceResource:
    identifier: str
    title: str
    kind: str
    target: str
    tags: list[str] = field(default_factory=list)
    account_email: str = ""


@dataclass
class CodiSpace:
    identifier: str
    title: str
    account_email: str = ""
    drive_folder: str = ""
    tags: list[str] = field(default_factory=list)
    resources: list[SpaceResource] = field(default_factory=list)


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
                resources.append(
                    SpaceResource(
                        identifier=str(raw_resource.get("identifier") or new_identifier()),
                        title=str(raw_resource.get("title") or raw_resource["target"]),
                        kind=str(raw_resource.get("kind") or "link"),
                        target=str(raw_resource["target"]),
                        tags=[str(tag) for tag in raw_resource.get("tags", []) if str(tag).strip()],
                        account_email=str(raw_resource.get("account_email", "")),
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
