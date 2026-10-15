from pathlib import Path
from unittest.mock import patch

from lou_codi_pdf_converter.system import open_path


def test_open_path_uses_xdg_open_on_linux() -> None:
    with patch("lou_codi_pdf_converter.system.sys.platform", "linux"), patch(
        "lou_codi_pdf_converter.system.subprocess.Popen"
    ) as popen:
        open_path(Path("/tmp/result.pdf"))

    popen.assert_called_once_with(["xdg-open", "/tmp/result.pdf"])
