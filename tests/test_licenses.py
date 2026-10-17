from pathlib import Path

from lou_codi_pdf_converter.ui.about_dialog import LICENSE_ROWS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_license_folder_contains_required_notices() -> None:
    license_dir = PROJECT_ROOT / "licenses"
    expected = {
        "APACHE-2.0.txt",
        "PYTHON-LICENSE.txt",
        "PYTHON-PSF-NOTICE.txt",
        "README.md",
        "SQLITE-PUBLIC-DOMAIN.txt",
    }
    assert expected <= {path.name for path in license_dir.iterdir()}


def test_about_catalogue_identifies_sqlite() -> None:
    assert any(
        component == "SQLite" and name == "Domaine public" for component, name, _ in LICENSE_ROWS
    )
