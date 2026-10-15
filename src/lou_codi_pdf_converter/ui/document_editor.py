from __future__ import annotations

import copy
import tempfile
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import colorchooser, messagebox, ttk

import pymupdf
from PIL import Image, ImageTk

from ..i18n import settings_path, translate_widget_tree
from ..paths import collision_free_target, downloads_directory
from ..services.canvas_document import (
    A4_HEIGHT,
    A4_WIDTH,
    CanvasDocument,
    PageObject,
    export_canvas_pdf,
    pages_for_object,
    resolve_dynamic_text,
)
from ..services.docx_canvas import export_editable_docx
from ..services.table_formulas import evaluate_table
from ..system import open_path
from .input_dialogs import ask_table_size, ask_text, edit_table, pick_symbol
from .pdf_picker import choose_documents
from .windowing import make_modal, maximize_window

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"


class DocumentEditorWindow(tk.Toplevel):
    """Editeur de pages : PDF original ou A4 blanc, avec objets indépendants."""

    def __init__(self, parent: tk.Misc, *, template_mode: bool = False) -> None:
        super().__init__(parent, class_="LouCodiPdfConverter")
        self.template_mode = template_mode
        self.title(("Créer un modèle" if template_mode else "Créer un document") + " — PDF Converter Lou Còdi")
        self.configure(bg=BACKGROUND)
        self.document = CanvasDocument()
        self.project_path: Path | None = None
        self.last_export: Path | None = None
        self.current_page = 0
        self.selected: int | None = None
        self.selected_indices: set[int] = set()
        self.zoom = 0.85
        self.undo_stack: list[CanvasDocument] = []
        self.redo_stack: list[CanvasDocument] = []
        self._background_image: ImageTk.PhotoImage | None = None
        self._overlay_images: list[ImageTk.PhotoImage] = []
        self._drag_origin: tuple[float, float, float, float] | None = None
        self._resize_origin: tuple[float, float, float, float] | None = None
        self._drag_positions: dict[int, tuple[float, float]] = {}
        self._drag_before: CanvasDocument | None = None
        self._editing_widget: tk.Text | None = None
        self._format_clipboard: dict[str, object] | None = None
        icon = getattr(self._root(), "app_icon", None)
        if icon is not None:
            self.iconphoto(False, icon)
        self._build()
        translate_widget_tree(self)
        maximize_window(self)
        make_modal(self, parent)
        self.after_idle(self._render)

    def _build(self) -> None:
        self._build_menu()
        ttk.Style(self).configure("EditorTool.TButton", padding=(5, 2), font=("Sans", 10))
        header = tk.Frame(self, bg=NAVY, padx=22, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Créer un modèle" if self.template_mode else "Créer un document", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(side="left")
        tk.Label(header, text="Mise en page locale — canevas A4/PDF", bg=NAVY, fg="#CBDFF5", font=("Sans", 10)).pack(side="left", padx=18)

        formatting = ttk.Frame(self, style="App.TFrame", padding=(12, 5))
        formatting.pack(fill="x")
        self._buttons(formatting, (
            ("↶", self._undo), ("↷", self._redo),
            ("B", lambda: self._toggle("bold")), ("I", lambda: self._toggle("italic")),
            ("≡←", lambda: self._align("left")), ("≡↔", lambda: self._align("center")),
            ("→≡", lambda: self._align("right")), ("≡", lambda: self._align("justify")),
        ))
        ttk.Label(formatting, text="Police", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.font_family_var = tk.StringVar(value="Sans-serif")
        font_family = ttk.Combobox(
            formatting,
            textvariable=self.font_family_var,
            values=("Sans-serif", "Serif", "Monospace", "Cursive", "Symboles"),
            state="readonly",
            width=11,
        )
        font_family.pack(side="left", padx=2)
        font_family.bind("<<ComboboxSelected>>", lambda _event: self._apply_font_family())
        ttk.Label(formatting, text="Taille", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.font_size_var = tk.StringVar(value="12")
        font_size = ttk.Combobox(
            formatting,
            textvariable=self.font_size_var,
            values=("8", "9", "10", "11", "12", "14", "16", "18", "20", "24", "28", "32", "36", "48", "60", "72"),
            width=5,
        )
        font_size.pack(side="left", padx=2)
        font_size.bind("<<ComboboxSelected>>", lambda _event: self._apply_font_size())
        font_size.bind("<Return>", lambda _event: self._apply_font_size())
        ttk.Button(formatting, text="🎨", command=self._choose_color).pack(side="left", padx=2)
        ttk.Separator(formatting, orient="vertical").pack(side="left", fill="y", padx=8)
        self._buttons(formatting, (
            ("T+", self._add_text), ("▧", self._add_image), ("▤", self._add_table),
            ("□", self._add_mask), ("╱", self._add_line), ("Ω", self._insert_symbol),
            ("•", lambda: self._make_list(False)),
            ("1.", lambda: self._make_list(True)), ("⌗", self._copy_format), ("✓⌗", self._apply_format),
        ))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12, pady=(2, 0))
        canvas_frame = ttk.Frame(body, style="App.TFrame")
        body.add(canvas_frame, weight=5)
        self.canvas = tk.Canvas(canvas_frame, bg="#C8D0DA", highlightthickness=0)
        xbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-1>", self._edit_selected)

        panel = ttk.Frame(body, style="Card.TFrame", padding=14)
        body.add(panel, weight=1)
        ttk.Label(panel, text="OBJET SÉLECTIONNÉ", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.kind_label = ttk.Label(panel, text="Aucun objet", style="Body.TLabel")
        self.kind_label.pack(anchor="w", pady=(0, 8))
        self.property_vars: dict[str, tk.StringVar] = {}
        for key, label in (("x", "X"), ("y", "Y"), ("width", "Largeur"), ("height", "Hauteur"), ("font_size", "Taille du texte")):
            ttk.Label(panel, text=label, style="Body.TLabel").pack(anchor="w")
            var = tk.StringVar()
            self.property_vars[key] = var
            ttk.Entry(panel, textvariable=var).pack(fill="x", pady=(0, 6))
        ttk.Button(panel, text="Appliquer les coordonnées", style="Primary.TButton", command=self._apply_properties).pack(fill="x", pady=4)
        ttk.Button(panel, text="Modifier le contenu", command=self._edit_selected).pack(fill="x", pady=4)
        ttk.Label(panel, text="Appliquer sur", style="Body.TLabel").pack(anchor="w", pady=(10, 0))
        self.scope_var = tk.StringVar(value="Cette page")
        self.scope_box = ttk.Combobox(
            panel,
            textvariable=self.scope_var,
            values=("Cette page", "Toutes les pages", "Pages choisies"),
            state="readonly",
        )
        self.scope_box.pack(fill="x", pady=(0, 5))
        self.scope_box.bind("<<ComboboxSelected>>", lambda _event: self._apply_scope())
        ttk.Label(panel, text="Pages (ex. 1,3-5)", style="Body.TLabel").pack(anchor="w")
        self.pages_var = tk.StringVar()
        pages_entry = ttk.Entry(panel, textvariable=self.pages_var)
        pages_entry.pack(fill="x", pady=(0, 5))
        pages_entry.bind("<Return>", lambda _event: self._apply_scope())
        ttk.Button(panel, text="Appliquer aux pages", command=self._apply_scope).pack(fill="x", pady=4)
        ttk.Label(panel, text="Glissez un objet pour le déplacer. Double-cliquez pour modifier son contenu.", style="Body.TLabel", wraplength=230, justify="left").pack(anchor="w", pady=14)

        bottom = ttk.Frame(self, style="App.TFrame", padding=(14, 6))
        bottom.pack(fill="x")
        self._buttons(bottom, (("◀ Page précédente", lambda: self._change_page(-1)),))
        self.page_label = ttk.Label(bottom, text="Page 1 / 1", style="Body.TLabel")
        self.page_label.pack(side="left", padx=10)
        self._buttons(bottom, (("Page suivante ▶", lambda: self._change_page(1)), ("+ Page blanche", self._add_blank_page)))
        ttk.Button(bottom, text="−", command=lambda: self._set_zoom(-0.1)).pack(side="right")
        self.zoom_label = ttk.Label(bottom, text="85 %", style="Body.TLabel")
        self.zoom_label.pack(side="right", padx=7)
        ttk.Button(bottom, text="+", command=lambda: self._set_zoom(0.1)).pack(side="right")
        ttk.Label(bottom, text="Zoom", style="Body.TLabel").pack(side="right", padx=5)
        self.status = ttk.Label(self, text="Nouvelle page A4", background=BACKGROUND)
        self.status.pack(fill="x", padx=18, pady=(2, 7))

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        for label, command, accelerator in (
            ("Nouveau document", self._new, "Ctrl+N"),
            ("Ouvrir un projet…", self._load, "Ctrl+O"),
            ("Importer un PDF…", self._import_pdf, ""),
            ("Enregistrer", self._save, "Ctrl+S"),
        ):
            file_menu.add_command(label=label, command=command, accelerator=accelerator)
        file_menu.add_separator()
        file_menu.add_command(label="Exporter en PDF…", command=self._export_pdf)
        file_menu.add_command(label="Exporter en DOCX…", command=self._export_docx)
        file_menu.add_command(label="Imprimer…", command=self._print, accelerator="Ctrl+P")
        file_menu.add_separator()
        file_menu.add_command(label="Fermer", command=self.destroy)
        menu.add_cascade(label="Fichier", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Annuler", command=self._undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Rétablir", command=self._redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Copier le format", command=self._copy_format)
        edit_menu.add_command(label="Appliquer le format", command=self._apply_format)
        edit_menu.add_command(label="Supprimer l’objet", command=self._delete_selected, accelerator="Suppr")
        menu.add_cascade(label="Édition", menu=edit_menu)

        insert_menu = tk.Menu(menu, tearoff=False)
        insert_menu.add_command(label="Zone de texte", command=self._add_text)
        insert_menu.add_command(label="Image…", command=self._add_image)
        insert_menu.add_command(label="Tableau…", command=self._add_table)
        insert_menu.add_command(label="Masque blanc", command=self._add_mask)
        insert_menu.add_command(label="Trait", command=self._add_line)
        insert_menu.add_command(label="Caractère spécial…", command=self._insert_symbol)
        insert_menu.add_separator()
        insert_menu.add_command(label="Graphique en barres lié au tableau", command=lambda: self._add_chart("bar"))
        insert_menu.add_command(label="Camembert lié au tableau", command=lambda: self._add_chart("pie"))
        insert_menu.add_separator()
        insert_menu.add_command(label="En-tête libre", command=lambda: self._add_preset("header"))
        insert_menu.add_command(label="Pied de page libre", command=lambda: self._add_preset("footer"))
        insert_menu.add_command(label="Marge de notes à gauche", command=lambda: self._add_preset("left_margin"))
        fields_menu = tk.Menu(insert_menu, tearoff=False)
        fields_menu.add_command(label="Numéro de page", command=lambda: self._insert_field("{{PAGE}}"))
        fields_menu.add_command(label="Page / nombre total", command=lambda: self._insert_field("Page {{PAGE}} / {{PAGES}}"))
        fields_menu.add_command(label="Date du jour", command=lambda: self._insert_field("{{DATE}}"))
        fields_menu.add_command(label="Nom du document", command=lambda: self._insert_field("{{DOCUMENT}}"))
        insert_menu.add_cascade(label="Champ automatique", menu=fields_menu)
        insert_menu.add_command(label="Page blanche", command=self._add_blank_page)
        menu.add_cascade(label="Insertion", menu=insert_menu)

        format_menu = tk.Menu(menu, tearoff=False)
        format_menu.add_command(label="Gras", command=lambda: self._toggle("bold"))
        format_menu.add_command(label="Italique", command=lambda: self._toggle("italic"))
        format_menu.add_command(label="Couleur du texte…", command=self._choose_color)
        format_menu.add_command(label="Liste à puces", command=lambda: self._make_list(False))
        format_menu.add_command(label="Liste numérotée", command=lambda: self._make_list(True))
        format_menu.add_separator()
        for label, value in (("Aligner à gauche", "left"), ("Centrer", "center"), ("Aligner à droite", "right"), ("Justifier", "justify")):
            format_menu.add_command(label=label, command=lambda alignment=value: self._align(alignment))
        format_menu.add_separator()
        format_menu.add_command(label="Agrandir le cadre", command=lambda: self._resize(1.1))
        format_menu.add_command(label="Réduire le cadre", command=lambda: self._resize(0.9))
        menu.add_cascade(label="Format", menu=format_menu)

        object_menu = tk.Menu(menu, tearoff=False)
        for label, mode in (
            ("Aligner à gauche", "left"), ("Centrer horizontalement", "center"),
            ("Aligner à droite", "right"), ("Aligner en haut", "top"),
            ("Centrer verticalement", "middle"), ("Aligner en bas", "bottom"),
        ):
            object_menu.add_command(label=label, command=lambda value=mode: self._align_objects(value))
        object_menu.add_separator()
        object_menu.add_command(label="Regrouper", command=self._group_selected)
        object_menu.add_command(label="Dissocier", command=self._ungroup_selected)
        menu.add_cascade(label="Objets", menu=object_menu)

        page_menu = tk.Menu(menu, tearoff=False)
        page_menu.add_command(label="Orientation portrait", command=lambda: self._set_orientation("portrait"))
        page_menu.add_command(label="Orientation paysage", command=lambda: self._set_orientation("landscape"))
        page_menu.add_separator()
        page_menu.add_command(label="Page précédente", command=lambda: self._change_page(-1))
        page_menu.add_command(label="Page suivante", command=lambda: self._change_page(1))
        page_menu.add_command(label="Ajouter une page blanche", command=self._add_blank_page)
        menu.add_cascade(label="Page", menu=page_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Zoom avant", command=lambda: self._set_zoom(0.1), accelerator="Ctrl++")
        view_menu.add_command(label="Zoom arrière", command=lambda: self._set_zoom(-0.1), accelerator="Ctrl+-")
        menu.add_cascade(label="Affichage", menu=view_menu)
        self.configure(menu=menu)
        self.bind("<Control-n>", lambda _event: self._new())
        self.bind("<Control-o>", lambda _event: self._load())
        self.bind("<Control-s>", lambda _event: self._save())
        self.bind("<Control-z>", lambda _event: self._undo())
        self.bind("<Control-y>", lambda _event: self._redo())
        self.bind("<Control-p>", lambda _event: self._print())
        self.bind("<Delete>", lambda _event: self._delete_selected())

    @staticmethod
    def _buttons(parent: tk.Misc, items: tuple[tuple[str, object], ...]) -> None:
        for label, command in items:
            ttk.Button(parent, text=label, command=command, style="EditorTool.TButton").pack(side="left", padx=1)

    def _checkpoint(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.document))
        self.undo_stack = self.undo_stack[-80:]
        self.redo_stack.clear()

    def _undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.document))
            self.document = self.undo_stack.pop()
            self._after_history()

    def _redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.document))
            self.document = self.redo_stack.pop()
            self._after_history()

    def _after_history(self) -> None:
        self.current_page = min(self.current_page, self.document.page_count - 1)
        self.selected = None
        self.selected_indices.clear()
        self._render()

    def _new(self) -> None:
        self._checkpoint()
        self.document = CanvasDocument()
        self.project_path = None
        self.current_page = 0
        self.selected = None
        self.selected_indices.clear()
        self.status.configure(text="Nouvelle page A4")
        self._render()

    def _import_pdf(self) -> None:
        files = choose_documents(self, {".pdf"})
        if not files:
            return
        try:
            with pymupdf.open(files[0]) as pdf:
                count = pdf.page_count
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("PDF illisible", str(exc), parent=self)
            return
        self._checkpoint()
        self.document = CanvasDocument(source_pdf=str(files[0]), page_count=max(1, count))
        self.current_page = 0
        self.selected = None
        self.selected_indices.clear()
        self.status.configure(text=f"PDF importé comme document complet : {files[0].name}")
        self._render()

    def _page_size(self) -> tuple[float, float]:
        if self.document.source_pdf and Path(self.document.source_pdf).is_file():
            try:
                with pymupdf.open(self.document.source_pdf) as pdf:
                    if self.current_page < pdf.page_count:
                        rect = pdf[self.current_page].rect
                        return rect.width, rect.height
            except (OSError, RuntimeError, ValueError):
                pass
        return self.document.page_width, self.document.page_height

    def _render(self) -> None:
        self.canvas.delete("all")
        self._overlay_images.clear()
        width, height = self._page_size()
        dw, dh = width * self.zoom, height * self.zoom
        viewport = max(self.canvas.winfo_width(), 900)
        self.page_x, self.page_y = max(30.0, (viewport - dw) / 2), 28.0
        rendered = False
        if self.document.source_pdf and Path(self.document.source_pdf).is_file():
            try:
                with pymupdf.open(self.document.source_pdf) as pdf:
                    if self.current_page < pdf.page_count:
                        pix = pdf[self.current_page].get_pixmap(matrix=pymupdf.Matrix(self.zoom, self.zoom), alpha=False)
                        self._background_image = tk.PhotoImage(data=pix.tobytes("ppm"))
                        self.canvas.create_image(self.page_x, self.page_y, image=self._background_image, anchor="nw")
                        rendered = True
            except (OSError, RuntimeError, ValueError):
                pass
        if not rendered:
            self.canvas.create_rectangle(self.page_x, self.page_y, self.page_x + dw, self.page_y + dh, fill="white", outline="#9AA5B1")
        for index, item in enumerate(self.document.objects):
            if self.current_page in pages_for_object(item, self.document.page_count):
                self._draw_object(index, item)
        self.canvas.configure(scrollregion=(0, 0, max(viewport, self.page_x + dw + 40), self.page_y + dh + 35))
        self.page_label.configure(text=f"Page {self.current_page + 1} / {self.document.page_count}")
        self.zoom_label.configure(text=f"{round(self.zoom * 100)} %")
        self._show_properties()

    def _draw_object(self, index: int, item: PageObject) -> None:
        x, y = self.page_x + item.x * self.zoom, self.page_y + item.y * self.zoom
        w, h = item.width * self.zoom, item.height * self.zoom
        tag, selected = f"object:{index}", index in self.selected_indices
        outline = "#1769AA" if selected else "#72879C"
        tags = (tag, "object")
        if item.kind == "mask":
            self.canvas.create_rectangle(x, y, x + w, y + h, fill=item.fill, outline=outline, width=3 if selected else 1, tags=tags)
        elif item.kind == "image":
            try:
                with Image.open(item.image_path) as source:
                    preview = source.copy()
                preview.thumbnail((max(1, int(w)), max(1, int(h))))
                picture = ImageTk.PhotoImage(preview)
                self._overlay_images.append(picture)
                self.canvas.create_image(x + w / 2, y + h / 2, image=picture, tags=tags)
            except OSError:
                self.canvas.create_text(x + 4, y + 4, text="Image introuvable", anchor="nw", tags=tags)
            self.canvas.create_rectangle(x, y, x + w, y + h, outline=outline, width=3 if selected else 1, tags=tags)
        elif item.kind == "table":
            rows = evaluate_table(item.text)
            columns = max((len(row) for row in rows), default=1)
            rh, cw = h / max(1, len(rows)), w / max(1, columns)
            for row_index, row in enumerate(rows):
                for column_index in range(columns):
                    cx, cy = x + column_index * cw, y + row_index * rh
                    self.canvas.create_rectangle(cx, cy, cx + cw, cy + rh, fill="white", outline="#777", tags=tags)
                    value = row[column_index] if column_index < len(row) else ""
                    self.canvas.create_text(cx + 4, cy + 3, text=value, anchor="nw", width=max(5, cw - 8), font=("Sans", max(7, round(item.font_size * self.zoom))), tags=tags)
            if selected:
                self.canvas.create_rectangle(x, y, x + w, y + h, outline=outline, width=3, tags=tags)
        elif item.kind == "line":
            self.canvas.create_line(x, y, x + w, y + h, fill=item.color, width=max(1, item.font_size / 6), tags=tags)
        elif item.kind == "chart":
            self._draw_chart_preview(item, x, y, w, h, tags)
        else:
            style = "bold italic" if item.bold and item.italic else "bold" if item.bold else "italic" if item.italic else "normal"
            anchor = {"left": "nw", "center": "n", "right": "ne"}.get(item.align, "nw")
            tx = x if item.align in {"left", "justify"} else x + w / 2 if item.align == "center" else x + w
            source_name = Path(self.document.source_pdf).stem if self.document.source_pdf else (self.project_path.stem if self.project_path else "Nouveau document")
            displayed_text = resolve_dynamic_text(item.text, self.current_page, self.document.page_count, source_name)
            self.canvas.create_rectangle(x, y, x + w, y + h, fill="#FFFFFF", stipple="gray12", outline=outline, width=3 if selected else 1, tags=tags)
            family = {"Serif": "Liberation Serif", "Monospace": "Liberation Mono", "Cursive": "URW Chancery L", "Symboles": "Noto Sans Symbols 2"}.get(item.font_family, "Liberation Sans")
            self.canvas.create_text(tx, y + 3, text=displayed_text, fill=item.color, anchor=anchor, justify=item.align if item.align != "justify" else "left", width=max(5, w - 8), font=(family, max(7, round(item.font_size * self.zoom)), style), tags=tags)
        if selected:
            size = 12
            self.canvas.create_rectangle(
                x + w - size / 2,
                y + h - size / 2,
                x + w + size / 2,
                y + h + size / 2,
                fill="#1769AA",
                outline="white",
                tags=(f"resize:{index}", "resize"),
            )

    def _add_object(self, item: PageObject) -> None:
        self._checkpoint()
        self.document.objects.append(item)
        self.selected = len(self.document.objects) - 1
        self.selected_indices = {self.selected}
        self._render()

    def _add_text(self) -> None:
        self._add_object(PageObject("text", self.current_page, 70, 80, 280, 80))
        self.after_idle(lambda: self._start_inline_text_editor(self.document.objects[self.selected]) if self.selected is not None else None)

    def _add_image(self) -> None:
        files = choose_documents(self, {".png", ".jpg", ".jpeg", ".tif", ".tiff"})
        if files:
            self._add_object(PageObject("image", self.current_page, 70, 80, 180, 120, image_path=str(files[0])))

    def _add_mask(self) -> None:
        self._add_object(PageObject("mask", self.current_page, 70, 80, 220, 55))

    def _add_table(self) -> None:
        size = ask_table_size(self)
        if size:
            rows, columns = size
            content = "\n".join("\t".join("" for _ in range(columns)) for _ in range(rows))
            self._add_object(PageObject("table", self.current_page, 70, 80, 360, max(80, rows * 32), text=content, font_size=10))

    def _add_line(self) -> None:
        self._add_object(PageObject("line", self.current_page, 70, 120, 260, 0, font_size=8))

    def _insert_symbol(self) -> None:
        symbol = pick_symbol(self)
        if not symbol:
            return
        if self.selected is not None and self.document.objects[self.selected].kind == "text":
            self._checkpoint()
            self.document.objects[self.selected].text += symbol
            self._render()
        else:
            family = "Flèches" if symbol in "←→↑↓↔⇒⇐➜" else "Symboles"
            self._add_object(PageObject("text", self.current_page, 70, 80, 80, 50, text=symbol, font_size=24, font_family=family))

    def _add_chart(self, chart_type: str) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "table":
            messagebox.showinfo("Graphique", "Sélectionnez d’abord le tableau qui contient les données.", parent=self)
            return
        table = self.document.objects[self.selected]
        self._add_object(PageObject("chart", self.current_page, table.x, table.y + table.height + 25, 320, 210, fill=chart_type, source_id=table.object_id))

    def _draw_chart_preview(self, item: PageObject, x: float, y: float, width: float, height: float, tags: tuple[str, str]) -> None:
        source = next((candidate for candidate in self.document.objects if candidate.object_id == item.source_id), None)
        rows = evaluate_table(source.text) if source else []
        values: list[tuple[str, float]] = []
        for index, row in enumerate(rows):
            try:
                values.append((row[0] or str(index + 1), float(row[-1].replace(",", "."))))
            except (ValueError, IndexError):
                continue
        self.canvas.create_rectangle(x, y, x + width, y + height, fill="white", outline="#72879C", tags=tags)
        if not values:
            self.canvas.create_text(x + width / 2, y + height / 2, text="Aucune donnée numérique", tags=tags)
            return
        colors = ("#2368AF", "#E8642E", "#45A37D", "#F0B738", "#875CB5")
        if item.fill == "pie":
            total = sum(abs(value) for _, value in values) or 1
            start = 0.0
            size = min(width, height) * 0.75
            for index, (_label, value) in enumerate(values):
                extent = 360 * abs(value) / total
                self.canvas.create_arc(x + (width - size) / 2, y + (height - size) / 2, x + (width + size) / 2, y + (height + size) / 2, start=start, extent=extent, fill=colors[index % len(colors)], outline="white", tags=tags)
                start += extent
        else:
            maximum = max(abs(value) for _, value in values) or 1
            gap = width / len(values)
            for index, (label, value) in enumerate(values):
                bar_height = (height - 30) * abs(value) / maximum
                self.canvas.create_rectangle(x + index * gap + 5, y + height - 20 - bar_height, x + (index + 1) * gap - 5, y + height - 20, fill=colors[index % len(colors)], outline="", tags=tags)
                self.canvas.create_text(x + (index + 0.5) * gap, y + height - 10, text=label[:8], font=("Sans", 7), tags=tags)

    def _make_list(self, numbered: bool) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            return
        self._checkpoint()
        item = self.document.objects[self.selected]
        lines = [line.removeprefix("• ").strip() for line in item.text.splitlines()]
        item.text = "\n".join(f"{index + 1}. {line}" if numbered else f"• {line}" for index, line in enumerate(lines))
        self._render()

    def _add_preset(self, kind: str) -> None:
        width, height = self._page_size()
        labels = {
            "header": ("Texte d’en-tête", 45, 30, width - 90, 45),
            "footer": ("Page {{PAGE}} / {{PAGES}}", 45, height - 65, width - 90, 35),
            "left_margin": ("Notes", 18, 90, 90, height - 160),
        }
        text, x, y, object_width, object_height = labels[kind]
        item = PageObject("text", self.current_page, x, y, object_width, object_height, text=text)
        item.pages = "all"
        self._add_object(item)

    def _insert_field(self, token: str) -> None:
        if self.selected is not None and self.document.objects[self.selected].kind == "text":
            self._checkpoint()
            item = self.document.objects[self.selected]
            item.text = f"{item.text} {token}".strip()
            self._render()
            return
        width, height = self._page_size()
        item = PageObject(
            "text",
            self.current_page,
            45,
            height - 65,
            width - 90,
            35,
            text=token,
            align="center",
            pages="all",
        )
        self._add_object(item)

    def _object_at_event(self, event: tk.Event[tk.Misc]) -> int | None:
        current = self.canvas.find_withtag("current")
        if current:
            for tag in self.canvas.gettags(current[0]):
                if tag.startswith("object:"):
                    return int(tag.split(":", 1)[1])
        return None

    def _press(self, event: tk.Event[tk.Misc]) -> None:
        current = self.canvas.find_withtag("current")
        if current:
            for tag in self.canvas.gettags(current[0]):
                if tag.startswith("resize:"):
                    self.selected = int(tag.split(":", 1)[1])
                    item = self.document.objects[self.selected]
                    self._resize_origin = (
                        self.canvas.canvasx(event.x),
                        self.canvas.canvasy(event.y),
                        item.width,
                        item.height,
                    )
                    self._drag_origin = None
                    return
        clicked = self._object_at_event(event)
        control = bool(event.state & 0x0004)
        if clicked is None:
            self.selected = None
            self.selected_indices.clear()
        elif control:
            if clicked in self.selected_indices:
                self.selected_indices.remove(clicked)
            else:
                self.selected_indices.add(clicked)
            self.selected = clicked if clicked in self.selected_indices else next(iter(self.selected_indices), None)
        else:
            self.selected = clicked
            group = self.document.objects[clicked].group
            self.selected_indices = {
                index for index, item in enumerate(self.document.objects) if group and item.group == group
            } or {clicked}
        if self.selected is not None:
            item = self.document.objects[self.selected]
            self._drag_origin = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y), item.x, item.y)
            self._drag_positions = {
                index: (self.document.objects[index].x, self.document.objects[index].y)
                for index in self.selected_indices
            }
            self._drag_before = copy.deepcopy(self.document)
        else:
            self._drag_origin = None
        self._render()

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self.selected is not None and self._resize_origin is not None:
            sx, sy, old_width, old_height = self._resize_origin
            item = self.document.objects[self.selected]
            item.width = max(20, old_width + (self.canvas.canvasx(event.x) - sx) / self.zoom)
            item.height = max(20, old_height + (self.canvas.canvasy(event.y) - sy) / self.zoom)
            self._render()
            return
        if self.selected is None or self._drag_origin is None:
            return
        sx, sy, _object_x, _object_y = self._drag_origin
        pw, ph = self._page_size()
        dx = (self.canvas.canvasx(event.x) - sx) / self.zoom
        dy = (self.canvas.canvasy(event.y) - sy) / self.zoom
        for index, (start_x, start_y) in self._drag_positions.items():
            item = self.document.objects[index]
            item.x = max(0, min(pw - item.width, start_x + dx))
            item.y = max(0, min(ph - item.height, start_y + dy))
        self._render()

    def _release(self, _event: tk.Event[tk.Misc]) -> None:
        if self._resize_origin is not None and self.selected is not None:
            _, _, old_width, old_height = self._resize_origin
            item = self.document.objects[self.selected]
            if (item.width, item.height) != (old_width, old_height):
                snapshot = copy.deepcopy(self.document)
                snapshot.objects[self.selected].width = old_width
                snapshot.objects[self.selected].height = old_height
                self.undo_stack.append(snapshot)
                self.redo_stack.clear()
        self._resize_origin = None
        if self._drag_origin is not None and self._drag_before is not None and any(
            (self.document.objects[index].x, self.document.objects[index].y) != position
            for index, position in self._drag_positions.items()
        ):
            self.undo_stack.append(self._drag_before)
            self.redo_stack.clear()
        self._drag_origin = None
        self._drag_before = None

    def _edit_selected(self, _event: object = None) -> None:
        if self.selected is None:
            return
        item = self.document.objects[self.selected]
        if item.kind not in {"text", "table"}:
            return
        if item.kind == "table":
            value = edit_table(self, item.text)
            if value is not None:
                self._checkpoint()
                item.text = value
                self._render()
            return
        self._start_inline_text_editor(item)

    def _start_inline_text_editor(self, item: PageObject) -> None:
        if self._editing_widget is not None:
            self._editing_widget.destroy()
        x = self.page_x + item.x * self.zoom
        y = self.page_y + item.y * self.zoom
        widget = tk.Text(
            self.canvas,
            wrap="word",
            font=("Liberation Sans", max(8, round(item.font_size * self.zoom))),
            bg="white",
            fg=item.color,
            relief="solid",
            borderwidth=2,
            undo=True,
        )
        widget.insert("1.0", item.text)
        self._editing_widget = widget
        self.canvas.create_window(
            x,
            y,
            window=widget,
            anchor="nw",
            width=max(60, item.width * self.zoom),
            height=max(35, item.height * self.zoom),
            tags=("inline-editor",),
        )

        def finish(_event: object = None) -> None:
            if self._editing_widget is not widget:
                return
            value = widget.get("1.0", "end-1c")
            self._editing_widget = None
            if value != item.text:
                self._checkpoint()
                item.text = value
            widget.destroy()
            self._render()

        widget.bind("<Control-Return>", finish)
        widget.bind("<FocusOut>", finish)
        widget.focus_set()
        widget.tag_configure("align", justify=item.align if item.align != "justify" else "left")
        widget.tag_add("align", "1.0", "end")

    def _mutate(self, mutation: object) -> None:
        if self.selected is not None:
            self._checkpoint()
            mutation(self.document.objects[self.selected])  # type: ignore[operator]
            self._render()

    def _toggle(self, name: str) -> None:
        self._mutate(lambda item: setattr(item, name, not getattr(item, name)))

    def _align(self, value: str) -> None:
        self._mutate(lambda item: setattr(item, "align", value))

    def _choose_color(self) -> None:
        if self.selected is not None:
            chosen = colorchooser.askcolor(self.document.objects[self.selected].color, parent=self)[1]
            if chosen:
                self._mutate(lambda item: setattr(item, "color", chosen))

    def _change_font(self, change: int) -> None:
        self._mutate(lambda item: setattr(item, "font_size", max(6, item.font_size + change)))

    def _apply_font_size(self) -> None:
        try:
            value = max(6.0, min(144.0, float(self.font_size_var.get().replace(",", "."))))
        except ValueError:
            return
        self._mutate(lambda item: setattr(item, "font_size", value))

    def _apply_font_family(self) -> None:
        self._mutate(lambda item: setattr(item, "font_family", self.font_family_var.get()))

    def _resize(self, factor: float) -> None:
        def resize(item: PageObject) -> None:
            item.width, item.height = max(20, item.width * factor), max(20, item.height * factor)
        self._mutate(resize)

    def _copy_format(self) -> None:
        if self.selected is not None:
            item = self.document.objects[self.selected]
            self._format_clipboard = {key: getattr(item, key) for key in ("font_size", "bold", "italic", "align", "color", "fill")}
            self.status.configure(text="Format copié. Sélectionnez un autre objet puis appliquez-le.")

    def _apply_format(self) -> None:
        if not self._format_clipboard:
            return
        def apply(item: PageObject) -> None:
            for key, value in self._format_clipboard.items():
                setattr(item, key, value)
        self._mutate(apply)

    def _delete_selected(self) -> None:
        if self.selected is not None:
            self._checkpoint()
            del self.document.objects[self.selected]
            self.selected = None
            self.selected_indices.clear()
            self._render()

    def _align_objects(self, mode: str) -> None:
        indices = sorted(self.selected_indices)
        if len(indices) < 2:
            return
        self._checkpoint()
        objects = [self.document.objects[index] for index in indices]
        anchor = objects[0]
        for item in objects[1:]:
            if mode == "left":
                item.x = anchor.x
            elif mode == "center":
                item.x = anchor.x + (anchor.width - item.width) / 2
            elif mode == "right":
                item.x = anchor.x + anchor.width - item.width
            elif mode == "top":
                item.y = anchor.y
            elif mode == "middle":
                item.y = anchor.y + (anchor.height - item.height) / 2
            elif mode == "bottom":
                item.y = anchor.y + anchor.height - item.height
        self._render()

    def _group_selected(self) -> None:
        if len(self.selected_indices) < 2:
            return
        self._checkpoint()
        group = uuid.uuid4().hex
        for index in self.selected_indices:
            self.document.objects[index].group = group
        self.status.configure(text="Objets regroupés : ils se déplacent désormais ensemble.")
        self._render()

    def _ungroup_selected(self) -> None:
        if not self.selected_indices:
            return
        self._checkpoint()
        for index in self.selected_indices:
            self.document.objects[index].group = ""
        self.status.configure(text="Objets dissociés.")
        self._render()

    def _show_properties(self) -> None:
        if self.selected is None or self.selected >= len(self.document.objects):
            self.kind_label.configure(text="Aucun objet")
            for var in self.property_vars.values():
                var.set("")
            self.scope_var.set("Cette page")
            self.pages_var.set("")
            return
        item = self.document.objects[self.selected]
        names = {"text": "Zone de texte", "image": "Image", "mask": "Masque", "table": "Tableau", "line": "Trait", "chart": "Graphique"}
        selection = f" — {len(self.selected_indices)} objets" if len(self.selected_indices) > 1 else ""
        self.kind_label.configure(text=names.get(item.kind, item.kind) + selection)
        for key, var in self.property_vars.items():
            var.set(f"{getattr(item, key):.1f}")
        self.font_size_var.set(f"{item.font_size:g}")
        self.font_family_var.set(item.font_family)
        self.scope_var.set("Toutes les pages" if item.pages == "all" else "Pages choisies" if item.pages else "Cette page")
        self.pages_var.set("" if item.pages == "all" else item.pages)

    def _apply_scope(self) -> None:
        if self.selected is None:
            return
        scope = self.scope_var.get()
        pages = "all" if scope == "Toutes les pages" else self.pages_var.get().strip() if scope == "Pages choisies" else ""
        self._mutate(lambda item: setattr(item, "pages", pages))

    def _apply_properties(self) -> None:
        if self.selected is None:
            return
        try:
            values = {key: float(var.get().replace(",", ".")) for key, var in self.property_vars.items()}
        except ValueError:
            messagebox.showerror("Valeur incorrecte", "Utilisez uniquement des nombres.", parent=self)
            return
        def apply(item: PageObject) -> None:
            for key, value in values.items():
                setattr(item, key, max(0 if key in {"x", "y"} else 6, value))
        self._mutate(apply)

    def _change_page(self, change: int) -> None:
        page = self.current_page + change
        if 0 <= page < self.document.page_count:
            self.current_page, self.selected = page, None
            self.selected_indices.clear()
            self._render()

    def _add_blank_page(self) -> None:
        self._checkpoint()
        self.document.page_count += 1
        self.current_page, self.selected = self.document.page_count - 1, None
        self.selected_indices.clear()
        self._render()

    def _set_zoom(self, change: float) -> None:
        self.zoom = max(0.4, min(1.8, self.zoom + change))
        self._render()

    def _set_orientation(self, orientation: str) -> None:
        if self.document.source_pdf:
            messagebox.showinfo("Orientation", "Pour un PDF importé, utilisez le module Organiser les PDF afin de faire pivoter les pages.", parent=self)
            return
        self._checkpoint()
        if orientation == "landscape":
            self.document.page_width, self.document.page_height = max(A4_WIDTH, A4_HEIGHT), min(A4_WIDTH, A4_HEIGHT)
        else:
            self.document.page_width, self.document.page_height = min(A4_WIDTH, A4_HEIGHT), max(A4_WIDTH, A4_HEIGHT)
        self._render()

    def _project_directory(self) -> Path:
        return settings_path().parent / "modeles" if self.template_mode else downloads_directory()

    def _save(self) -> None:
        path = self.project_path
        if path is None:
            name = ask_text(self, "Enregistrer", "Nom du document :", "nouveau_document")
            if not name:
                return
            destination = self._project_directory()
            destination.mkdir(parents=True, exist_ok=True)
            path = collision_free_target(destination, Path(name).stem, ".loucodi-document")
        self.document.save(path)
        self.project_path = path
        self.status.configure(text=f"Projet enregistré : {path.name}")

    def _load(self) -> None:
        files = choose_documents(self, {".loucodi-document"}, initial_directory=self._project_directory())
        if not files:
            return
        try:
            loaded = CanvasDocument.load(files[0])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Document illisible", str(exc), parent=self)
            return
        self._checkpoint()
        self.document, self.project_path = loaded, files[0]
        self.current_page, self.selected = 0, None
        self.selected_indices.clear()
        self.status.configure(text=f"Projet ouvert : {files[0].name}")
        self._render()

    def _choose_export(self, extension: str, label: str) -> Path | None:
        stem = self.project_path.stem if self.project_path else "nouveau_document"
        name = ask_text(self, label, "Nom du fichier :", stem)
        return collision_free_target(downloads_directory(), Path(name).stem, extension) if name else None

    def _export_pdf(self) -> None:
        target = self._choose_export(".pdf", "Document PDF")
        if target:
            try:
                export_canvas_pdf(self.document, target)
            except (OSError, RuntimeError, ValueError) as exc:
                messagebox.showerror("Export impossible", str(exc), parent=self)
                return
            self.last_export = target
            self.status.configure(text=f"PDF créé : {target.name}")

    def _export_docx(self) -> None:
        target = self._choose_export(".docx", "Document Word")
        if target is None:
            return
        try:
            export_editable_docx(self.document, target)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Export impossible", str(exc), parent=self)
            return
        self.last_export = target
        self.status.configure(text=f"DOCX créé : {target.name}. Les zones de texte restent modifiables dans Word et TextMaker.")

    def _print(self) -> None:
        target = Path(tempfile.gettempdir()) / "lou-codi-document-a-imprimer.pdf"
        try:
            export_canvas_pdf(self.document, target)
            open_path(target)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Impression impossible", str(exc), parent=self)
            return
        messagebox.showinfo("Impression", "Le document a été ouvert. Utilisez la commande Imprimer du lecteur PDF.", parent=self)
