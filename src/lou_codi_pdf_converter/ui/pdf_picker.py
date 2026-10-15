from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from ..paths import downloads_directory
from .windowing import make_modal, maximize_window

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"


class PdfPicker(tk.Toplevel):
    """Large, predictable PDF picker starting in the Downloads directory."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("Choisir des PDF — Téléchargements")
        self.minsize(850, 600)
        self.configure(bg=BACKGROUND)
        self.transient(parent)
        self.selected_files: list[Path] = []
        self.current_directory = downloads_directory()
        self.paths: dict[str, Path] = {}
        self.path_text = tk.StringVar(value=str(self.current_directory))
        self._build()
        self._show_directory(self.current_directory)
        maximize_window(self)
        make_modal(self, parent)

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, padx=22, pady=16)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Choisir les documents PDF",
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
            columns=("modified", "size"),
            show="tree headings",
            selectmode="extended",
        )
        self.tree.heading("#0", text="Nom du fichier ou dossier")
        self.tree.heading("modified", text="Modifié le")
        self.tree.heading("size", text="Taille")
        self.tree.column("#0", width=650, minwidth=300, stretch=True)
        self.tree.column("modified", width=180, stretch=False, anchor="center")
        self.tree.column("size", width=120, stretch=False, anchor="e")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", self._double_click)

        footer = ttk.Frame(self, padding=(20, 6, 20, 18))
        footer.pack(fill="x")
        ttk.Label(footer, text="Ctrl ou Maj : sélectionner plusieurs PDF").pack(side="left")
        ttk.Button(footer, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            footer,
            text="Ajouter les PDF sélectionnés",
            style="Primary.TButton",
            command=self._accept,
        ).pack(side="right")

    def _show_directory(self, directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda path: (not path.is_dir(), path.name.casefold()))
        except (OSError, PermissionError) as exc:
            messagebox.showerror("Dossier inaccessible", str(exc), parent=self)
            return
        self.current_directory = directory
        self.path_text.set(str(directory))
        self.paths.clear()
        self.tree.delete(*self.tree.get_children())
        for path in entries:
            if not (path.is_dir() or path.suffix.lower() == ".pdf"):
                continue
            try:
                statistics = path.stat()
            except OSError:
                continue
            modified = datetime.fromtimestamp(statistics.st_mtime).strftime("%d/%m/%Y %H:%M")
            size = "" if path.is_dir() else _format_size(statistics.st_size)
            prefix = "📁  " if path.is_dir() else "📄  "
            item = self.tree.insert("", "end", text=prefix + path.name, values=(modified, size))
            self.paths[item] = path

    def _double_click(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.tree.selection()
        if len(selection) != 1:
            return
        path = self.paths.get(selection[0])
        if path and path.is_dir():
            self._show_directory(path)
        elif path:
            self._accept()

    def _accept(self) -> None:
        paths = [self.paths[item] for item in self.tree.selection() if item in self.paths]
        directories = [path for path in paths if path.is_dir()]
        files = [path for path in paths if path.is_file() and path.suffix.lower() == ".pdf"]
        if files:
            self.selected_files = files
            self.destroy()
            return
        if len(directories) == 1:
            self._show_directory(directories[0])
            return
        messagebox.showinfo(
            "Sélection",
            "Sélectionnez un ou plusieurs documents PDF.",
            parent=self,
        )


def choose_pdfs(parent: tk.Misc) -> list[Path]:
    picker = PdfPicker(parent)
    picker.wait_window()
    return picker.selected_files


def _format_size(byte_count: int) -> str:
    if byte_count < 1_048_576:
        return f"{byte_count / 1024:.0f} Ko"
    return f"{byte_count / 1_048_576:.1f} Mo"
