from pathlib import Path

from lou_codi_pdf_converter.services.destinations import (
    document_destination,
    favorite_destinations,
    resolve_existing_directory,
    save_favorite_destinations,
    set_document_destination,
    set_toolbar_size,
    toolbar_size,
)


def test_favorite_destinations_preserve_other_preferences(tmp_path: Path) -> None:
    settings = tmp_path / "preferences.json"
    settings.write_text('{"language": "fr"}', encoding="utf-8")
    drive = tmp_path / "Drive"
    drive.mkdir()

    save_favorite_destinations([("Réunions", drive)], settings)

    assert favorite_destinations(settings) == [("Réunions", drive)]
    assert '"language": "fr"' in settings.read_text(encoding="utf-8")


def test_document_destination_can_be_configured(tmp_path: Path) -> None:
    settings = tmp_path / "preferences.json"
    destination = tmp_path / "Comptes rendus"
    destination.mkdir()

    set_document_destination(destination, settings)

    assert document_destination(settings) == destination


def test_cloud_directory_with_invisible_trailing_space_is_resolved(tmp_path: Path) -> None:
    real_directory = tmp_path / "Notes fil de l'eau "
    real_directory.mkdir()

    assert resolve_existing_directory(tmp_path / "Notes fil de l'eau") == real_directory


def test_toolbar_size_is_persistent(tmp_path: Path) -> None:
    settings = tmp_path / "preferences.json"

    set_toolbar_size("large", settings)

    assert toolbar_size(settings) == "large"
