from pathlib import Path
from unittest.mock import Mock, patch

from lou_codi_pdf_converter.services.documents_to_pdf import convert_document_to_pdf


def test_office_conversion_invokes_libreoffice_headlessly(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    target = tmp_path / "result.pdf"
    source.touch()
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> Mock:
        commands.append(command)
        output_directory = Path(command[command.index("--outdir") + 1])
        (output_directory / "source.pdf").write_bytes(b"pdf")
        return Mock(returncode=0, stderr="", stdout="")

    with patch(
        "lou_codi_pdf_converter.services.documents_to_pdf.find_office_engine",
        return_value=Path("/opt/lou-codi/office-runtime/program/soffice"),
    ), patch(
        "lou_codi_pdf_converter.services.documents_to_pdf.subprocess.run",
        side_effect=fake_run,
    ):
        convert_document_to_pdf(source, target)

    assert target.read_bytes() == b"pdf"
    assert commands[0][0] == "/opt/lou-codi/office-runtime/program/soffice"
    assert "--headless" in commands[0]
    assert any(argument.startswith("-env:UserInstallation=file://") for argument in commands[0])
