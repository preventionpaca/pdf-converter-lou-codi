from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Callable
from tkinter import ttk

from ..i18n import translate_widget_tree
from ..support import SUPPORT_URL
from .windowing import center_window, make_modal

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"
MUTED = "#597089"


def _support_dialog(
    parent: tk.Misc,
    *,
    title: str,
    heading: str,
    message: str,
    primary_label: str,
    primary_action: Callable[[], None],
    secondary_label: str,
    allow_disable: bool = False,
) -> bool:
    dialog = tk.Toplevel(parent, class_="LouCodiPdfConverter")
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.configure(bg=BACKGROUND)
    app_icon = getattr(dialog._root(), "app_icon", None)
    if app_icon is not None:
        dialog.iconphoto(False, app_icon)

    header = tk.Frame(dialog, bg=NAVY, padx=22, pady=14)
    header.pack(fill="x")
    if app_icon is not None:
        dialog.support_logo = app_icon.subsample(18, 18)
        tk.Label(header, image=dialog.support_logo, bg=NAVY, borderwidth=0).pack(
            side="left", padx=(0, 12)
        )
    tk.Label(header, text=heading, bg=NAVY, fg="white", font=("Sans", 16, "bold")).pack(
        side="left"
    )

    content = ttk.Frame(dialog, style="Card.TFrame", padding=(28, 24))
    content.pack(fill="both", expand=True, padx=18, pady=(18, 10))
    ttk.Label(
        content,
        text=message,
        style="Body.TLabel",
        wraplength=610,
        justify="left",
    ).pack(anchor="w")

    disable_var = tk.BooleanVar(value=False)
    if allow_disable:
        ttk.Checkbutton(
            content,
            text="Ne plus afficher les rappels de soutien",
            variable=disable_var,
        ).pack(anchor="w", pady=(18, 0))

    buttons = ttk.Frame(dialog, style="App.TFrame", padding=(18, 8, 18, 18))
    buttons.pack(fill="x")
    ttk.Button(buttons, text=secondary_label, command=dialog.destroy).pack(side="right")

    def run_primary() -> None:
        primary_action()
        dialog.destroy()

    ttk.Button(
        buttons,
        text=primary_label,
        style="Primary.TButton",
        command=run_primary,
    ).pack(side="right", padx=(0, 10))

    translate_widget_tree(dialog)
    center_window(dialog, 720, 370 if allow_disable else 340)
    make_modal(dialog, parent)
    dialog.wait_window()
    return disable_var.get()


def show_welcome(parent: tk.Misc) -> None:
    _support_dialog(
        parent,
        title="Bienvenue",
        heading="Bienvenue dans PDF Converter – Lou Còdi",
        message=(
            "Ce logiciel est mis gratuitement à votre disposition par Lou Còdi, club de "
            "programmation. Il est le fruit d’un travail bénévole et tous les traitements "
            "de vos documents sont réalisés localement sur votre ordinateur.\n\n"
            "Vous pourrez soutenir librement la création et la maintenance de nouveaux "
            "outils, sans jamais bloquer l’utilisation du logiciel."
        ),
        primary_label="Découvrir Lou Còdi",
        primary_action=lambda: webbrowser.open("https://loucodi.fr"),
        secondary_label="Commencer",
    )


def show_support_reminder(parent: tk.Misc) -> bool:
    return _support_dialog(
        parent,
        title="Soutenir Lou Còdi",
        heading="Merci d’utiliser PDF Converter – Lou Còdi",
        message=(
            "PDF Converter est mis gratuitement à votre disposition par Lou Còdi. "
            "Votre contribution volontaire aide le club à financer la création, la "
            "maintenance et la mise à disposition de nouveaux outils respectueux de "
            "votre vie privée.\n\nVous pouvez également continuer gratuitement."
        ),
        primary_label="Soutenir Lou Còdi ♥",
        primary_action=lambda: webbrowser.open(SUPPORT_URL),
        secondary_label="Continuer gratuitement",
        allow_disable=True,
    )
