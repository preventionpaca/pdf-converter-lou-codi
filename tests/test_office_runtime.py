from pathlib import Path
from unittest.mock import patch

from lou_codi_pdf_converter.services.office_runtime import find_office_engine


def test_bundled_engine_has_priority_over_system_engine(tmp_path: Path) -> None:
    executable = tmp_path / "office-runtime" / "program" / "soffice"
    executable.parent.mkdir(parents=True)
    executable.touch()

    with patch(
        "lou_codi_pdf_converter.services.office_runtime.runtime_root", return_value=tmp_path
    ), patch(
        "lou_codi_pdf_converter.services.office_runtime.shutil.which",
        return_value="/usr/bin/libreoffice",
    ):
        assert find_office_engine() == executable


def test_system_engine_is_only_a_development_fallback(tmp_path: Path) -> None:
    with patch(
        "lou_codi_pdf_converter.services.office_runtime.runtime_root", return_value=tmp_path
    ), patch(
        "lou_codi_pdf_converter.services.office_runtime.shutil.which",
        return_value="/usr/bin/libreoffice",
    ):
        assert find_office_engine() == Path("/usr/bin/libreoffice")
