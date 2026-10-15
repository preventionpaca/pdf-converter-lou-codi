from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from .windowing import center_window, make_modal

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"
INK = "#1C2B3C"
MUTED = "#597089"


def show_success(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    action_label: str | None = None,
    action: Callable[[], None] | None = None,
) -> None:
    """Show a branded modal confirmation instead of a native Tk message box."""
    dialog = tk.Toplevel(parent, class_="LouCodiPdfConverter")
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.configure(bg=BACKGROUND)
    app_icon = getattr(dialog._root(), "app_icon", None)
    if app_icon is not None:
        dialog.iconphoto(False, app_icon)

    header = tk.Frame(dialog, bg=NAVY, padx=20, pady=12)
    header.pack(fill="x")
    if app_icon is not None:
        dialog.success_logo = app_icon.subsample(18, 18)
        tk.Label(header, image=dialog.success_logo, bg=NAVY, borderwidth=0).pack(
            side="left", padx=(0, 12)
        )
    tk.Label(
        header,
        text=title,
        bg=NAVY,
        fg="white",
        font=("Sans", 16, "bold"),
    ).pack(side="left")

    content = ttk.Frame(dialog, style="Card.TFrame", padding=(26, 22))
    content.pack(fill="both", expand=True, padx=18, pady=(18, 10))
    ttk.Label(
        content,
        text="✓",
        background="white",
        foreground="#23825B",
        font=("Sans", 24, "bold"),
    ).pack(side="left", anchor="n", padx=(0, 16))
    text_area = ttk.Frame(content, style="Card.TFrame")
    text_area.pack(side="left", fill="both", expand=True)
    ttk.Label(
        text_area,
        text="Opération réussie",
        style="Title.TLabel",
    ).pack(anchor="w", pady=(0, 8))
    ttk.Label(
        text_area,
        text=message,
        style="Body.TLabel",
        wraplength=570,
        justify="left",
    ).pack(anchor="w")

    buttons = ttk.Frame(dialog, style="App.TFrame", padding=(18, 8, 18, 18))
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Fermer", command=dialog.destroy).pack(side="right")

    if action_label and action:
        def run_action() -> None:
            action()
            dialog.destroy()

        ttk.Button(
            buttons,
            text=action_label,
            style="Primary.TButton",
            command=run_action,
        ).pack(side="right", padx=(0, 10))

    center_window(dialog, 700, 330)
    make_modal(dialog, parent)
    dialog.wait_window()
    if parent.winfo_exists():
        parent.grab_set()

