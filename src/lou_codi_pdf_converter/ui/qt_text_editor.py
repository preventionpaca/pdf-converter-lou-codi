"""Standalone Qt rich-text editor used by Document Studio.

It runs in a separate process so Qt and Tk never share an event loop.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QFontComboBox,
    QGridLayout,
    QInputDialog,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
)

STYLE_KEYS = (
    "bold",
    "italic",
    "underline",
    "strikethrough",
    "color",
    "highlight",
    "font_family",
    "font_size",
)

SYMBOLS = (
    "•",
    "◦",
    "▪",
    "▫",
    "◆",
    "◇",
    "★",
    "☆",
    "☐",
    "☑",
    "☒",
    "✓",
    "✗",
    "□",
    "■",
    "○",
    "●",
    "←",
    "→",
    "↑",
    "↓",
    "↔",
    "⇒",
    "⇐",
    "➜",
    "€",
    "£",
    "$",
    "%",
    "©",
    "®",
    "™",
    "§",
    "°",
    "±",
    "☎",
    "✉",
    "⌂",
    "⚠",
    "ℹ",
    "♥",
    "♦",
    "♣",
    "♠",
    "²",
    "³",
    "√",
    "∛",
    "∞",
    "≈",
    "≠",
    "≤",
    "≥",
    "×",
    "÷",
    "Σ",
    "∑",
    "∏",
    "∫",
    "∂",
    "∆",
    "π",
    "Ω",
    "α",
    "β",
    "γ",
    "τ",
    "λ",
    "μ",
    "φ",
    "θ",
    "f(x)",
    "∈",
    "∉",
    "⊂",
    "∩",
    "∪",
)


def _format_from_style(style: dict[str, object]) -> QTextCharFormat:
    result = QTextCharFormat()
    result.setFontFamilies([str(style.get("font_family", "Sans-serif"))])
    result.setFontPointSize(float(style.get("font_size", 12)))
    result.setFontWeight(QFont.Weight.Bold if style.get("bold") else QFont.Weight.Normal)
    result.setFontItalic(bool(style.get("italic")))
    result.setFontUnderline(bool(style.get("underline")))
    result.setFontStrikeOut(bool(style.get("strikethrough")))
    result.setForeground(QColor(str(style.get("color", "#000000"))))
    highlight = str(style.get("highlight", ""))
    result.setBackground(QColor(highlight) if highlight else QColor(Qt.GlobalColor.transparent))
    return result


def _style_from_format(value: QTextCharFormat) -> dict[str, object]:
    background = value.background().color()
    return {
        "bold": value.fontWeight() >= QFont.Weight.Bold,
        "italic": value.fontItalic(),
        "underline": value.fontUnderline(),
        "strikethrough": value.fontStrikeOut(),
        "color": value.foreground().color().name().upper(),
        "highlight": "" if background.alpha() == 0 else background.name().upper(),
        "font_family": (value.fontFamilies() or ["Sans-serif"])[0],
        "font_size": value.fontPointSize() if value.fontPointSize() > 0 else 12.0,
    }


class RichTextWindow(QMainWindow):
    def __init__(self, payload: dict[str, object], output: Path) -> None:
        super().__init__()
        self.payload = payload
        self.output = output
        self.saved = False
        self.copied_format: QTextCharFormat | None = None
        self.setWindowTitle("Modifier la zone de texte — Lou Còdi")
        self.resize(900, 560)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(True)
        self.setCentralWidget(self.editor)
        self._build_toolbar()
        self._load_document()
        self.editor.cursorPositionChanged.connect(self._sync_toolbar)
        self._sync_toolbar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Mise en forme", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        for label, callback in (("↶", self.editor.undo), ("↷", self.editor.redo)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)

        copy_format = QPushButton("Copier format")
        copy_format.clicked.connect(self._copy_format)
        toolbar.addWidget(copy_format)
        apply_format = QPushButton("Appliquer format")
        apply_format.clicked.connect(self._apply_format)
        toolbar.addWidget(apply_format)

        self.style_buttons: dict[str, QPushButton] = {}
        for name, label, callback, checkable in (
            ("bold", "G", self._bold, True),
            ("italic", "I", self._italic, True),
            ("underline", "S", self._underline, True),
            ("strike", "Barré", self._strike, True),
        ):
            button = QPushButton(label)
            button.setCheckable(checkable)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.style_buttons[name] = button

        for label, alignment in (
            ("←", Qt.AlignmentFlag.AlignLeft),
            ("↔", Qt.AlignmentFlag.AlignHCenter),
            ("→", Qt.AlignmentFlag.AlignRight),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=alignment: self._align(value))
            toolbar.addWidget(button)

        self.family = QFontComboBox()
        self.family.currentFontChanged.connect(self._font_family)
        toolbar.addWidget(self.family)
        self.size = QComboBox()
        self.size.setEditable(True)
        self.size.addItems(
            [
                "8",
                "9",
                "10",
                "11",
                "12",
                "14",
                "16",
                "18",
                "20",
                "24",
                "28",
                "32",
                "36",
                "48",
                "60",
                "72",
            ]
        )
        self.size.setCurrentText(str(self.payload.get("font_size", 12)))
        self.size.currentTextChanged.connect(self._font_size)
        toolbar.addWidget(self.size)
        smaller = QPushButton("A−")
        smaller.clicked.connect(lambda: self._adjust_size(-1))
        toolbar.addWidget(smaller)
        larger = QPushButton("A+")
        larger.clicked.connect(lambda: self._adjust_size(1))
        toolbar.addWidget(larger)

        color = QPushButton("Couleur")
        color.clicked.connect(self._text_color)
        toolbar.addWidget(color)
        link = QPushButton("Lien")
        link.clicked.connect(self._add_link)
        toolbar.addWidget(link)
        unlink = QPushButton("Retirer lien")
        unlink.clicked.connect(self._remove_link)
        toolbar.addWidget(unlink)
        for label, value in (
            ("Jaune", "#FFF176"),
            ("Vert", "#A7F3A1"),
            ("Violet", "#D8B4FE"),
            ("Cyan", "#8BE9FD"),
            ("Sans fluo", ""),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, chosen=value: self._highlight(chosen))
            toolbar.addWidget(button)

        symbols = QPushButton("Ω Symboles")
        symbols.clicked.connect(self._insert_symbol)
        toolbar.addWidget(symbols)
        bullets = QPushButton("• Liste")
        bullets.clicked.connect(lambda: self._make_list(False))
        toolbar.addWidget(bullets)
        numbered = QPushButton("1. Liste")
        numbered.clicked.connect(lambda: self._make_list(True))
        toolbar.addWidget(numbered)
        chatgpt = QPushButton("ChatGPT")
        chatgpt.clicked.connect(self._open_chatgpt)
        toolbar.addWidget(chatgpt)
        paste = QPushButton("Coller")
        paste.clicked.connect(self._paste_clipboard)
        toolbar.addWidget(paste)

        toolbar.addSeparator()
        save = QPushButton("✓ Terminer")
        save.clicked.connect(self.save_and_close)
        toolbar.addWidget(save)

    def _load_document(self) -> None:
        text = str(self.payload.get("text", ""))
        base = {key: self.payload.get(key) for key in STYLE_KEYS}
        cursor = self.editor.textCursor()
        cursor.insertText(text, _format_from_style(base))
        for run in self.payload.get("text_styles", []):
            if not isinstance(run, dict):
                continue
            start = max(0, int(run.get("start", 0)))
            end = min(len(text), max(start, int(run.get("end", start))))
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            merged = dict(base)
            merged.update(run)
            cursor.mergeCharFormat(_format_from_style(merged))
        for link in self.payload.get("text_links", []):
            if not isinstance(link, dict) or not link.get("hyperlink"):
                continue
            start = max(0, int(link.get("start", 0)))
            end = min(len(text), max(start, int(link.get("end", start))))
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(str(link["hyperlink"]))
            fmt.setFontUnderline(True)
            fmt.setForeground(QColor("#1769AA"))
            cursor.mergeCharFormat(fmt)
        alignment = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
            "justify": Qt.AlignmentFlag.AlignJustify,
        }.get(str(self.payload.get("align", "left")), Qt.AlignmentFlag.AlignLeft)
        cursor.select(QTextCursor.SelectionType.Document)
        block = QTextBlockFormat()
        block.setAlignment(alignment)
        cursor.mergeBlockFormat(block)
        self.editor.moveCursor(QTextCursor.MoveOperation.Start)
        self.editor.setFocus()

    def _merge(self, fmt: QTextCharFormat) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
        self.editor.mergeCurrentCharFormat(fmt)

    def _copy_format(self) -> None:
        self.copied_format = QTextCharFormat(self.editor.currentCharFormat())

    def _apply_format(self) -> None:
        if self.copied_format is not None:
            self._merge(QTextCharFormat(self.copied_format))

    def _bold(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold if checked else QFont.Weight.Normal)
        self._merge(fmt)

    def _italic(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(checked)
        self._merge(fmt)

    def _underline(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(checked)
        self._merge(fmt)

    def _strike(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(checked)
        self._merge(fmt)

    def _font_family(self, font: QFont) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamily(font.family())
        self._merge(fmt)

    def _font_size(self, value: str) -> None:
        try:
            size = float(value.replace(",", "."))
        except ValueError:
            return
        if size >= 6:
            fmt = QTextCharFormat()
            fmt.setFontPointSize(size)
            self._merge(fmt)

    def _adjust_size(self, delta: int) -> None:
        current = self.editor.currentCharFormat().fontPointSize()
        if current <= 0:
            current = float(self.payload.get("font_size", 12))
        self.size.setCurrentText(f"{max(6, current + delta):g}")

    def _sync_toolbar(self) -> None:
        fmt = self.editor.currentCharFormat()
        states = {
            "bold": fmt.fontWeight() >= QFont.Weight.Bold,
            "italic": fmt.fontItalic(),
            "underline": fmt.fontUnderline(),
            "strike": fmt.fontStrikeOut(),
        }
        for name, checked in states.items():
            button = self.style_buttons[name]
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
        self.family.blockSignals(True)
        families = fmt.fontFamilies()
        self.family.setCurrentFont(QFont(families[0] if families else "Sans-serif"))
        self.family.blockSignals(False)
        point_size = fmt.fontPointSize()
        if point_size > 0:
            self.size.blockSignals(True)
            self.size.setCurrentText(f"{point_size:g}")
            self.size.blockSignals(False)

    def _text_color(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self._merge(fmt)

    def _highlight(self, value: str) -> None:
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(value) if value else QColor(Qt.GlobalColor.transparent))
        self._merge(fmt)

    def _align(self, alignment: Qt.AlignmentFlag) -> None:
        cursor = self.editor.textCursor()
        block = QTextBlockFormat()
        block.setAlignment(alignment)
        cursor.mergeBlockFormat(block)

    def _insert_symbol(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Caractères spéciaux")
        layout = QVBoxLayout(dialog)
        grid = QGridLayout()
        layout.addLayout(grid)
        for index, symbol in enumerate(SYMBOLS):
            button = QPushButton(symbol)
            button.setMinimumSize(48, 36)
            button.clicked.connect(
                lambda _checked=False, value=symbol: (
                    self.editor.textCursor().insertText(value),
                    dialog.accept(),
                )
            )
            grid.addWidget(button, index // 8, index % 8)
        dialog.exec()

    def _make_list(self, numbered: bool) -> None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
        text = cursor.selectedText().replace("\u2029", "\n")
        lines = text.splitlines() or [""]
        formatted = "\n".join(
            f"{index + 1}. {line}" if numbered else f"• {line}" for index, line in enumerate(lines)
        )
        cursor.insertText(formatted)

    def _open_chatgpt(self) -> None:
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n").strip()
        source = selected or self.editor.toPlainText().strip()
        prompt = (
            "Corrige, reformule ou améliore le texte suivant en conservant son sens. "
            "Réponds uniquement avec le texte final, prêt à être collé :\n\n"
            f"{source}"
        )
        QApplication.clipboard().setText(prompt)
        webbrowser.open("https://chatgpt.com/")

    def _paste_clipboard(self) -> None:
        self.editor.textCursor().insertText(QApplication.clipboard().text())

    def _add_link(self) -> None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return
        value, accepted = QInputDialog.getText(self, "Lien hypertexte", "Adresse du lien :")
        if not accepted:
            return
        value = value.strip()
        if value and ":" not in value:
            value = f"https://{value}"
        fmt = QTextCharFormat()
        fmt.setAnchor(bool(value))
        fmt.setAnchorHref(value)
        fmt.setFontUnderline(bool(value))
        if value:
            fmt.setForeground(QColor("#1769AA"))
        cursor.mergeCharFormat(fmt)

    def _remove_link(self) -> None:
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return
        fmt = QTextCharFormat()
        fmt.setAnchor(False)
        fmt.setAnchorHref("")
        fmt.setFontUnderline(False)
        cursor.mergeCharFormat(fmt)

    def _result(self) -> dict[str, object]:
        text = self.editor.toPlainText()
        base = {key: self.payload.get(key) for key in STYLE_KEYS}
        runs: list[dict[str, object]] = []
        links: list[dict[str, object]] = []
        active: dict[str, object] | None = None
        active_link = ""
        link_start = 0
        start = 0
        cursor = QTextCursor(self.editor.document())
        for position in range(len(text)):
            cursor.setPosition(position)
            cursor.movePosition(
                QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor
            )
            style = _style_from_format(cursor.charFormat())
            href = cursor.charFormat().anchorHref()
            delta = {key: value for key, value in style.items() if value != base.get(key)}
            if delta != active:
                if active:
                    runs.append({"start": start, "end": position, **active})
                active = delta
                start = position
            if href != active_link:
                if active_link:
                    links.append({"start": link_start, "end": position, "hyperlink": active_link})
                active_link = href
                link_start = position
        if active:
            runs.append({"start": start, "end": len(text), **active})
        if active_link:
            links.append({"start": link_start, "end": len(text), "hyperlink": active_link})
        first = self.editor.document().firstBlock().blockFormat().alignment()
        align = (
            "center"
            if first & Qt.AlignmentFlag.AlignHCenter
            else "right"
            if first & Qt.AlignmentFlag.AlignRight
            else "justify"
            if first & Qt.AlignmentFlag.AlignJustify
            else "left"
        )
        return {"text": text, "text_styles": runs, "text_links": links, "align": align}

    def save_and_close(self) -> None:
        self.output.write_text(json.dumps(self._result(), ensure_ascii=False), encoding="utf-8")
        self.saved = True
        self.close()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self.saved:
            self.output.write_text(json.dumps(self._result(), ensure_ascii=False), encoding="utf-8")
            self.saved = True
        event.accept()


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    app = QApplication(sys.argv[:1])
    window = RichTextWindow(payload, Path(sys.argv[2]))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
