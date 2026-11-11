from __future__ import annotations

import json

from lou_codi_pdf_converter.services.canvas_document import CanvasDocument, PageObject
from lou_codi_pdf_converter.services import document_recovery
from lou_codi_pdf_converter.ui.document_editor import DocumentEditorWindow


def test_recovery_snapshot_round_trip_and_delete(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        document_recovery,
        "recovery_directory",
        lambda create=True: tmp_path,
    )
    document = CanvasDocument()
    document.objects.append(
        PageObject("text", 0, 10, 20, 200, 80, text="Compte rendu non enregistré")
    )

    saved = document_recovery.write_recovery_snapshot(
        document,
        recovery_id="recovery-test",
        title="Réunion",
        original_path="",
        session_id="ancienne-session",
    )

    assert saved.document_path.is_file()
    snapshots = document_recovery.list_recovery_snapshots()
    assert [snapshot.recovery_id for snapshot in snapshots] == ["recovery-test"]
    loaded = CanvasDocument.load(snapshots[0].document_path)
    assert loaded.objects[0].text == "Compte rendu non enregistré"

    document_recovery.delete_recovery_snapshot("recovery-test")
    assert document_recovery.list_recovery_snapshots() == []


def test_corrupt_recovery_descriptor_is_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        document_recovery,
        "recovery_directory",
        lambda create=True: tmp_path,
    )
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "broken.cod").write_bytes(b"not-a-document")

    assert document_recovery.list_recovery_snapshots() == []


def test_recovery_metadata_keeps_original_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        document_recovery,
        "recovery_directory",
        lambda create=True: tmp_path,
    )
    document_recovery.write_recovery_snapshot(
        CanvasDocument(),
        recovery_id="known-file",
        title="rapport.cod",
        original_path="/documents/rapport.cod",
        session_id="session-1",
    )

    metadata = json.loads((tmp_path / "known-file.json").read_text(encoding="utf-8"))
    assert metadata["original_path"] == "/documents/rapport.cod"
    assert metadata["title"] == "rapport.cod"


def test_failed_clipboard_transaction_restores_document(monkeypatch) -> None:
    editor = object.__new__(DocumentEditorWindow)
    editor.document = CanvasDocument(
        objects=[PageObject("text", 0, 10, 20, 200, 80, text="Avant collage")]
    )
    editor.selected = 0
    editor.selected_indices = {0}
    editor.undo_stack = []
    editor.redo_stack = []
    editor._render = lambda: None
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.messagebox.showerror",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "lou_codi_pdf_converter.ui.document_editor.record_document_studio_error",
        lambda *_args, **_kwargs: None,
    )

    def broken_paste() -> None:
        editor.document.objects[0].text = "Document partiellement modifié"
        editor.document.objects.append(
            PageObject("text", 0, 30, 40, 200, 80, text="Objet incomplet")
        )
        raise RuntimeError("clipboard failure")

    editor._run_clipboard_transaction("test", broken_paste)

    assert len(editor.document.objects) == 1
    assert editor.document.objects[0].text == "Avant collage"
    assert editor.selected == 0
    assert editor.selected_indices == {0}
