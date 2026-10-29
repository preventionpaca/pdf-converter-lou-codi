import json
from pathlib import Path

import pytest

from lou_codi_pdf_converter.services import capture_bridge
from lou_codi_pdf_converter.space_library import CodiSpace, load_spaces, save_spaces


@pytest.fixture
def capture_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "codi-spaces.json"
    save_spaces(
        [
            CodiSpace("inbox", "À classer"),
            CodiSpace("project", "Projet test", account_email="pro@example.org"),
        ],
        target,
    )
    monkeypatch.setattr(capture_bridge, "load_spaces", lambda: load_spaces(target))
    monkeypatch.setattr(
        capture_bridge,
        "save_spaces",
        lambda spaces: save_spaces(spaces, target),
    )
    return target


def test_capture_lists_and_creates_spaces(capture_library: Path) -> None:
    assert [space["title"] for space in capture_bridge.list_capture_spaces()] == [
        "À classer",
        "Projet test",
    ]

    created = capture_bridge.create_capture_space("Nouvel espace", "perso@gmail.com")

    assert created["title"] == "Nouvel espace"
    saved = load_spaces(capture_library)[-1]
    assert saved.title == "Nouvel espace"
    assert saved.account_email == "perso@gmail.com"
    assert saved.group == "Personnel"


def test_capture_adds_named_url_once(capture_library: Path) -> None:
    first = capture_bridge.capture_url(
        "project",
        "https://docs.google.com/spreadsheets/d/sheet-id/edit",
        "Planning annuel",
    )
    second = capture_bridge.capture_url(
        "project",
        "https://docs.google.com/spreadsheets/d/sheet-id/edit",
        "Autre titre",
    )

    assert first["added"] is True
    assert second["added"] is False
    project = next(space for space in load_spaces(capture_library) if space.identifier == "project")
    assert len(project.resources) == 1
    assert project.resources[0].title == "Planning annuel"
    assert project.resources[0].kind == "google_sheets"
    assert project.resources[0].account_email == "pro@example.org"


def test_capture_enriches_google_photos_title(
    capture_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capture_bridge,
        "google_photos_title",
        lambda _url: "Sortie atelier · 12 octobre 📸",
    )

    result = capture_bridge.capture_url(
        "project",
        "https://photos.google.com/share/album-id?key=public-key",
        "Albums - Google Photos",
    )

    assert result["resource"] == "Sortie atelier · 12 octobre 📸"
    project = next(space for space in load_spaces(capture_library) if space.identifier == "project")
    assert project.resources[-1].title == "Sortie atelier · 12 octobre 📸"


def test_capture_rejects_unknown_space_or_non_web_url(capture_library: Path) -> None:
    with pytest.raises(ValueError, match="HTTP"):
        capture_bridge.capture_url("project", "file:///tmp/private.txt")
    with pytest.raises(ValueError, match="n’existe plus"):
        capture_bridge.capture_url("missing", "https://example.org")


def test_capture_creates_distinct_ai_knowledge_cards(capture_library: Path) -> None:
    url = "https://chatgpt.com/c/example"
    first = capture_bridge.capture_url(
        "project", url, "Configurer RustDesk", "Installer le paquet .deb.", "ai_knowledge"
    )
    second = capture_bridge.capture_url(
        "project", url, "Configurer RustDesk", "Activer le service systemd.", "ai_knowledge"
    )

    assert first["added"] is True
    assert second["added"] is True
    project = next(space for space in load_spaces(capture_library) if space.identifier == "project")
    notes = [resource for resource in project.resources if resource.kind == "ai_chatgpt_knowledge"]
    assert [note.details for note in notes] == [
        "Installer le paquet .deb.",
        "Activer le service systemd.",
    ]


def test_extension_manifest_is_valid_json() -> None:
    manifest = Path("browser-extension/lou-codi-capture/manifest.json")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == 3
    assert "contextMenus" in payload["permissions"]
    assert payload["content_scripts"][0]["js"] == ["context.js"]
