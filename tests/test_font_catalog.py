from pathlib import Path

from lou_codi_pdf_converter.services.font_catalog import (
    FontFace,
    closest_family,
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
