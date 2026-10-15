from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..i18n import translate_widget_tree
from .windowing import center_window, make_modal

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"


def ask_text(parent: tk.Misc, title: str, prompt: str, initial: str = "") -> str | None:
    dialog = tk.Toplevel(parent, class_="LouCodiPdfConverter")
    dialog.title(title)
    dialog.configure(bg=BACKGROUND)
    result: list[str] = []
    icon = getattr(dialog._root(), "app_icon", None)
    if icon is not None:
        dialog.iconphoto(False, icon)
    tk.Label(dialog, text=title, bg=NAVY, fg="white", font=("Sans", 16, "bold"), padx=22, pady=14).pack(fill="x")
    body = ttk.Frame(dialog, style="Card.TFrame", padding=24)
    body.pack(fill="both", expand=True, padx=16, pady=16)
    ttk.Label(body, text=prompt, style="Body.TLabel").pack(anchor="w", pady=(0, 8))
    value = tk.StringVar(value=initial)
    entry = ttk.Entry(body, textvariable=value, width=58)
    entry.pack(fill="x")
    actions = ttk.Frame(dialog, style="App.TFrame", padding=(16, 0, 16, 16))
    actions.pack(fill="x")
    ttk.Button(actions, text="Annuler", command=dialog.destroy).pack(side="right")

    def accept() -> None:
        if value.get().strip():
            result.append(value.get().strip())
            dialog.destroy()

    ttk.Button(actions, text="Valider", style="Primary.TButton", command=accept).pack(side="right", padx=8)
    entry.bind("<Return>", lambda _event: accept())
    translate_widget_tree(dialog)
    center_window(dialog, 560, 250)
    make_modal(dialog, parent)
    entry.focus_set()
    dialog.wait_window()
    return result[0] if result else None


def ask_table_size(parent: tk.Misc) -> tuple[int, int] | None:
    value = ask_text(parent, "Insérer un tableau", "Dimensions du tableau (lignes × colonnes) :", "3 × 3")
    if not value:
        return None
    normalized = value.lower().replace(" ", "").replace("x", "×")
    try:
        rows_text, columns_text = normalized.split("×", 1)
        rows, columns = int(rows_text), int(columns_text)
    except (ValueError, TypeError):
        return None
    return (rows, columns) if 1 <= rows <= 30 and 1 <= columns <= 10 else None
