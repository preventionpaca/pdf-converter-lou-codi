from pathlib import Path

from lou_codi_pdf_converter.services.font_catalog import (
    FontFace,
    closest_family,
    install_user_font,
    normalize_font_name,
)


def test_normalize_embedded_pdf_font_name() -> None:
    assert normalize_font_name("ABCDEF+Arial-BoldMT") == "Arial"
    assert normalize_font_name("LiberationSans-Italic") == "Liberation Sans"


def test_closest_family_prefers_exact_match() -> None:
    assert closest_family("Liberation Sans", ("DejaVu Sans", "Liberation Sans")) == "Liberation Sans"


def test_font_face_keeps_local_path() -> None:
    face = FontFace("Example", Path("/tmp/example.ttf"), "Regular")
    assert face.family == "Example"


def test_install_user_font_copies_to_private_font_directory(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "Example.ttf"
    source.write_bytes(b"font-data")
    private_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: private_home))
    monkeypatch.setattr(
        "lou_codi_pdf_converter.services.font_catalog.shutil.which", lambda _name: None
    )

    installed = install_user_font(source)

    assert installed == private_home / ".local/share/fonts/LouCodi/Example.ttf"
    assert installed.read_bytes() == b"font-data"


def test_install_user_font_rejects_non_font_file(tmp_path: Path) -> None:
    source = tmp_path / "not-a-font.txt"
    source.write_text("no")
    try:
        install_user_font(source)
    except ValueError as exc:
        assert ".ttf" in str(exc)
    else:
        raise AssertionError("A non-font file must be rejected")
