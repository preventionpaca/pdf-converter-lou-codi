from lou_codi_pdf_converter.ui.pdf_picker import _format_size


def test_format_size_uses_french_units() -> None:
    assert _format_size(512 * 1024) == "512 Ko"
    assert _format_size(2 * 1024 * 1024) == "2.0 Mo"
