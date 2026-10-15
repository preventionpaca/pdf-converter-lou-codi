from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from ..paths import downloads_directory
from .windowing import make_modal, maximize_window

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"


class DirectoryPicker(tk.Toplevel):
    def __init__(self, parent: tk.Misc, initial_directory: Path) -> None:
        super().__init__(parent, class_="LouCodiPdfConverter")
        self.title("Choisir le dossier de destination")
        self.minsize(850, 600)
        self.configure(bg=BACKGROUND)
        self.selected_directory: Path | None = None
        self.current_directory = (
            initial_directory if initial_directory.is_dir() else downloads_directory()
        )
        self.paths: dict[str, Path] = {}
        self.path_text = tk.StringVar(value=str(self.current_directory))
        self._build()
        self._show_directory(self.current_directory)
        maximize_window(self)
        make_modal(self, parent)

    def _build(self) -> None:
        app_icon = getattr(self._root(), "app_icon", None)
        if app_icon is not None:
            self.iconphoto(False, app_icon)
        header = tk.Frame(self, bg=NAVY, padx=22, pady=10)
        header.pack(fill="x")
        if app_icon is not None:
            self.picker_logo = app_icon.subsample(17, 17)
            tk.Label(header, image=self.picker_logo, bg=NAVY, borderwidth=0).pack(
                side="left", padx=(0, 14)
            )
        tk.Label(
            header,
            text="Choisir le dossier de destination",
            bg=NAVY,
            fg="white",
            font=("Sans", 18, "bold"),
        ).pack(side="left")
        ttk.Button(
            header,
            text="Revenir à Téléchargements",
            command=lambda: self._show_directory(downloads_directory()),
        ).pack(side="right")

        navigation = ttk.Frame(self, padding=(20, 14))
        navigation.pack(fill="x")
        ttk.Button(
            navigation,
            text="↑ Dossier parent",
            command=lambda: self._show_directory(self.current_directory.parent),
        ).pack(side="left")
        ttk.Label(navigation, textvariable=self.path_text).pack(side="left", padx=16)

        table_frame = ttk.Frame(self, padding=(20, 0, 20, 12))
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("modified",),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Dossier")
        self.tree.heading("modified", text="Modifié le")
        self.tree.column("#0", width=800, minwidth=350, stretch=True)
        self.tree.column("modified", width=190, anchor="center", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", self._open_selected)

        footer = ttk.Frame(self, padding=(20, 6, 20, 18))
        footer.pack(fill="x")
        ttk.Label(footer, text="Double-cliquez sur un dossier pour l’ouvrir.").pack(side="left")
        ttk.Button(footer, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            footer,
            text="Choisir ce dossier",
            style="Primary.TButton",
            command=self._accept_current,
        ).pack(side="right")

    def _show_directory(self, directory: Path) -> None:
        try:
            entries = sorted(
                (path for path in directory.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            )
        except (OSError, PermissionError) as exc:
            messagebox.showerror("Dossier inaccessible", str(exc), parent=self)
            return
        self.current_directory = directory
        self.path_text.set(str(directory))
        self.paths.clear()
        self.tree.delete(*self.tree.get_children())
        for path in entries:
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%d/%m/%Y %H:%M"
                )
            except OSError:
                continue
            item = self.tree.insert("", "end", text="📁  " + path.name, values=(modified,))
            self.paths[item] = path

    def _open_selected(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.tree.selection()
        if len(selection) == 1 and selection[0] in self.paths:
            self._show_directory(self.paths[selection[0]])

    def _accept_current(self) -> None:
        self.selected_directory = self.current_directory
        self.destroy()


def choose_directory(parent: tk.Misc, initial_directory: Path) -> Path | None:
    picker = DirectoryPicker(parent, initial_directory)
    picker.wait_window()
    return picker.selected_directory

