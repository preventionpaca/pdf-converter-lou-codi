from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import __version__
from ..i18n import translate_widget_tree
from .windowing import center_window, make_modal

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"

LICENSE_ROWS = (
    ("Lou Còdi Workshop", "AGPL-3.0-or-later", "Application"),
    ("Python", "PSF License", "Moteur d’exécution"),
    ("SQLite", "Domaine public", "Stockage local intégré à Python"),
    ("PyMuPDF / MuPDF", "AGPL-3.0 ou commerciale", "PDF et aperçus"),
    ("pypdf", "BSD-3-Clause", "Lecture, écriture et organisation PDF"),
    ("pdfplumber", "MIT", "Extraction de texte et de tableaux"),
    ("pdf2docx", "MIT", "Conversion vers DOCX"),
    ("openpyxl", "MIT", "Création de classeurs XLSX"),
    ("Pillow", "MIT-CMU", "Traitement d’images"),
    ("ReportLab", "BSD", "Création de documents PDF"),
    ("python-docx", "MIT", "Création de documents DOCX"),
    ("arabic-reshaper", "MIT", "Affichage de l’arabe"),
    ("python-bidi", "LGPL-3.0-or-later", "Texte bidirectionnel"),
)


def _build_header(dialog: tk.Toplevel) -> None:
    icon = getattr(dialog._root(), "app_icon", None)
    if icon is not None:
        dialog.iconphoto(False, icon)
    header = tk.Frame(dialog, bg=NAVY, padx=24, pady=16)
    header.pack(fill="x")
    if icon is not None:
        dialog.about_logo = icon.subsample(17, 17)
        tk.Label(header, image=dialog.about_logo, bg=NAVY).pack(side="left", padx=(0, 14))
    title = tk.Frame(header, bg=NAVY)
    title.pack(side="left")
    tk.Label(
        title, text="À propos et licences", bg=NAVY, fg="white", font=("Sans", 17, "bold")
    ).pack(anchor="w")
    tk.Label(
        title,
        text="Lou Còdi Workshop — des outils pratiques, en local, pour créer et fabriquer",
        bg=NAVY,
        fg="#CBDFF5",
        font=("Sans", 9),
    ).pack(anchor="w")


def _build_about_tab(tab: ttk.Frame) -> None:
    card = ttk.Frame(tab, style="Card.TFrame", padding=24)
    card.pack(fill="both", expand=True, padx=12, pady=12)
    ttk.Label(
        card, text=f"Lou Còdi Workshop — version {__version__}", style="Title.TLabel"
    ).pack(anchor="w")
    ttk.Label(
        card,
        text=(
            "Logiciel libre développé par Lou Còdi — Club de programmation.\n\n"
            "Les documents sont traités localement : ils ne sont pas envoyés sur Internet. "
            "Le projet est distribué sous licence GNU Affero General Public License v3.0 "
            "ou ultérieure. Les composants tiers conservent leurs propres licences.\n\n"
            "SQLite est disponible localement avec Python, sans serveur ni abonnement. "
            "Le raccourci ChatGPT ouvre un service externe dans le navigateur, mais Lou Còdi "
            "n’y transmet automatiquement aucun document ni aucun texte."
        ),
        style="Body.TLabel",
        wraplength=720,
        justify="left",
    ).pack(anchor="w", pady=(14, 18))
    privacy = tk.Frame(card, bg="#E8F4EF", padx=16, pady=12)
    privacy.pack(fill="x")
    tk.Label(
        privacy,
        text="✓  Traitement local — aucun document transmis sur Internet",
        bg="#E8F4EF",
        fg="#176747",
        font=("Sans", 11, "bold"),
    ).pack(anchor="w")


def _build_licenses_tab(tab: ttk.Frame) -> None:
    card = ttk.Frame(tab, style="Card.TFrame", padding=18)
    card.pack(fill="both", expand=True, padx=12, pady=12)
    ttk.Label(card, text="Composants distribués avec l’application", style="Title.TLabel").pack(
        anchor="w", pady=(0, 8)
    )
    ttk.Label(
        card,
        text="Cette liste synthétique ne remplace pas les textes complets, regroupés dans le dossier « licenses » de la distribution.",
        style="Body.TLabel",
        wraplength=760,
        justify="left",
    ).pack(anchor="w", pady=(0, 12))
    tree_frame = ttk.Frame(card, style="Card.TFrame")
    tree_frame.pack(fill="both", expand=True)
    columns = ("component", "license", "usage")
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12)
    tree.heading("component", text="Composant")
    tree.heading("license", text="Licence")
    tree.heading("usage", text="Utilisation")
    tree.column("component", width=190, anchor="w")
    tree.column("license", width=175, anchor="w")
    tree.column("usage", width=350, anchor="w")
    scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    for row in LICENSE_ROWS:
        tree.insert("", "end", values=row)


def show_about(parent: tk.Misc) -> None:
    dialog = tk.Toplevel(parent, class_="Loucodiworkshop")
    dialog.title("À propos et licences")
    dialog.configure(bg=BACKGROUND)
    dialog.resizable(True, True)
    dialog.minsize(720, 520)
    _build_header(dialog)
    notebook = ttk.Notebook(dialog)
    notebook.pack(fill="both", expand=True, padx=18, pady=(18, 10))
    about_tab = ttk.Frame(notebook, style="App.TFrame")
    licenses_tab = ttk.Frame(notebook, style="App.TFrame")
    notebook.add(about_tab, text="À propos")
    notebook.add(licenses_tab, text="Licences")
    _build_about_tab(about_tab)
    _build_licenses_tab(licenses_tab)

    actions = ttk.Frame(dialog, style="App.TFrame", padding=(18, 0, 18, 18))
    actions.pack(fill="x")
    ttk.Button(actions, text="Fermer", command=dialog.destroy).pack(side="right")
    ttk.Button(
        actions, text="Visiter loucodi.fr", command=lambda: webbrowser.open("https://loucodi.fr")
    ).pack(side="right", padx=8)
    ttk.Button(
        actions,
        text="Voir le code source",
        command=lambda: webbrowser.open("https://github.com/preventionpaca/pdf-converter-lou-codi"),
    ).pack(side="right", padx=8)
    ttk.Button(
        actions,
        text="Licence du projet",
        command=lambda: webbrowser.open(
            "https://github.com/preventionpaca/pdf-converter-lou-codi/blob/main/LICENSE"
        ),
    ).pack(side="left")
    translate_widget_tree(dialog)
    center_window(dialog, 860, 620)
    make_modal(dialog, parent)
    dialog.wait_window()
