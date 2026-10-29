from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from ..i18n import translate_widget_tree
from ..paths import downloads_directory
from .windowing import make_modal, maximize_window
from .input_dialogs import ask_text

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"


def versioned_save_target(target: Path) -> Path:
    """Return target or the first free ``_N`` version beside it."""
    if not target.exists():
        return target
    for index in range(1, 10_000):
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError("Impossible de trouver un nom de version disponible.")


class DirectoryPicker(tk.Toplevel):
    def __init__(self, parent: tk.Misc, initial_directory: Path) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
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
        translate_widget_tree(self)
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
        ttk.Button(
            navigation,
            text="＋ Nouveau dossier",
            command=self._new_folder,
        ).pack(side="left", padx=(8, 0))
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

    def _new_folder(self) -> None:
        name = ask_text(self, "Nouveau dossier", "Nom du nouveau dossier :", "Nouveau dossier")
        if not name:
            return
        name = name.strip()
        if not name or any(character in name for character in '/\\\0'):
            messagebox.showerror("Nom incorrect", "Choisissez un nom de dossier simple.", parent=self)
            return
        target = self.current_directory / name
        try:
            target.mkdir()
        except FileExistsError:
            messagebox.showwarning("Dossier existant", "Un dossier porte déjà ce nom.", parent=self)
            return
        except OSError as exc:
            messagebox.showerror("Création impossible", str(exc), parent=self)
            return
        self._show_directory(target)


def choose_directory(parent: tk.Misc, initial_directory: Path) -> Path | None:
    picker = DirectoryPicker(parent, initial_directory)
    picker.wait_window()
    return picker.selected_directory


def choose_save_path(
    parent: tk.Misc,
    initial_directory: Path,
    initial_name: str,
    suffix: str,
) -> Path | None:
    """Choose folder and filename in one window, versioning by default."""
    picker = SavePathPicker(parent, initial_directory, initial_name, suffix)
    picker.wait_window()
    return picker.selected_path


