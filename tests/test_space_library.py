from pathlib import Path

from lou_codi_pdf_converter.space_library import (
    CodiSpace,
    SpaceResource,
    load_spaces,
    save_spaces,
    space_deletion_blocker,
)
from lou_codi_pdf_converter.ui.codi_space import drive_folder_id


def test_missing_library_starts_with_inbox(tmp_path: Path) -> None:
    spaces = load_spaces(tmp_path / "missing.json")
    assert [(space.identifier, space.title) for space in spaces] == [("inbox", "À classer")]


def test_spaces_round_trip_all_resource_types(tmp_path: Path) -> None:
    target = tmp_path / "spaces.json"
    spaces = [
        CodiSpace(
            identifier="examens",
            title="Examens 2027",
            account_email="pro@example.org",
            drive_folder="https://drive.google.com/drive/folders/folder-id",
            tags=["examen", "2027"],
            resources=[
                SpaceResource(
                    identifier="photos",
                    title="Album des épreuves",
                    kind="google_photos_album",
                    target="https://photos.google.com/share/album-id",
                    tags=["photos"],
                    account_email="pro@example.org",
                )
            ],
        )
    ]
    save_spaces(spaces, target)
    loaded = load_spaces(target)
    assert loaded[0].identifier == "inbox"
    assert loaded[1] == spaces[0]


def test_space_deletion_requires_an_empty_unlinked_space() -> None:
    assert space_deletion_blocker(CodiSpace("inbox", "À classer"))
    linked = CodiSpace("linked", "Lié", drive_folder="https://drive.google.com/example")
    assert "Drive" in space_deletion_blocker(linked)
    populated = CodiSpace(
        "filled",
        "Rempli",
        resources=[SpaceResource("one", "Document", "local_file", "/tmp/document.pdf")],
    )
    assert "ressources" in space_deletion_blocker(populated)
    assert space_deletion_blocker(CodiSpace("empty", "Vide")) == ""


def test_drive_folder_id_accepts_url_or_identifier() -> None:
    assert drive_folder_id("https://drive.google.com/drive/folders/abc_DEF-123?usp=sharing") == "abc_DEF-123"
    assert drive_folder_id("1LongFolderIdentifier_123") == "1LongFolderIdentifier_123"
    assert drive_folder_id("https://drive.google.com/file/d/not-a-folder") == ""
