from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..services.destinations import (
    document_destination,
    favorite_destinations,
    resolve_existing_directory,
    save_favorite_destinations,
    set_document_destination,
)
from .windowing import center_window, make_modal
from .directory_picker import choose_directory


def configure_document_destinations(parent: tk.Misc) -> None:
    """Edit the default document folder and a short list of named shortcuts."""
    dialog = tk.Toplevel(parent, class_="Loucodiworkshop")
    dialog.title("Dossiers et favoris — Lou Còdi Workshop")
    dialog.configure(bg="#F0F4F9")
    center_window(dialog, 760, 500)

    default_var = tk.StringVar(value=str(document_destination()))
    label_var = tk.StringVar()
    path_var = tk.StringVar()
    favorites = favorite_destinations()

    body = ttk.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="Dossier par défaut de Document Studio", font=("Sans", 13, "bold")).pack(anchor="w")
    default_row = ttk.Frame(body)
    default_row.pack(fill="x", pady=(6, 18))
    ttk.Entry(default_row, textvariable=default_var).pack(side="left", fill="x", expand=True)

    def browse(variable: tk.StringVar) -> None:
        selected = choose_directory(dialog, Path(variable.get() or Path.home()))
        if selected:
            variable.set(str(selected))

    ttk.Button(default_row, text="Parcourir…", command=lambda: browse(default_var)).pack(side="left", padx=(8, 0))
    ttk.Label(body, text="Favoris d’enregistrement", font=("Sans", 13, "bold")).pack(anchor="w")
    ttk.Label(
        body,
        text="Ajoutez par exemple “Drive — Réunions” ou “Drive — Animation automobile”.",
    ).pack(anchor="w", pady=(2, 8))

    listbox = tk.Listbox(body, height=8)
    listbox.pack(fill="both", expand=True)

    def refresh() -> None:
        listbox.delete(0, "end")
        for label, directory in favorites:
            listbox.insert("end", f"{label}  —  {directory}")

    def select_favorite(_event: object = None) -> None:
        selection = listbox.curselection()
        if selection:
            label, directory = favorites[selection[0]]
            label_var.set(label)
            path_var.set(str(directory))

    listbox.bind("<<ListboxSelect>>", select_favorite)
    refresh()

    form = ttk.Frame(body)
    form.pack(fill="x", pady=8)
    ttk.Entry(form, textvariable=label_var, width=25).pack(side="left")
    ttk.Entry(form, textvariable=path_var).pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(form, text="Parcourir…", command=lambda: browse(path_var)).pack(side="left")

    def add_or_update() -> None:
        label = label_var.get().strip()
        directory = resolve_existing_directory(Path(path_var.get()))
        if not label or directory is None:
            messagebox.showerror("Favori incorrect", "Indiquez un nom et un dossier existant.", parent=dialog)
            return
        selection = listbox.curselection()
        if selection:
            favorites[selection[0]] = (label, directory)
        else:
            favorites.append((label, directory))
        label_var.set("")
        path_var.set("")
        listbox.selection_clear(0, "end")
        refresh()

    def remove() -> None:
        selection = listbox.curselection()
        if selection:
            favorites.pop(selection[0])
            refresh()

    actions = ttk.Frame(body)
    actions.pack(fill="x")
    ttk.Button(actions, text="Ajouter ou modifier", command=add_or_update).pack(side="left")
    ttk.Button(actions, text="Retirer", command=remove).pack(side="left", padx=8)

    def save() -> None:
        default = resolve_existing_directory(Path(default_var.get()))
        if default is None:
            messagebox.showerror("Dossier incorrect", "Le dossier par défaut doit exister.", parent=dialog)
            return
        set_document_destination(default)
        save_favorite_destinations(favorites)
        dialog.destroy()

    footer = ttk.Frame(body)
    footer.pack(fill="x", pady=(18, 0))
    ttk.Button(footer, text="Annuler", command=dialog.destroy).pack(side="right")
    ttk.Button(footer, text="Enregistrer", command=save).pack(side="right", padx=8)
    make_modal(dialog, parent)
