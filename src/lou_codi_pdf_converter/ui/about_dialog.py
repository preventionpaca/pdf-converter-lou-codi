from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import __version__
from ..i18n import translate_widget_tree
from .windowing import center_window, make_modal

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"


def show_about(parent: tk.Misc) -> None:
    dialog = tk.Toplevel(parent, class_="LouCodiPdfConverter")
    dialog.title("À propos et licences")
    dialog.configure(bg=BACKGROUND)
    dialog.resizable(False, False)
    icon = getattr(dialog._root(), "app_icon", None)
    if icon is not None:
        dialog.iconphoto(False, icon)

    header = tk.Frame(dialog, bg=NAVY, padx=24, pady=18)
    header.pack(fill="x")
    if icon is not None:
        dialog.about_logo = icon.subsample(17, 17)
        tk.Label(header, image=dialog.about_logo, bg=NAVY).pack(side="left", padx=(0, 14))
    tk.Label(
        header,
        text="PDF Converter – Lou Còdi",
        bg=NAVY,
        fg="white",
        font=("Sans", 17, "bold"),
    ).pack(side="left")

    body = ttk.Frame(dialog, style="Card.TFrame", padding=26)
    body.pack(fill="both", expand=True, padx=18, pady=18)
    ttk.Label(body, text=f"Version {__version__}", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        body,
        text=(
            "Logiciel libre développé par Lou Còdi — Club de programmation.\n\n"
            "Licence : GNU Affero General Public License v3.0 ou ultérieure.\n"
            "Le traitement des documents est réalisé localement.\n\n"
            "Les bibliothèques intégrées conservent leurs licences respectives. "
            "Le code source de chaque version publiée sera accessible depuis le site officiel."
        ),
        style="Body.TLabel",
        wraplength=600,
        justify="left",
    ).pack(anchor="w")

    actions = ttk.Frame(dialog, style="App.TFrame", padding=(18, 0, 18, 18))
    actions.pack(fill="x")
    ttk.Button(actions, text="Fermer", command=dialog.destroy).pack(side="right")
    ttk.Button(
        actions,
        text="Visiter loucodi.fr",
        command=lambda: webbrowser.open("https://loucodi.fr"),
    ).pack(side="right", padx=8)
    ttk.Button(
        actions,
        text="Voir le code source",
        command=lambda: webbrowser.open(
            "https://github.com/preventionpaca/pdf-converter-lou-codi"
        ),
    ).pack(side="right", padx=8)
    translate_widget_tree(dialog)
    center_window(dialog, 700, 430)
    make_modal(dialog, parent)
    dialog.wait_window()
