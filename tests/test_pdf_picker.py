from lou_codi_pdf_converter.ui.pdf_picker import PdfPicker, _format_size


def test_format_size_uses_french_units() -> None:
    assert _format_size(512 * 1024) == "512 Ko"
    assert _format_size(2 * 1024 * 1024) == "2.0 Mo"


def test_picker_defaults_to_pdf_suffix() -> None:
    assert PdfPicker.__init__.__kwdefaults__["allowed_suffixes"] is None
