from __future__ import annotations

from pathlib import Path

from lou_codi_pdf_converter import module_selection
from lou_codi_pdf_converter.ui.code_lab import load_exercises


def test_all_modules_are_enabled_without_installer_selection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOU_CODI_INSTALL_ROOT", str(tmp_path))
    assert all(module_selection.module_enabled(name) for name in module_selection.SELECTABLE_MODULES)


def test_installer_selection_disables_missing_markers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOU_CODI_INSTALL_ROOT", str(tmp_path))
    markers = tmp_path / "selected-modules"
    markers.mkdir()
    (markers / "code_lab.enabled").write_text("enabled", encoding="utf-8")
    assert module_selection.module_enabled("code_lab") is True
    assert module_selection.module_enabled("pdf_studio") is False


def test_code_lab_exercises_are_valid_and_cover_four_languages() -> None:
    exercises = load_exercises()
    assert len(exercises) >= 20
    assert {exercise.language for exercise in exercises} >= {"python", "javascript", "html", "css"}
    for exercise in exercises:
        assert exercise.title
        assert exercise.code
        assert 0 <= exercise.answer < len(exercise.choices)
