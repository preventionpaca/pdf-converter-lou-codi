from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Literal

import pymupdf
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

from ..i18n import tr, translate_widget_tree
from ..paths import downloads_directory
from ..services.destinations import google_drive_destination, set_google_drive_destination
from .directory_picker import choose_directory
from .input_dialogs import ask_text
from .windowing import make_modal, maximize_window

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"
SortColumn = Literal["name", "modified", "size"]


def _sorted_entries(
    directory: Path,
    allowed_suffixes: set[str],
    sort_column: SortColumn,
    descending: bool,
) -> list[tuple[Path, float, int]]:
    """Read a directory afresh and return visible entries in the requested order."""
    rows: list[tuple[Path, float, int]] = []
    for path in directory.iterdir():
        if not (path.is_dir() or path.suffix.lower() in allowed_suffixes):
            continue
        try:
            statistics = path.stat()
        except OSError:
            continue
        rows.append((path, statistics.st_mtime, statistics.st_size))

    def value(row: tuple[Path, float, int]) -> str | float | int:
        path, modified, size = row
        if sort_column == "modified":
            return modified
        if sort_column == "size":
            return size
        return path.name.casefold()

    # Directories remain grouped above files, while each group follows the
    # selected ordering. This keeps navigation predictable even for a size sort.
    directories = [row for row in rows if row[0].is_dir()]
    files = [row for row in rows if not row[0].is_dir()]
    directories.sort(key=value, reverse=descending)
    files.sort(key=value, reverse=descending)
    return directories + files


