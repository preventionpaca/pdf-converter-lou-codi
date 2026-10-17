from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from ..i18n import tr, translate_widget_tree
from .windowing import center_window, make_modal

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"
INK = "#1C2B3C"
MUTED = "#597089"


def _branded_message(
    parent: tk.Misc | None,
    title: str,
    message: str,
    *,
    kind: str,
    buttons: tuple[tuple[str, object], ...],
    default: object,
) -> object:
    owner = parent or tk._default_root  # type: ignore[attr-defined]
    if owner is None:
        return default
    dialog = tk.Toplevel(owner, class_="Loucodiworkshop")
    title, message = tr(title), tr(message)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.configure(bg=BACKGROUND)
    icon = getattr(dialog._root(), "app_icon", None)
    if icon is not None:
        dialog.iconphoto(False, icon)
    result = {"value": default}
    colors = {
        "info": ("i", "#2368AF", "Information"),
        "warning": ("!", "#C47B00", "Attention"),
        "error": ("×", "#C83232", "Une action est nécessaire"),
        "question": ("?", "#2368AF", "Confirmation"),
    }
    symbol, color, heading = colors[kind]
    header = tk.Frame(dialog, bg=NAVY, padx=20, pady=12)
    header.pack(fill="x")
    tk.Label(header, text=title, bg=NAVY, fg="white", font=("Sans", 16, "bold")).pack(side="left")
    card = tk.Frame(dialog, bg="white", padx=24, pady=22)
    card.pack(fill="both", expand=True, padx=18, pady=18)
    tk.Label(card, text=symbol, bg="white", fg=color, font=("Sans", 26, "bold"), width=2).pack(side="left", anchor="n", padx=(0, 14))
    text = tk.Frame(card, bg="white")
    text.pack(side="left", fill="both", expand=True)
    tk.Label(text, text=heading, bg="white", fg=INK, font=("Sans", 13, "bold")).pack(anchor="w")
    tk.Label(text, text=message, bg="white", fg=MUTED, font=("Sans", 10), wraplength=560, justify="left").pack(anchor="w", pady=(8, 0))
    footer = ttk.Frame(dialog, padding=(18, 0, 18, 18))
    footer.pack(fill="x")

    def close(value: object) -> None:
        result["value"] = value
        dialog.destroy()

    for index, (label, value) in enumerate(buttons):
        ttk.Button(
            footer,
            text=label,
            style="Primary.TButton" if index == 0 else "TButton",
            command=lambda selected=value: close(selected),
        ).pack(side="right", padx=(8, 0))
    dialog.protocol("WM_DELETE_WINDOW", lambda: close(default))
    center_window(dialog, 680, 320)
    make_modal(dialog, owner)
    dialog.wait_window()
    return result["value"]


def install_branded_messageboxes() -> None:
    """Use the Lou Còdi visual language for every alert and confirmation."""
    if getattr(messagebox, "_lou_codi_brand", False):
        return

    def parent_from(options: dict[str, object]) -> tk.Misc | None:
        value = options.pop("parent", None)
        return value if isinstance(value, tk.Misc) else None

    messagebox.showinfo = lambda title, message, **options: _branded_message(parent_from(options), title, message, kind="info", buttons=(("Fermer", "ok"),), default="ok")  # type: ignore[assignment]
    messagebox.showwarning = lambda title, message, **options: _branded_message(parent_from(options), title, message, kind="warning", buttons=(("Fermer", "ok"),), default="ok")  # type: ignore[assignment]
    messagebox.showerror = lambda title, message, **options: _branded_message(parent_from(options), title, message, kind="error", buttons=(("Fermer", "ok"),), default="ok")  # type: ignore[assignment]
    messagebox.askyesno = lambda title, message, **options: bool(_branded_message(parent_from(options), title, message, kind="question", buttons=(("Oui", True), ("Non", False)), default=False))  # type: ignore[assignment]
    messagebox.askokcancel = lambda title, message, **options: bool(_branded_message(parent_from(options), title, message, kind="question", buttons=(("OK", True), ("Annuler", False)), default=False))  # type: ignore[assignment]
    messagebox.askyesnocancel = lambda title, message, **options: _branded_message(parent_from(options), title, message, kind="question", buttons=(("Oui", True), ("Non", False), ("Annuler", None)), default=None)  # type: ignore[assignment]
    messagebox._lou_codi_brand = True


def show_success(
    parent: tk.Misc,
    title: str,
    message: str,
    *,
    action_label: str | None = None,
    action: Callable[[], None] | None = None,
) -> None:
    """Show a branded modal confirmation instead of a native Tk message box."""
    dialog = tk.Toplevel(parent, class_="Loucodiworkshop")
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

    translate_widget_tree(dialog)
    center_window(dialog, 700, 330)
    make_modal(dialog, parent)
    dialog.wait_window()
    if parent.winfo_exists():
        parent.grab_set()
