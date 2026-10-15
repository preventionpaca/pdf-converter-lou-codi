from pathlib import Path

from lou_codi_pdf_converter.paths import collision_free_target


def test_collision_free_target_preserves_existing_file(tmp_path: Path) -> None:
    (tmp_path / "rapport.pdf").touch()
    (tmp_path / "rapport_2.pdf").touch()

    assert collision_free_target(tmp_path, "rapport", ".pdf") == tmp_path / "rapport_3.pdf"


def test_collision_free_target_uses_original_name_when_available(tmp_path: Path) -> None:
    assert collision_free_target(tmp_path, "rapport", ".pdf") == tmp_path / "rapport.pdf"

