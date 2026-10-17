from pathlib import Path
from types import SimpleNamespace
import logging
from unittest.mock import Mock, patch

from lou_codi_pdf_converter.services.pdf_to_office import (
    _Pdf2DocxProgressHandler,
    convert_pdf_to_docx,
)
from lou_codi_pdf_converter.ui.pdf_to_office import _docx_progress_fraction


def test_docx_conversion_avoids_packaged_multiprocessing_deadlock() -> None:
    converter = Mock()
    converter_type = Mock(return_value=converter)
    fake_module = SimpleNamespace(Converter=converter_type)

    with patch.dict("sys.modules", {"pdf2docx": fake_module}):
        convert_pdf_to_docx(Path("source.pdf"), Path("result.docx"), "secret")

    converter_type.assert_called_once_with("source.pdf", "secret")
    converter.convert.assert_called_once_with("result.docx", multi_processing=False)
    converter.close.assert_called_once_with()


def test_pdf2docx_progress_handler_reports_stages_and_pages() -> None:
    progress = Mock()
    handler = _Pdf2DocxProgressHandler(progress)

    handler.emit(logging.LogRecord("pdf2docx", logging.INFO, "", 0, "[3/4] Parsing pages...", (), None))
    handler.emit(logging.LogRecord("pdf2docx", logging.INFO, "", 0, "(2/7) Page 2", (), None))
    handler.emit(logging.LogRecord("pdf2docx", logging.INFO, "", 0, "[4/4] Creating pages...", (), None))
    handler.emit(logging.LogRecord("pdf2docx", logging.INFO, "", 0, "(1/7) Page 1", (), None))

    assert progress.call_args_list == [
        (("Lecture des pages", None, None),),
        (("Lecture des pages", 2, 7),),
        (("Création du document Word", None, None),),
        (("Création du document Word", 1, 7),),
    ]


def test_docx_progress_never_moves_back_between_stages() -> None:
    assert _docx_progress_fraction("Lecture des pages", 7, 7) == 0.75
    assert _docx_progress_fraction("Création du document Word", 1, 7) > 0.75
    assert _docx_progress_fraction("Création du document Word", 7, 7) == 1.0
