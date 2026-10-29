from pathlib import Path

from lou_codi_pdf_converter.ui.directory_picker import versioned_save_target


def test_versioned_save_target_keeps_unused_name(tmp_path: Path) -> None:
    target = tmp_path / "rapport.pdf"

    assert versioned_save_target(target) == target


def test_versioned_save_target_uses_first_available_numeric_suffix(tmp_path: Path) -> None:
    target = tmp_path / "rapport.pdf"
    target.write_bytes(b"original")
    (tmp_path / "rapport_1.pdf").write_bytes(b"version 1")
    (tmp_path / "rapport_2.pdf").write_bytes(b"version 2")

    assert versioned_save_target(target) == tmp_path / "rapport_3.pdf"
