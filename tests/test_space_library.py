import json
from pathlib import Path

from lou_codi_pdf_converter.space_library import (
    CodiSpace,
    SpaceResource,
    all_tags,
    import_space_index,
    load_spaces,
    move_resources_between_spaces,
    resource_from_drop,
    save_spaces,
    space_is_descendant,
    space_deletion_blocker,
)
from lou_codi_pdf_converter.ui.codi_space import (
    CodiSpaceWindow,
    clipboard_is_single_url,
    drive_folder_id,
    drive_folder_url,
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
            group="Professionnel",
            parent_id="dossier-examens",
            photo_archive_folder="/mnt/nas/Albums",
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


def test_move_resources_between_spaces_preserves_metadata() -> None:
    resource = SpaceResource(
        "mail", "Convention", "gmail_message", "https://mail.google.com/example",
        ["urgent"], "pro@example.org", "Entreprise", "2026-10-25T10:00:00+00:00",
    )
    source = CodiSpace("source", "Source", resources=[resource])
    destination = CodiSpace("destination", "Destination")

    moved = move_resources_between_spaces(
        [source, destination], "source", "destination", {"mail"},
    )

    assert moved == 1
    assert source.resources == []
    assert destination.resources == [resource]
    assert destination.resources[0].tags == ["urgent"]
    assert destination.resources[0].account_email == "pro@example.org"


def test_space_descendant_supports_multiple_levels() -> None:
    spaces = [
        CodiSpace("root", "Personnel"),
        CodiSpace("album", "Albums photo", parent_id="root"),
        CodiSpace("paramet", "Paramet", parent_id="album"),
    ]

    assert space_is_descendant(spaces, "paramet", "root")
    assert space_is_descendant(spaces, "paramet", "album")
    assert not space_is_descendant(spaces, "root", "paramet")


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
    assert drive_folder_url("1LongFolderIdentifier_123") == (
        "https://drive.google.com/drive/folders/1LongFolderIdentifier_123"
    )


def test_tag_dictionary_is_unique_and_alphabetical() -> None:
    spaces = [
        CodiSpace(
            "one",
            "Premier",
            tags=["Projet", "urgent"],
            resources=[SpaceResource("r1", "Fichier", "local_file", "/tmp/a", ["projet", "Archive"])],
        )
    ]

    assert all_tags(spaces) == ["Archive", "Projet", "urgent"]


def test_drop_recognizes_files_folders_and_google_links(tmp_path: Path) -> None:
    document = tmp_path / "tableau.xlsx"
    document.write_bytes(b"test")

    local = resource_from_drop(str(document), "perso@example.org")
    gmail = resource_from_drop("https://mail.google.com/mail/u/0/#inbox/message-id")
    drive = resource_from_drop("https://drive.google.com/drive/folders/folder-id")
    sheet = resource_from_drop("https://docs.google.com/spreadsheets/d/sheet-id/edit")

    assert local and local.kind == "local_file" and local.title == "tableau.xlsx"
    assert local.account_email == "perso@example.org"
    assert gmail and gmail.kind == "gmail_message"
    assert drive and drive.kind == "google_drive_folder"
    assert sheet and sheet.kind == "google_sheets" and sheet.title == "Tableur Google Sheets"


def test_browser_drop_extracts_url_from_title_and_markup() -> None:
    payload = "Planning annuel <https://docs.google.com/spreadsheets/d/sheet-id/edit>"

    assert CodiSpaceWindow._drop_values(None, payload) == [
        payload
    ]
    resource = resource_from_drop(payload)
    assert resource and resource.title == "Planning annuel"


def test_ai_conversations_are_distinguished_by_provider() -> None:
    chatgpt = resource_from_drop("https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc")
    claude = resource_from_drop("https://claude.ai/chat/12345678-1234-1234-1234-123456789abc")

    assert chatgpt and chatgpt.kind == "ai_chatgpt_conversation"
    assert chatgpt.title == "Conversation ChatGPT"
    assert claude and claude.kind == "ai_claude_conversation"
    assert claude.title == "Conversation Claude"


def test_clipboard_text_with_urls_or_terminal_paths_remains_a_note() -> None:
    assert clipboard_is_single_url("https://chatgpt.com/c/example")
    assert not clipboard_is_single_url(
        "Procédure RustDesk\nhttps://rustdesk.com/docs/en/client/linux/\n"
        "sudo apt install ./rustdesk.deb"
    )


def test_loading_migrates_an_old_chatgpt_link_for_display(tmp_path: Path) -> None:
    target = tmp_path / "spaces.json"
    target.write_text(json.dumps([{
        "identifier": "project",
        "title": "Projet",
        "resources": [{
            "identifier": "old",
            "title": "6adccaa7-93ec-83eb-9198-df888085fc61",
            "kind": "web_link",
            "target": "https://chatgpt.com/c/6adccaa7-93ec-83eb-9198-df888085fc61",
        }],
    }]), encoding="utf-8")

    resource = load_spaces(target)[1].resources[0]

    assert resource.kind == "ai_chatgpt_conversation"
    assert resource.title == "Conversation ChatGPT"


def test_import_space_index_opens_or_refreshes_named_space(tmp_path: Path) -> None:
    project = tmp_path / "Sud Avenir Hélico.loucodi-espace"
    project.write_text(json.dumps({
        "version": 2,
        "space_id": "sud-avenir",
        "space_title": "Sud Avenir Hélico",
        "account_email": "pro@example.org",
        "drive_folder_id": "drive-folder-123",
        "resources": [{
            "identifier": "mail-1",
            "title": "Courriel",
            "kind": "gmail_message",
            "target": "https://mail.google.com/mail/u/0/#inbox/123",
            "tags": ["hélico"],
        }],
    }), encoding="utf-8")
    spaces = [CodiSpace("inbox", "À classer")]

    imported = import_space_index(project, spaces)

    assert imported.title == "Sud Avenir Hélico"
    assert imported.drive_folder == "drive-folder-123"
    assert imported.resources[0].kind == "gmail_message"
    assert spaces[-1] is imported
