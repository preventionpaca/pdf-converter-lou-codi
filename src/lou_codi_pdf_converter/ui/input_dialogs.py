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


def edit_table(parent: tk.Misc, text: str) -> str | None:
    rows = [row.split("\t") for row in text.splitlines()]
    if not rows:
        rows = [[""]]
    column_count = max(len(row) for row in rows)
    rows = [row + [""] * (column_count - len(row)) for row in rows]
    dialog = tk.Toplevel(parent, class_="LouCodiPdfConverter")
    dialog.title("Modifier le tableau")
    dialog.configure(bg=BACKGROUND)
    result: list[str] = []
    icon = getattr(dialog._root(), "app_icon", None)
    if icon is not None:
        dialog.iconphoto(False, icon)
    tk.Label(dialog, text="Modifier le tableau", bg=NAVY, fg="white", font=("Sans", 16, "bold"), padx=22, pady=14).pack(fill="x")
    ttk.Label(
        dialog,
        text="Saisissez du texte ou une formule : =A1+B1, =A1*20%, =SUM(A1:A4)",
        style="Body.TLabel",
    ).pack(fill="x", padx=18, pady=(12, 6))
    area = ttk.Frame(dialog, style="App.TFrame")
    area.pack(fill="both", expand=True, padx=18)
    canvas = tk.Canvas(area, bg="white", highlightthickness=0)
    xbar = ttk.Scrollbar(area, orient="horizontal", command=canvas.xview)
    ybar = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
    canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    ybar.grid(row=0, column=1, sticky="ns")
    xbar.grid(row=1, column=0, sticky="ew")
    area.rowconfigure(0, weight=1)
    area.columnconfigure(0, weight=1)
    grid = ttk.Frame(canvas, style="Card.TFrame", padding=8)
    window = canvas.create_window(0, 0, window=grid, anchor="nw")
    variables: list[list[tk.StringVar]] = []
    ttk.Label(grid, text="", style="Body.TLabel", width=4).grid(row=0, column=0)
    for column in range(column_count):
        ttk.Label(grid, text=_column_name(column), style="Body.TLabel", anchor="center").grid(row=0, column=column + 1, sticky="ew")
    for row_index, values in enumerate(rows):
        ttk.Label(grid, text=str(row_index + 1), style="Body.TLabel", anchor="center", width=4).grid(row=row_index + 1, column=0)
        variable_row: list[tk.StringVar] = []
        for column_index, value in enumerate(values):
            variable = tk.StringVar(value=value)
            variable_row.append(variable)
            ttk.Entry(grid, textvariable=variable, width=18).grid(row=row_index + 1, column=column_index + 1, padx=1, pady=1, sticky="ew")
        variables.append(variable_row)

    def resize(_event: object = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(window, width=max(canvas.winfo_width(), grid.winfo_reqwidth()))

    grid.bind("<Configure>", resize)
    canvas.bind("<Configure>", resize)
    actions = ttk.Frame(dialog, style="App.TFrame", padding=14)
    actions.pack(fill="x")

    def accept() -> None:
        result.append("\n".join("\t".join(variable.get() for variable in row) for row in variables))
        dialog.destroy()

    ttk.Button(actions, text="Annuler", command=dialog.destroy).pack(side="right")
    ttk.Button(actions, text="Valider le tableau", style="Primary.TButton", command=accept).pack(side="right", padx=8)
    translate_widget_tree(dialog)
    center_window(dialog, min(1200, 180 + column_count * 150), min(800, 240 + len(rows) * 38))
    make_modal(dialog, parent)
    dialog.wait_window()
    return result[0] if result else None


def _column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name
