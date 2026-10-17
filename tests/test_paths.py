from pathlib import Path

from lou_codi_pdf_converter import paths


def test_module_output_directory_creates_loucodi_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(paths, "downloads_directory", lambda: tmp_path)

    result = paths.module_output_directory("Document Studio")

    assert result == tmp_path / "LouCodi" / "Document Studio"
    assert result.is_dir()


def test_module_output_directory_removes_forbidden_filename_characters(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(paths, "downloads_directory", lambda: tmp_path)

    result = paths.module_output_directory('PDF: test/essai?')

    assert result.name == "PDF testessai"
