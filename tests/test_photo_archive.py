import json
import zipfile
from pathlib import Path

import pytest

from lou_codi_pdf_converter.services.photo_archive import import_google_photos_archive


def test_import_photo_archive_preserves_files_sidecars_and_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "album.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Album/photo.jpg", b"jpeg-original-bytes")
        bundle.writestr("Album/photo.jpg.json", '{"geoData": {"latitude": 43.7}}')

    result = import_google_photos_archive(archive, tmp_path / "nas", "Voyage / Nice")

    assert result.directory.name == "Voyage - Nice"
    assert (result.directory / "Album/photo.jpg").read_bytes() == b"jpeg-original-bytes"
    assert (result.directory / "Album/photo.jpg.json").is_file()
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["format"] == "lou-codi-photo-archive-v1"
    assert {item["path"] for item in manifest["files"]} == {
        "Album/photo.jpg", "Album/photo.jpg.json",
    }


def test_import_photo_archive_ignores_traversal_and_duplicate_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "album.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", b"forbidden")
        bundle.writestr("photo.jpg", b"same-photo")

    first = import_google_photos_archive(archive, tmp_path / "nas", "Album")
    second = import_google_photos_archive(archive, tmp_path / "nas", "Album")

    assert first.extracted == 1
    assert second.duplicates == 1
    assert not (tmp_path / "nas/outside.txt").exists()


def test_rejects_non_zip_archive(tmp_path: Path) -> None:
    source = tmp_path / "photo.txt"
    source.write_text("not a zip", encoding="utf-8")

    with pytest.raises(ValueError, match="ZIP valide"):
        import_google_photos_archive(source, tmp_path / "nas", "Album")