class PdfPicker(tk.Toplevel):
    """Large, predictable PDF picker starting in the Downloads directory."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        allowed_suffixes: set[str] | None = None,
        window_title: str = "Choisir des PDF — Téléchargements",
        heading: str = "Choisir les documents PDF",
        accept_label: str = "Ajouter les PDF sélectionnés",
        selection_help: str = "Sélectionnez un ou plusieurs documents PDF.",
        initial_directory: Path | None = None,
    ) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title(window_title)
        self.minsize(850, 600)
        self.configure(bg=BACKGROUND)
        self.transient(parent)
        self.selected_files: list[Path] = []
        self.allowed_suffixes = allowed_suffixes or {".pdf"}
        self.heading = heading
        self.accept_label = accept_label
        self.selection_help = selection_help
        self.current_directory = (
            initial_directory if initial_directory and initial_directory.is_dir() else downloads_directory()
        )
        self.paths: dict[str, Path] = {}
        self.view_mode = tk.StringVar(value="tiles")
        self.tile_paths: list[Path] = []
        self.tile_selection: set[Path] = set()
        self.tile_anchor = -1
        self.tile_images: dict[Path, ImageTk.PhotoImage] = {}
        self.tile_cards: dict[Path, tk.Frame] = {}
        # A file picker is most useful when the document just downloaded is
        # immediately visible. Users can then switch to name or size sorting.
        self.sort_column: SortColumn = "modified"
        self.sort_descending = True
        self.path_text = tk.StringVar(value=str(self.current_directory))
        self._build()
        translate_widget_tree(self)
        self._show_directory(self.current_directory)
        maximize_window(self)
        make_modal(self, parent)

    def _build(self) -> None:
        root = self._root()
        app_icon = getattr(root, "app_icon", None)
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
            text=self.heading,
            bg=NAVY,
            fg="white",
            font=("Sans", 18, "bold"),
        ).pack(side="left")
        ttk.Button(
            header,
            text="Revenir à Téléchargements",
            command=lambda: self._show_directory(downloads_directory()),
        ).pack(side="right")
        ttk.Button(
            header,
            text="☁ Google Drive",
            command=self._open_google_drive,
        ).pack(side="right", padx=(0, 8))

        navigation = ttk.Frame(self, padding=(20, 14))
        navigation.pack(fill="x")
        ttk.Button(
            navigation,
            text="↑ Dossier parent",
            command=lambda: self._show_directory(self.current_directory.parent),
        ).pack(side="left")
        ttk.Button(navigation, text="＋ Nouveau dossier", command=self._new_folder).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(
            navigation,
            text="↻ Actualiser",
            command=self._refresh_current_directory,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(navigation, textvariable=self.path_text).pack(side="left", padx=16)
        ttk.Button(
            navigation,
            text="▦ Panneaux illustrés",
            command=lambda: self._set_view("tiles"),
        ).pack(side="right")
        ttk.Button(
            navigation,
            text="☰ Liste",
            command=lambda: self._set_view("list"),
        ).pack(side="right", padx=(0, 8))

        self.content_frame = ttk.Frame(self)
        self.content_frame.pack(fill="both", expand=True)
        self.table_frame = ttk.Frame(self.content_frame, padding=(20, 0, 20, 12))
        self.tree = ttk.Treeview(
            self.table_frame,
            columns=("modified", "size"),
            show="tree headings",
            selectmode="extended",
        )
        self.tree.heading("#0", command=lambda: self._change_sort("name"))
        self.tree.heading("modified", command=lambda: self._change_sort("modified"))
        self.tree.heading("size", command=lambda: self._change_sort("size"))
        self.tree.column("#0", width=650, minwidth=300, stretch=True)
        self.tree.column("modified", width=180, stretch=False, anchor="center")
        self.tree.column("size", width=120, stretch=False, anchor="e")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(self.table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<Double-1>", self._double_click)
        self.bind("<FocusIn>", self._refresh_on_focus, add="+")
        self._update_headings()

        self.tiles_frame = ttk.Frame(self.content_frame, padding=(20, 0, 20, 12))
        self.tiles_canvas = tk.Canvas(
            self.tiles_frame,
            bg="#FFFFFF",
            highlightthickness=1,
            highlightbackground="#C7D2E0",
        )
        self.tiles_canvas.pack(side="left", fill="both", expand=True)
        tile_scrollbar = ttk.Scrollbar(self.tiles_frame, command=self.tiles_canvas.yview)
        tile_scrollbar.pack(side="right", fill="y")
        self.tiles_canvas.configure(yscrollcommand=tile_scrollbar.set)
        self.tiles_body = tk.Frame(self.tiles_canvas, bg="#FFFFFF")
        self.tiles_window = self.tiles_canvas.create_window(
            (0, 0), window=self.tiles_body, anchor="nw"
        )
        self.tiles_body.bind(
            "<Configure>",
            lambda _event: self.tiles_canvas.configure(
                scrollregion=self.tiles_canvas.bbox("all")
            ),
        )
        self.tiles_canvas.bind("<Configure>", self._resize_tiles)
        self.bind("<MouseWheel>", self._scroll_tiles, add="+")
        self._set_view("tiles")

        footer = ttk.Frame(self, padding=(20, 6, 20, 18))
        footer.pack(fill="x")
        ttk.Label(footer, text="Ctrl ou Maj : sélectionner plusieurs fichiers").pack(side="left")
        ttk.Button(footer, text="Annuler", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            footer,
            text=self.accept_label,
            style="Primary.TButton",
            command=self._accept,
        ).pack(side="right")

    def _show_directory(self, directory: Path) -> None:
        try:
            directory = directory.expanduser().resolve()
            entries = _sorted_entries(
                directory,
                self.allowed_suffixes,
                self.sort_column,
                self.sort_descending,
            )
        except (OSError, PermissionError) as exc:
            messagebox.showerror("Dossier inaccessible", str(exc), parent=self)
            return
        self.current_directory = directory
        self.path_text.set(str(directory))
        self.paths.clear()
        self.tree.delete(*self.tree.get_children())
        for path, modified_timestamp, byte_count in entries:
            modified = datetime.fromtimestamp(modified_timestamp).strftime("%d/%m/%Y %H:%M")
            size = "" if path.is_dir() else _format_size(byte_count)
            prefix = "📁  " if path.is_dir() else "📄  "
            item = self.tree.insert("", "end", text=prefix + path.name, values=(modified, size))
            self.paths[item] = path
        self.tile_paths = [row[0] for row in entries]
        self.tile_selection.intersection_update(self.tile_paths)
        self._render_tiles(entries)

    def _set_view(self, mode: str) -> None:
        selected = self._selected_paths()
        self.view_mode.set(mode)
        if mode == "tiles":
            self.table_frame.pack_forget()
            self.tiles_frame.pack(fill="both", expand=True)
            self.tile_selection.update(selected)
            self._paint_tile_selection()
        else:
            self.tiles_frame.pack_forget()
            self.table_frame.pack(fill="both", expand=True)
            self._select_tree_paths(selected)

    def _resize_tiles(self, event: tk.Event[tk.Misc]) -> None:
        self.tiles_canvas.itemconfigure(self.tiles_window, width=max(1, event.width))
        self._layout_tile_cards(max(1, event.width))

    def _scroll_tiles(self, event: tk.Event[tk.Misc]) -> None:
        if self.view_mode.get() == "tiles" and self.winfo_exists():
            self.tiles_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _render_tiles(self, entries: list[tuple[Path, float, int]]) -> None:
        for child in self.tiles_body.winfo_children():
            child.destroy()
        self.tile_cards.clear()
        self.tile_images.clear()
        for index, (path, modified_timestamp, byte_count) in enumerate(entries):
            card = tk.Frame(
                self.tiles_body,
                bg="#F7FAFD",
                highlightthickness=2,
                highlightbackground="#D5DFEA",
                cursor="hand2",
                padx=8,
                pady=8,
            )
            picture = self._tile_image(path)
            self.tile_images[path] = picture
            image_label = tk.Label(card, image=picture, bg="#F7FAFD", borderwidth=0)
            image_label.pack(pady=(0, 6))
            name_label = tk.Label(
                card,
                text=path.name,
                bg="#F7FAFD",
                fg=NAVY,
                font=("Sans", 9, "bold"),
                wraplength=165,
                justify="center",
            )
            name_label.pack(fill="x")
            modified = datetime.fromtimestamp(modified_timestamp).strftime("%d/%m/%Y")
            size = "Dossier" if path.is_dir() else _format_size(byte_count)
            details = tk.Label(
                card,
                text=f"{modified}  •  {size}",
                bg="#F7FAFD",
                fg="#5A6B7D",
                font=("Sans", 8),
            )
            details.pack(pady=(4, 0))
            for widget in (card, image_label, name_label, details):
                widget.bind(
                    "<Button-1>",
                    lambda event, item_index=index: self._tile_click(event, item_index),
                )
                widget.bind(
                    "<Double-1>",
                    lambda _event, item_path=path: self._tile_double_click(item_path),
                )
            self.tile_cards[path] = card
        self._layout_tile_cards(max(700, self.tiles_canvas.winfo_width()))
        self._paint_tile_selection()

    def _layout_tile_cards(self, width: int) -> None:
        if not self.tile_cards:
            return
        columns = max(2, width // 210)
        for index, path in enumerate(self.tile_paths):
            card = self.tile_cards.get(path)
            if card is not None:
                card.grid(
                    row=index // columns,
                    column=index % columns,
                    padx=10,
                    pady=10,
                    sticky="nsew",
                )
        for column in range(columns):
            self.tiles_body.grid_columnconfigure(column, weight=1, uniform="tiles")

    def _tile_image(self, path: Path) -> ImageTk.PhotoImage:
        image = _illustrated_thumbnail(path)
        return ImageTk.PhotoImage(image)

    def _tile_click(self, event: tk.Event[tk.Misc], index: int) -> None:
        if not 0 <= index < len(self.tile_paths):
            return
        path = self.tile_paths[index]
        control = bool(event.state & 0x0004)
        shift = bool(event.state & 0x0001)
        if shift and self.tile_anchor >= 0:
            start, end = sorted((self.tile_anchor, index))
            if not control:
                self.tile_selection.clear()
            self.tile_selection.update(self.tile_paths[start : end + 1])
        elif control:
            if path in self.tile_selection:
                self.tile_selection.remove(path)
            else:
                self.tile_selection.add(path)
            self.tile_anchor = index
        else:
            self.tile_selection = {path}
            self.tile_anchor = index
        self._paint_tile_selection()

    def _tile_double_click(self, path: Path) -> None:
        if path.is_dir():
            self._show_directory(path)
        else:
            self.tile_selection = {path}
            self._accept()

    def _paint_tile_selection(self) -> None:
        for path, card in self.tile_cards.items():
            selected = path in self.tile_selection
            background = "#E6F1FF" if selected else "#F7FAFD"
            card.configure(
                bg=background,
                highlightbackground="#1F6FB2" if selected else "#D5DFEA",
            )
            for child in card.winfo_children():
                try:
                    child.configure(bg=background)
                except tk.TclError:
                    pass

    def _change_sort(self, column: SortColumn) -> None:
        if column == self.sort_column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = column in {"modified", "size"}
        self._update_headings()
        self._refresh_current_directory()

    def _update_headings(self) -> None:
        labels: dict[SortColumn, str] = {
            "name": tr("Nom du fichier ou dossier"),
            "modified": tr("Modifié le"),
            "size": tr("Taille"),
        }
        tree_columns = {"name": "#0", "modified": "modified", "size": "size"}
        for column, label in labels.items():
            marker = " ▼" if self.sort_descending else " ▲"
            self.tree.heading(
                tree_columns[column],
                text=label + (marker if column == self.sort_column else ""),
            )

    def _refresh_current_directory(self) -> None:
        selected_paths = self._selected_paths()
        self._show_directory(self.current_directory)
        self.tile_selection.update(selected_paths)
        self._select_tree_paths(selected_paths)
        self._paint_tile_selection()

    def _selected_paths(self) -> set[Path]:
        if self.view_mode.get() == "tiles":
            return set(self.tile_selection)
        return {self.paths[item] for item in self.tree.selection() if item in self.paths}

    def _select_tree_paths(self, paths: set[Path]) -> None:
        self.tree.selection_remove(*self.tree.selection())
        for item, path in self.paths.items():
            if path in paths:
                self.tree.selection_add(item)

    def _refresh_on_focus(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is self:
            self._refresh_current_directory()

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
        paths = list(self._selected_paths())
        directories = [path for path in paths if path.is_dir()]
        files = [
            path
            for path in paths
            if path.is_file() and path.suffix.lower() in self.allowed_suffixes
        ]
        if files:
            self.selected_files = files
            self.destroy()
            return
        if len(directories) == 1:
            self._show_directory(directories[0])
            return
        messagebox.showinfo(
            "Sélection",
            self.selection_help,
            parent=self,
        )

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

    def _open_google_drive(self) -> None:
        """Open the current user's Google Drive, asking only the first time."""
        directory = google_drive_destination()
        if directory is None:
            if not messagebox.askyesno(
                "Configurer Google Drive",
                "Le dossier Google Drive n’est pas encore configuré sur cet ordinateur.\n\n"
                "Voulez-vous le choisir maintenant ?",
                parent=self,
            ):
                return
            selected = choose_directory(self, Path.home())
            if selected is None:
                return
            try:
                set_google_drive_destination(selected)
            except ValueError as exc:
                messagebox.showerror("Dossier Google Drive incorrect", str(exc), parent=self)
                return
            directory = selected
        self._show_directory(directory)


