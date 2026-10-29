from __future__ import annotations

import tkinter as tk
import webbrowser

from ..i18n import get_language, tr


HELP_URL = "https://loucodi.fr/mode-emploi.html"
CONTACT_URL = "https://loucodi.fr/#contact"


def add_help_contact_buttons(parent: tk.Misc, help_anchor: str) -> None:
    """Add the module-level help and contact actions to a dark header."""
    button_options = {
        "bg": "#28507D",
        "fg": "white",
        "activebackground": "#3474AD",
        "activeforeground": "white",
        "relief": "flat",
        "padx": 12,
        "pady": 6,
    }
    tk.Button(
        parent,
        text=tr("Contact"),
        command=lambda: webbrowser.open(CONTACT_URL),
        **button_options,
    ).pack(side="right", padx=(4, 0))
    tk.Button(
        parent,
        text=tr("Aide"),
        command=lambda: webbrowser.open(
            f"{HELP_URL}?lang={get_language()}#{help_anchor}"
        ),
        **button_options,
    ).pack(side="right", padx=(8, 0))
