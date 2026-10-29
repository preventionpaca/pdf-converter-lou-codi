"""Generate the checked-in static UI catalogue used by the offline application.

This development tool sends only interface labels (never user data) to Google
Translate. The resulting JSON is bundled with the application, so translation
at runtime remains fully local and deterministic.
"""
from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "lou_codi_pdf_converter"
OUTPUT = SOURCE / "assets" / "i18n-static.json"
LANGUAGES = ("en", "de", "es", "it", "zh", "tr", "ar")
SEPARATOR = "\n<<<LOU_CODI_SEPARATOR>>>\n"


def interface_strings() -> list[str]:
    strings: set[str] = set()
    for path in (SOURCE / "app.py", *(SOURCE / "ui").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # Also retain human-readable strings assigned to a variable before
            # being passed to a widget (for example availability banners).
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if len(value) > 1 and re.search(r"[A-Za-zÀ-ÿ]", value):
                    strings.add(node.value)
            if isinstance(node, ast.keyword) and node.arg in {"text", "label"}:
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    strings.add(node.value.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "title" and node.args:
                    value = node.args[0]
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        strings.add(value.value)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr" and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    strings.add(value.value)
    # Module names and descriptions are positional dataclass arguments.
    app_tree = ast.parse((SOURCE / "app.py").read_text(encoding="utf-8"))
    for node in ast.walk(app_tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "WorkshopModule":
            for value in node.args[1:3]:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    strings.add(value.value)
    return sorted(value for value in strings if value.strip() and not value.startswith("#"))


def batches(values: list[str], limit: int = 3200) -> list[list[str]]:
    result: list[list[str]] = []
    current: list[str] = []
    size = 0
    for value in values:
        extra = len(value) + len(SEPARATOR)
        if current and size + extra > limit:
            result.append(current)
            current, size = [], 0
        current.append(value)
        size += extra
    if current:
        result.append(current)
    return result


def translate_batch(values: list[str], language: str) -> list[str]:
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "fr", "tl": language, "dt": "t", "q": SEPARATOR.join(values)},
        timeout=45,
    )
    response.raise_for_status()
    translated = "".join(part[0] for part in response.json()[0])
    pieces = translated.split("<<<LOU_CODI_SEPARATOR>>>")
    pieces = [piece.strip("\n ") for piece in pieces]
    if len(pieces) != len(values):
        raise RuntimeError(f"separator mismatch for {language}: {len(values)} != {len(pieces)}")
    return pieces


def main() -> None:
    sources = interface_strings()
    catalogue: dict[str, dict[str, str]] = {}
    for language in LANGUAGES:
        translated: list[str] = []
        for group in batches(sources):
            for attempt in range(3):
                try:
                    translated.extend(translate_batch(group, language))
                    break
                except (requests.RequestException, RuntimeError):
                    if attempt == 2:
                        raise
                    time.sleep(2 ** attempt)
        catalogue[language] = dict(zip(sources, translated, strict=True))
        print(f"{language}: {len(translated)} labels")
    OUTPUT.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
