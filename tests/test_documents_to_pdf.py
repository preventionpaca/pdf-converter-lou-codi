from pathlib import Path
from unittest.mock import Mock, patch

from lou_codi_pdf_converter.services.documents_to_pdf import convert_document_to_pdf


def test_office_conversion_invokes_libreoffice_headlessly(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    target = tmp_path / "result.pdf"
    source.touch()

    def fake_run(command: list[str], **_kwargs: object) -> Mock:
        output_directory = Path(command[command.index("--outdir") + 1])
        (output_directory / "source.pdf").write_bytes(b"pdf")
        return Mock(returncode=0, stderr="", stdout="")

    with patch(
        "lou_codi_pdf_converter.services.documents_to_pdf.shutil.which",
        return_value="/usr/bin/libreoffice",
    ), patch(
        "lou_codi_pdf_converter.services.documents_to_pdf.subprocess.run",
        side_effect=fake_run,
    ):
        convert_document_to_pdf(source, target)

    assert target.read_bytes() == b"pdf"
