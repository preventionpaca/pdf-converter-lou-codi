from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError


@dataclass(frozen=True)
class PdfInspection:
    page_count: int
    encrypted: bool
    scanned_likely: bool


class PdfPasswordRequired(ValueError):
    pass


def inspect_pdf(source: Path, password: str | None = None) -> PdfInspection:
    reader = PdfReader(source)
    encrypted = reader.is_encrypted
    if encrypted and not reader.decrypt(password or ""):
        raise PdfPasswordRequired("Ce PDF est chiffré et nécessite un mot de passe valide.")

    pages = list(reader.pages)
    try:
        text_characters = sum(len((page.extract_text() or "").strip()) for page in pages[:5])
    except FileNotDecryptedError as exc:
        raise PdfPasswordRequired("Ce PDF est chiffré et ne peut pas être lu.") from exc
    scanned_likely = bool(pages) and text_characters < 20 * min(5, len(pages))
    return PdfInspection(len(pages), encrypted, scanned_likely)

