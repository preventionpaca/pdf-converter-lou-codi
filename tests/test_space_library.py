from pathlib import Path

from lou_codi_pdf_converter.space_library import (
    CodiSpace,
    SpaceResource,
    load_spaces,
    save_spaces,
)


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