def choose_pdfs(parent: tk.Misc) -> list[Path]:
    picker = PdfPicker(parent)
    picker.wait_window()
    return picker.selected_files


def choose_documents(
    parent: tk.Misc,
    allowed_suffixes: set[str],
    *,
    initial_directory: Path | None = None,
    window_title: str = "Choisir des documents ou images — Téléchargements",
    heading: str = "Choisir les documents ou images",
    accept_label: str = "Ajouter les fichiers sélectionnés",
    selection_help: str = "Sélectionnez un ou plusieurs documents ou images pris en charge.",
) -> list[Path]:
    picker = PdfPicker(
        parent,
        allowed_suffixes=allowed_suffixes,
        window_title=window_title,
        heading=heading,
        accept_label=accept_label,
        selection_help=selection_help,
        initial_directory=initial_directory,
    )
    picker.wait_window()
    return picker.selected_files


def _format_size(byte_count: int) -> str:
    if byte_count < 1_048_576:
        return f"{byte_count / 1024:.0f} Ko"
    return f"{byte_count / 1_048_576:.1f} Mo"


def _illustrated_thumbnail(path: Path, size: tuple[int, int] = (170, 108)) -> Image.Image:
    """Create a quick visual tile without depending on the desktop icon theme."""
    width, height = size
    canvas = Image.new("RGBA", size, "#FFFFFF")
    try:
        if path.is_dir():
            drawing = ImageDraw.Draw(canvas)
            drawing.rounded_rectangle(
                (24, 28, width - 24, height - 17),
                radius=9,
                fill="#F4C542",
                outline="#C49516",
                width=2,
            )
            drawing.rounded_rectangle(
                (31, 18, 86, 43),
                radius=6,
                fill="#FFD96A",
                outline="#C49516",
                width=2,
            )
            return canvas

        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}:
            with Image.open(path) as source:
                preview = ImageOps.exif_transpose(source).convert("RGBA")
                preview.thumbnail((width - 10, height - 10), Image.Resampling.LANCZOS)
                canvas.alpha_composite(
                    preview,
                    ((width - preview.width) // 2, (height - preview.height) // 2),
                )
                return canvas

        if suffix == ".pdf":
            with pymupdf.open(path) as document:
                if document.page_count:
                    pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(0.28, 0.28), alpha=False)
                    preview = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).convert("RGBA")
                    preview.thumbnail((width - 10, height - 10), Image.Resampling.LANCZOS)
                    canvas.alpha_composite(
                        preview,
                        ((width - preview.width) // 2, (height - preview.height) // 2),
                    )
                    return canvas

        if suffix in {".cod", ".code", ".loucodi-document"}:
            icon = Path(__file__).resolve().parents[1] / "assets" / "lou-codi-document.png"
            if icon.is_file():
                with Image.open(icon) as source:
                    preview = source.convert("RGBA")
                    preview.thumbnail((width - 16, height - 8), Image.Resampling.LANCZOS)
                    canvas.alpha_composite(
                        preview,
                        ((width - preview.width) // 2, (height - preview.height) // 2),
                    )
                    return canvas
    except (OSError, ValueError, pymupdf.FileDataError):
        pass

    drawing = ImageDraw.Draw(canvas)
    drawing.rounded_rectangle(
        (43, 8, width - 43, height - 8),
        radius=7,
        fill="#EDF4FB",
        outline="#8AA6C3",
        width=2,
    )
    extension = (path.suffix[1:] or "FICHIER").upper()[:8]
    font = ImageFont.load_default(size=16)
    box = drawing.textbbox((0, 0), extension, font=font)
    drawing.text(
        ((width - (box[2] - box[0])) / 2, (height - (box[3] - box[1])) / 2),
        extension,
        fill=NAVY,
        font=font,
    )
    return canvas
