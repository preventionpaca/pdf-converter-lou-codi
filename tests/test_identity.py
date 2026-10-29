from pathlib import Path


def test_legacy_name_is_absent_from_project_files() -> None:
    root = Path(__file__).parents[1]
    excluded = {
        ".git", ".venv", ".pytest_cache", "__pycache__",
        "build", "dist", "output",
    }
    for path in root.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pyc"}:
            continue
        assert "lou" + "camin" not in path.read_text(encoding="utf-8", errors="ignore").lower()


def test_occitan_cross_is_packaged() -> None:
    root = Path(__file__).parents[1]
    logo = root / "src/lou_codi_pdf_converter/assets/croix-lou-codi.png"
    assert logo.is_file()
    assert logo.stat().st_size > 100_000


def test_cod_document_icons_are_packaged() -> None:
    root = Path(__file__).parents[1]
    assets = root / "src/lou_codi_pdf_converter/assets"
    assert (assets / "lou-codi-document.png").stat().st_size > 1_000
    assert (assets / "lou-codi-document.ico").stat().st_size > 1_000
    assert (assets / "lou-codi-document.icns").stat().st_size > 1_000
    assert (assets / "lou-codi-document.svg").stat().st_size > 200
    for size in (16, 24, 32, 48, 64, 128, 256):
        assert (assets / f"lou-codi-document-{size}.png").is_file()

    linux = (root / "packaging/linux/make-deb.sh").read_text(encoding="utf-8")
    windows = (root / "packaging/windows/lou-codi-workshop.iss").read_text(encoding="utf-8")
    macos = (root / "packaging/standalone/lou-codi-pdf-converter.spec").read_text(encoding="utf-8")
    assert "application-x-loucodi-document.svg" in linux
    assert "lou-codi-document.ico" in windows
    assert '"code", "cod", "loucodi-document"' in macos
    assert '"lou-codi-document.icns"' in macos


def test_all_installers_associate_every_lou_codi_document_extension() -> None:
    root = Path(__file__).parents[1]
    files = [
        root / "packaging/linux/install-bundle.sh",
        root / "packaging/linux/make-deb.sh",
        root / "packaging/windows/install.ps1",
        root / "packaging/windows/lou-codi-workshop.iss",
        root / "packaging/standalone/lou-codi-pdf-converter.spec",
    ]
    for path in files:
        content = path.read_text(encoding="utf-8")
        for extension in ("code", "cod", "loucodi-document"):
            assert extension in content, f"{extension} absent de {path.name}"
