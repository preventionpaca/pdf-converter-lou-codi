from pathlib import Path


def test_legacy_name_is_absent_from_project_files() -> None:
    root = Path(__file__).parents[1]
    excluded = {".git", ".venv", ".pytest_cache", "__pycache__"}
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
    assert logo.stat().st_size > 1_000
