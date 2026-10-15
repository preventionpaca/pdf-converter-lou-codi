from __future__ import annotations

import tkinter as tk
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import messagebox, ttk

import pymupdf
from pypdf import PdfReader

from ..paths import collision_free_target, downloads_directory
from ..services.pdf_organizer import PagePlan, assemble_pdf, suggested_organized_stem
from ..system import open_path
from .dialogs import show_success
from .directory_picker import choose_directory
from .pdf_picker import choose_pdfs
from .windowing import make_modal, maximize_window

BACKGROUND = "#F0F4F9"
NAVY = "#193B66"
MUTED = "#597089"


@dataclass(frozen=True)
class PageItem:
    uid: str
    source: Path | None
    page_index: int | None
    rotation: int = 0
    width: float = 595
    height: float = 842

    def plan(self) -> PagePlan:
        return PagePlan(self.source, self.page_index, self.rotation, self.width, self.height)


class OrganizePdfWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, class_="LouCodiPdfConverter")
        self.title("Organiser les PDF — PDF Converter Lou Còdi")
        self.minsize(900, 650)
        self.configure(bg=BACKGROUND)
        maximize_window(self)
        self.pages: list[PageItem] = []
        self.undo_stack: list[list[PageItem]] = []
        self.redo_stack: list[list[PageItem]] = []
        self.thumbnails: dict[str, tk.PhotoImage] = {}
        self.drag_item: str | None = None
        self.drag_snapshot: list[PageItem] | None = None
        self.last_output: Path | None = None
        self.destination = tk.StringVar(value=str(downloads_directory()))
        self._build()
        make_modal(self, parent)

    def _build(self) -> None:
        app_icon = getattr(self._root(), "app_icon", None)
        if app_icon is not None:
            self.iconphoto(False, app_icon)
        header = tk.Frame(self, bg=NAVY, padx=22, pady=10)
        header.pack(fill="x")
        if app_icon is not None:
            self.workspace_logo = app_icon.subsample(17, 17)
            tk.Label(header, image=self.workspace_logo, bg=NAVY, borderwidth=0).pack(
                side="left", padx=(0, 14)
            )
        titles = tk.Frame(header, bg=NAVY)
        titles.pack(side="left")
        tk.Label(titles, text="Organiser les PDF", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(anchor="w")
        tk.Label(
            titles,
            text="Réorganiser, fusionner, extraire, dupliquer et faire pivoter les pages",
            bg=NAVY,
            fg="#CBDFF5",
            font=("Sans", 10),
        ).pack(anchor="w")

        body = ttk.Frame(self, style="App.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        toolbar = ttk.Frame(body, style="Card.TFrame", padding=12)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="Ajouter des PDF…", command=self._add_pdfs).pack(side="left")
        ttk.Button(toolbar, text="Page blanche", command=self._insert_blank).pack(side="left", padx=6)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(toolbar, text="↑ Monter", command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(toolbar, text="↓ Descendre", command=lambda: self._move(1)).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Dupliquer", command=self._duplicate).pack(side="left")
        ttk.Button(toolbar, text="↻ Rotation 90°", command=self._rotate).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Supprimer", command=self._delete).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.undo_button = ttk.Button(toolbar, text="Annuler", command=self._undo, state="disabled")
        self.undo_button.pack(side="left")
        self.redo_button = ttk.Button(toolbar, text="Rétablir", command=self._redo, state="disabled")
        self.redo_button.pack(side="left", padx=6)
        ttk.Button(toolbar, text="Tout vider", command=self._clear).pack(side="right")

        table_frame = ttk.Frame(body, style="Card.TFrame", padding=12)
        table_frame.pack(fill="both", expand=True, pady=(0, 10))
        ttk.Style(self).configure("Organizer.Treeview", rowheight=145)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("position", "source", "page", "rotation"),
            show="tree headings",
            selectmode="extended",
            # Keep the requested height below the available workspace so the
            # validation controls always remain visible. The frame expands to
            # use any additional screen space.
            height=3,
            style="Organizer.Treeview",
        )
        self.tree.heading("#0", text="Aperçu")
        self.tree.heading("position", text="Ordre")
        self.tree.heading("source", text="Document source")
        self.tree.heading("page", text="Page")
        self.tree.heading("rotation", text="Rotation")
        self.tree.column("#0", width=135, minwidth=120, stretch=False)
        self.tree.column("position", width=70, anchor="center", stretch=False)
        self.tree.column("source", width=540, stretch=True)
        self.tree.column("page", width=80, anchor="center", stretch=False)
        self.tree.column("rotation", width=100, anchor="center", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<ButtonPress-1>", self._drag_start)
        self.tree.bind("<B1-Motion>", self._drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._drag_end)
        self.tree.bind("<Delete>", lambda _event: self._delete())

        destination = ttk.Frame(body, style="Card.TFrame", padding=12)
        destination.pack(fill="x", pady=(0, 10))
        ttk.Label(destination, text="Destination", style="Title.TLabel").pack(side="left")
        ttk.Entry(destination, textvariable=self.destination).pack(side="left", fill="x", expand=True, padx=12)
        ttk.Button(destination, text="Parcourir…", command=self._choose_destination).pack(side="left")

        actions = ttk.Frame(body, style="App.TFrame")
        actions.pack(fill="x")
        ttk.Button(
            actions,
            text="Valider et exporter le PDF",
            style="Primary.TButton",
            command=self._export,
        ).pack(side="left")
        self.open_button = ttk.Button(actions, text="Ouvrir le résultat", command=self._open_output, state="disabled")
        self.open_button.pack(side="left", padx=10)
        self.status = ttk.Label(
            actions,
            text="Ajoutez un ou plusieurs PDF.",
            background=BACKGROUND,
            foreground=MUTED,
        )
        self.status.pack(side="right")

    def _add_pdfs(self) -> None:
        sources = choose_pdfs(self)
        if not sources:
            return
        self._remember()
        for source in sources:
            try:
                reader = PdfReader(source)
                document = pymupdf.open(source)
                for index, page in enumerate(reader.pages):
                    rect = page.mediabox
                    item = PageItem(
                        uuid.uuid4().hex,
                        source,
                        index,
                        width=float(rect.width),
                        height=float(rect.height),
                    )
                    self.pages.append(item)
                    self.thumbnails[item.uid] = self._render_thumbnail(document[index])
                document.close()
            except Exception as exc:  # noqa: BLE001 - isoler chaque PDF importé
                messagebox.showerror("Import impossible", f"{source.name}\n\n{exc}", parent=self)
        self._refresh()

    def _render_thumbnail(self, page: pymupdf.Page) -> tk.PhotoImage:
        scale = min(110 / page.rect.width, 135 / page.rect.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return tk.PhotoImage(data=pixmap.tobytes("png"))

    def _blank_thumbnail(self, uid: str) -> tk.PhotoImage:
        image = tk.PhotoImage(width=96, height=132)
        image.put("#FFFFFF", to=(0, 0, 96, 132))
        image.put("#C8D1DB", to=(0, 0, 96, 2))
        image.put("#C8D1DB", to=(0, 130, 96, 132))
        image.put("#C8D1DB", to=(0, 0, 2, 132))
        image.put("#C8D1DB", to=(94, 0, 96, 132))
        self.thumbnails[uid] = image
        return image

    def _refresh(self, selection: set[str] | None = None) -> None:
        selection = selection or set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for position, item in enumerate(self.pages, 1):
            thumbnail = self.thumbnails.get(item.uid) or self._blank_thumbnail(item.uid)
            source = item.source.name if item.source else "Page blanche"
            page_number = str(item.page_index + 1) if item.page_index is not None else "—"
            self.tree.insert(
                "",
                "end",
                iid=item.uid,
                image=thumbnail,
                text="  ",
                values=(position, source, page_number, f"{item.rotation}°"),
            )
        existing = [uid for uid in selection if self.tree.exists(uid)]
        if existing:
            self.tree.selection_set(existing)
            self.tree.see(existing[0])
        self.status.configure(text=f"{len(self.pages)} page(s) dans le document.")
        self.undo_button.configure(state="normal" if self.undo_stack else "disabled")
        self.redo_button.configure(state="normal" if self.redo_stack else "disabled")

    def _remember(self) -> None:
        self.undo_stack.append(list(self.pages))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _selected_indices(self) -> list[int]:
        selected = set(self.tree.selection())
        return [index for index, item in enumerate(self.pages) if item.uid in selected]

    def _move(self, offset: int) -> None:
        indices = self._selected_indices()
        if len(indices) != 1:
            return
        index = indices[0]
        target = index + offset
        if target < 0 or target >= len(self.pages):
            return
        self._remember()
        self.pages[index], self.pages[target] = self.pages[target], self.pages[index]
        self._refresh({self.pages[target].uid})

    def _duplicate(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        self._remember()
        insertion = indices[-1] + 1
        duplicates = [replace(self.pages[index], uid=uuid.uuid4().hex) for index in indices]
        for original_index, duplicate in zip(indices, duplicates, strict=True):
            self.thumbnails[duplicate.uid] = self.thumbnails[self.pages[original_index].uid]
        self.pages[insertion:insertion] = duplicates
        self._refresh({item.uid for item in duplicates})

    def _insert_blank(self) -> None:
        indices = self._selected_indices()
        insertion = indices[-1] + 1 if indices else len(self.pages)
        self._remember()
        item = PageItem(uuid.uuid4().hex, None, None)
        self.pages.insert(insertion, item)
        self._blank_thumbnail(item.uid)
        self._refresh({item.uid})

    def _rotate(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        self._remember()
        selected: set[str] = set()
        for index in indices:
            item = self.pages[index]
            self.pages[index] = replace(item, rotation=(item.rotation + 90) % 360)
            selected.add(item.uid)
        self._refresh(selected)

    def _delete(self) -> None:
        indices = self._selected_indices()
        if not indices:
            return
        self._remember()
        selected = set(self.tree.selection())
        self.pages = [item for item in self.pages if item.uid not in selected]
        self._refresh()

    def _clear(self) -> None:
        if not self.pages:
            return
        self._remember()
        self.pages.clear()
        self._refresh()

    def _undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(list(self.pages))
        self.pages = self.undo_stack.pop()
        self._refresh()

    def _redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(list(self.pages))
        self.pages = self.redo_stack.pop()
        self._refresh()

    def _drag_start(self, event: tk.Event[tk.Misc]) -> None:
        item = self.tree.identify_row(event.y)
        if item:
            self.drag_item = item
            self.drag_snapshot = list(self.pages)

    def _drag_motion(self, event: tk.Event[tk.Misc]) -> None:
        target = self.tree.identify_row(event.y)
        if self.drag_item and target and target != self.drag_item:
            self.tree.move(self.drag_item, "", self.tree.index(target))

    def _drag_end(self, _event: tk.Event[tk.Misc]) -> None:
        if not self.drag_item or self.drag_snapshot is None:
            return
        by_uid = {item.uid: item for item in self.pages}
        reordered = [by_uid[uid] for uid in self.tree.get_children()]
        if reordered != self.pages:
            self.undo_stack.append(self.drag_snapshot)
            self.redo_stack.clear()
            self.pages = reordered
            self._refresh({self.drag_item})
        self.drag_item = None
        self.drag_snapshot = None

    def _choose_destination(self) -> None:
        selected = choose_directory(self, Path(self.destination.get()).expanduser())
        if selected:
            self.destination.set(str(selected))

    def _export(self) -> None:
        if not self.pages:
            messagebox.showwarning("Document vide", "Ajoutez au moins une page.", parent=self)
            return
        destination = Path(self.destination.get()).expanduser()
        if not destination.is_dir():
            messagebox.showerror("Dossier introuvable", "Choisissez un dossier existant.", parent=self)
            return
        plans = [item.plan() for item in self.pages]
        target = collision_free_target(
            destination,
            suggested_organized_stem(plans),
            ".pdf",
        )
        self.configure(cursor="watch")
        self.status.configure(text="Export du PDF…")
        self.update_idletasks()
        try:
            assemble_pdf(plans, target)
        except Exception as exc:  # noqa: BLE001 - présenter l’erreur d’export
            messagebox.showerror("Export impossible", str(exc), parent=self)
            return
        finally:
            self.configure(cursor="")
        self.last_output = target
        self.open_button.configure(state="normal")
        self.status.configure(text=f"PDF créé : {target.name}")
        show_success(
            self,
            "Export terminé",
            f"Le document a été créé dans :\n\n{target}",
            action_label="Ouvrir le PDF",
            action=lambda: open_path(target),
        )

    def _open_output(self) -> None:
        if self.last_output and self.last_output.is_file():
            open_path(self.last_output)
