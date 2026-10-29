import os

from lou_codi_pdf_converter.ui.pdf_picker import PdfPicker, _format_size, _sorted_entries


def test_format_size_uses_french_units() -> None:
    assert _format_size(512 * 1024) == "512 Ko"
    assert _format_size(2 * 1024 * 1024) == "2.0 Mo"


def test_picker_defaults_to_pdf_suffix() -> None:
    assert PdfPicker.__init__.__kwdefaults__["allowed_suffixes"] is None


def test_picker_reads_new_files_and_sorts_latest_first(tmp_path) -> None:
    older = tmp_path / "ancien.pdf"
    older.write_bytes(b"old")
    os.utime(older, (10, 10))

    first_read = _sorted_entries(tmp_path, {".pdf"}, "modified", True)
    newest = tmp_path / "nouveau.pdf"
    newest.write_bytes(b"newest")
    os.utime(newest, (20, 20))
    refreshed = _sorted_entries(tmp_path, {".pdf"}, "modified", True)

    assert [row[0] for row in first_read] == [older]
    assert [row[0] for row in refreshed] == [newest, older]


def test_picker_sorts_name_and_size_while_keeping_directories_first(tmp_path) -> None:
    folder = tmp_path / "z-dossier"
    folder.mkdir()
    small = tmp_path / "z-petit.pdf"
    small.write_bytes(b"1")
    large = tmp_path / "a-grand.pdf"
    large.write_bytes(b"123456")

    by_name = _sorted_entries(tmp_path, {".pdf"}, "name", False)
    by_size = _sorted_entries(tmp_path, {".pdf"}, "size", True)

    assert [row[0] for row in by_name] == [folder, large, small]
    assert [row[0] for row in by_size] == [folder, large, small]