class SavePathPicker(tk.Toplevel):
    """Single-step save dialog showing folders and existing peer documents."""

    def __init__(
        self,
        parent: tk.Misc,
        initial_directory: Path,
        initial_name: str,
        suffix: str,
    ) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title("Enregistrer sous")
        self.minsize(900, 650)
        self.configure(bg=BACKGROUND)
        self.selected_path: Path | None = None
        self.current_directory = (
            initial_directory if initial_directory.is_dir() else downloads_directory()
        ).expanduser().resolve()
        self.suffix = suffix if suffix.startswith(".") else f".{suffix}"
        self.visible_suffixes = {self.suffix.lower()}
        if self.suffix.lower() == ".cod":
            self.visible_suffixes.update({".code", ".loucodi-document"})
        clean_initial = Path(initial_name).name
        if Path(clean_initial).suffix.lower() not in self.visible_suffixes:
            clean_initial = f"{clean_initial}{self.suffix}"
        self.name_var = tk.StringVar(value=clean_initial)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.path_text = tk.StringVar(value=str(self.current_directory))
        self.preview_text = tk.StringVar()
        self.paths: dict[str, Path] = {}
        self._build()
        translate_widget_tree(self)
        self._show_directory(self.current_directory)
        self._update_preview()
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
            header, text="Enregistrer sous", bg=NAVY, fg="white",
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
            navigation, text="↑ Dossier parent",
            command=lambda: self._show_directory(self.current_directory.parent),
        ).pack(side="left")
        ttk.Button(navigation, text="＋ Nouveau dossier", command=self._new_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(navigation, text="↻ Actualiser", command=self._refresh).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(navigation, textvariable=self.path_text).pack(side="left", padx=16)

        table_frame = ttk.Frame(self, padding=(20, 0, 20, 10))
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("modified", "size"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Nom du fichier ou dossier")
        self.tree.heading("modified", text="Modifié le")
        self.tree.heading("size", text="Taille")
        self.tree.column("#0", width=650, minwidth=320, stretch=True)
        self.tree.column("modified", width=180, anchor="center", stretch=False)
        self.tree.column("size", width=110, anchor="e", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", self._open_selected)
        self.tree.bind("<<TreeviewSelect>>", self._selected)

        form = ttk.Frame(self, padding=(20, 4, 20, 4))
        form.pack(fill="x")
        ttk.Label(form, text="Nom du fichier").pack(side="left")
        name_entry = ttk.Entry(form, textvariable=self.name_var)
        name_entry.pack(side="left", fill="x", expand=True, padx=(10, 14))
        name_entry.bind("<Return>", lambda _event: self._accept())
        self.name_var.trace_add("write", lambda *_args: self._update_preview())
        ttk.Checkbutton(
            form,
            text="Écraser le fichier existant",
            variable=self.overwrite_var,
            command=self._update_preview,
        ).pack(side="right")

        footer = ttk.Frame(self, padding=(20, 4, 20, 18))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.preview_text).pack(side="left")
        ttk.Button(footer, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            footer, text="Enregistrer", style="Primary.TButton", command=self._accept,
        ).pack(side="right")
        name_entry.focus_set()
        name_entry.selection_range(0, "end")

    def _show_directory(self, directory: Path) -> None:
        try:
            directory = directory.expanduser().resolve()
            entries = [
                path for path in directory.iterdir()
                if path.is_dir() or path.suffix.lower() in self.visible_suffixes
            ]
            entries.sort(key=lambda path: (not path.is_dir(), path.name.casefold()))
        except (OSError, PermissionError) as exc:
            messagebox.showerror("Dossier inaccessible", str(exc), parent=self)
            return
        self.current_directory = directory
        self.path_text.set(str(directory))
        self.paths.clear()
        self.tree.delete(*self.tree.get_children())
        for path in entries:
            try:
                statistics = path.stat()
            except OSError:
                continue
            modified = datetime.fromtimestamp(statistics.st_mtime).strftime("%d/%m/%Y %H:%M")
            size = "" if path.is_dir() else _format_size(statistics.st_size)
            prefix = "📁  " if path.is_dir() else "📄  "
            item = self.tree.insert("", "end", text=prefix + path.name, values=(modified, size))
            self.paths[item] = path
        self._update_preview()

    def _refresh(self) -> None:
        self._show_directory(self.current_directory)

    def _open_selected(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.tree.selection()
        if len(selection) != 1:
            return
        path = self.paths.get(selection[0])
        if path is None:
            return
        if path.is_dir():
            self._show_directory(path)
        else:
            self.name_var.set(path.name)

    def _selected(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.tree.selection()
        if len(selection) == 1:
            path = self.paths.get(selection[0])
            if path is not None and path.is_file():
                self.name_var.set(path.name)

    def _new_folder(self) -> None:
        name = ask_text(self, "Nouveau dossier", "Nom du nouveau dossier :", "Nouveau dossier")
        if not name:
            return
        name = name.strip()
        if not name or any(character in name for character in '/\\\0'):
            messagebox.showerror("Nom incorrect", "Choisissez un nom de dossier simple.", parent=self)
            return
        target = self.current_directory / name
        try:
            target.mkdir()
        except FileExistsError:
            messagebox.showwarning("Dossier existant", "Un dossier porte déjà ce nom.", parent=self)
            return
        except OSError as exc:
            messagebox.showerror("Création impossible", str(exc), parent=self)
            return
        self._show_directory(target)

    def _typed_target(self) -> Path | None:
        name = self.name_var.get().strip()
        if not name:
            return None
        safe_name = Path(name).name
        if safe_name != name or safe_name in {".", ".."}:
            return None
        target = self.current_directory / safe_name
        if target.suffix.lower() != self.suffix.lower():
            target = target.with_suffix(self.suffix)
        return target

    def _update_preview(self) -> None:
        target = self._typed_target()
        if target is None:
            self.preview_text.set("Indiquez un nom de fichier.")
            return
        final = target if self.overwrite_var.get() else versioned_save_target(target)
        if final != target:
            self.preview_text.set(f"Le nom existe : enregistrement automatique sous {final.name}")
        elif target.exists():
            self.preview_text.set(f"Le fichier {target.name} sera remplacé.")
        else:
            self.preview_text.set(f"Le fichier sera enregistré sous {final.name}")

    def _accept(self) -> None:
        target = self._typed_target()
        if target is None:
            messagebox.showerror(
                "Nom incorrect", "Indiquez uniquement le nom du fichier.", parent=self
            )
            return
        if not self.overwrite_var.get():
            target = versioned_save_target(target)
        self.selected_path = target
        self.destroy()


def _format_size(byte_count: int) -> str:
    if byte_count < 1_048_576:
        return f"{byte_count / 1024:.0f} Ko"
    return f"{byte_count / 1_048_576:.1f} Mo"
