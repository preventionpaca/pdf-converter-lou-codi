from __future__ import annotations

import json
import os
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..paths import application_data_directory
from .canvas_document import CanvasDocument


@dataclass(frozen=True)
class RecoverySnapshot:
    recovery_id: str
    document_path: Path
    metadata_path: Path
    title: str
    original_path: str
    saved_at: str
    session_id: str


def recovery_directory(*, create: bool = True) -> Path:
    directory = application_data_directory(create=create) / "recovery"
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def recovery_log_path() -> Path:
    directory = application_data_directory() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "document-studio.log"


def write_recovery_snapshot(
    document: CanvasDocument,
    *,
    recovery_id: str,
    title: str,
    original_path: str,
    session_id: str,
) -> RecoverySnapshot:
    """Atomically persist one crash-recovery document and its small descriptor."""
    directory = recovery_directory()
    document_path = directory / f"{recovery_id}.cod"
    metadata_path = directory / f"{recovery_id}.json"
    document.save(document_path)
    saved_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "format": 1,
        "recovery_id": recovery_id,
        "title": title or "Document sans titre",
        "original_path": original_path,
        "saved_at": saved_at,
        "session_id": session_id,
    }
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, metadata_path)
    return RecoverySnapshot(
        recovery_id,
        document_path,
        metadata_path,
        str(metadata["title"]),
        original_path,
        saved_at,
        session_id,
    )


def list_recovery_snapshots() -> list[RecoverySnapshot]:
    snapshots: list[RecoverySnapshot] = []
    directory = recovery_directory()
    for metadata_path in directory.glob("*.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("format") != 1:
                continue
            recovery_id = str(metadata["recovery_id"])
            document_path = directory / f"{recovery_id}.cod"
            if not document_path.is_file():
                continue
            snapshots.append(
                RecoverySnapshot(
                    recovery_id,
                    document_path,
                    metadata_path,
                    str(metadata.get("title") or "Document sans titre"),
                    str(metadata.get("original_path") or ""),
                    str(metadata.get("saved_at") or ""),
                    str(metadata.get("session_id") or ""),
                )
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return sorted(snapshots, key=lambda snapshot: snapshot.saved_at, reverse=True)


def delete_recovery_snapshot(recovery_id: str) -> None:
    if not recovery_id:
        return
    directory = recovery_directory()
    (directory / f"{recovery_id}.cod").unlink(missing_ok=True)
    (directory / f"{recovery_id}.json").unlink(missing_ok=True)
    (directory / f"{recovery_id}.json.tmp").unlink(missing_ok=True)


def record_document_studio_error(context: str, error: BaseException) -> None:
    """Keep diagnostics private and local so intermittent clipboard faults are actionable."""
    try:
        with recovery_log_path().open("a", encoding="utf-8") as stream:
            timestamp = datetime.now(timezone.utc).isoformat()
            stream.write(f"\n[{timestamp}] {context}: {type(error).__name__}: {error}\n")
            traceback.print_exception(type(error), error, error.__traceback__, file=stream)
    except OSError:
        pass
