from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lou_codi_pdf_converter.services.pdf_to_office import convert_pdf_to_docx


def test_docx_conversion_uses_bounded_multiprocessing() -> None:
    converter = Mock()
    converter_type = Mock(return_value=converter)
    fake_module = SimpleNamespace(Converter=converter_type)

    with patch.dict("sys.modules", {"pdf2docx": fake_module}), patch(
        "lou_codi_pdf_converter.services.pdf_to_office.os.cpu_count", return_value=8
    ):
        convert_pdf_to_docx(Path("source.pdf"), Path("result.docx"), "secret")

    converter_type.assert_called_once_with("source.pdf", "secret")
    converter.convert.assert_called_once_with(
        "result.docx", multi_processing=True, cpu_count=4
    )
    converter.close.assert_called_once_with()
