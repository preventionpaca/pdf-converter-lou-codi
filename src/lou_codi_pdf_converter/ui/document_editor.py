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
    flowed_text_for_object,
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
        self._editing_object_id = ""
        self._editing_original_text = ""
        self._format_clipboard: dict[str, object] | None = None
        self._object_clipboard: list[PageObject] = []
        self.properties_visible = tk.BooleanVar(value=True)
        self.ribbon_visible = tk.BooleanVar(value=True)
        self._pending_text_link_id = ""
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
        ttk.Style(self).configure("EditorTool.TButton", padding=(3, 2), font=("Sans", 10))
        header = tk.Frame(self, bg=NAVY, padx=22, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Créer un modèle" if self.template_mode else "Créer un document", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(side="left")
        tk.Label(header, text="Mise en page locale — canevas A4/PDF", bg=NAVY, fg="#CBDFF5", font=("Sans", 10)).pack(side="left", padx=18)
        tk.Button(
            header,
            text="⚙  Propriétés  F4",
            command=self._toggle_properties_panel,
            bg="#285886",
            fg="white",
            activebackground="#3474AD",
            activeforeground="white",
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="right")
        tk.Button(
            header,
            text="▦  Ruban",
            command=self._toggle_ribbon,
            bg="#285886",
            fg="white",
            activebackground="#3474AD",
            activeforeground="white",
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="right", padx=(0, 8))

        self.ribbon = ttk.Notebook(self)
        self.ribbon.pack(fill="x", padx=8, pady=(4, 2))
        formatting = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        insertion = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        layout = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        self.ribbon.add(formatting, text="Accueil")
        self.ribbon.add(insertion, text="Insertion")
        self.ribbon.add(layout, text="Mise en page")
        self._buttons(formatting, (
            ("↶", self._undo, "Annuler"), ("↷", self._redo, "Rétablir"),
            ("Cop", self._copy_objects, "Copier les objets sélectionnés"),
            ("Col", self._paste_objects, "Coller une copie indépendante sur cette page"),
            ("Fmt+", self._copy_format, "Copier la mise en forme"),
            ("Fmt✓", self._apply_format, "Appliquer la mise en forme copiée"),
            ("B", lambda: self._toggle("bold"), "Gras"),
            ("I", lambda: self._toggle("italic"), "Italique"),
            ("←", lambda: self._align("left"), "Aligner à gauche"),
            ("↔", lambda: self._align("center"), "Centrer"),
            ("→", lambda: self._align("right"), "Aligner à droite"),
            ("J", lambda: self._align("justify"), "Justifier"),
        ), color="#DCEBFA")
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
        color_button = tk.Button(
            formatting,
            text="A▾",
            width=3,
            command=self._choose_color,
            bg="#DCEBFA",
            activebackground="#B8D7F4",
            relief="flat",
        )
        color_button.pack(side="left", padx=2)
        self._add_tooltip(color_button, "Couleur du texte")
        self._buttons(insertion, (
            ("T+", self._add_text, "Insérer une zone de texte"),
            ("Img", self._add_image, "Insérer une image"),
            ("Tab", self._add_table, "Insérer un tableau"),
            ("Mas", self._add_mask, "Insérer un masque blanc"),
            ("Trait", self._add_line, "Insérer un trait"),
            ("Ω", self._insert_symbol, "Insérer un caractère spécial"),
            ("•", lambda: self._make_list(False), "Liste à puces"),
            ("1.", lambda: self._make_list(True), "Liste numérotée"),
            ("Barres", lambda: self._add_chart("bar"), "Graphique en barres lié au tableau"),
            ("Cam.", lambda: self._add_chart("pie"), "Camembert lié au tableau"),
        ), color="#DDF3E7")
        self._buttons(layout, (
            ("Portrait", lambda: self._set_orientation("portrait"), "Page en orientation portrait"),
            ("Paysage", lambda: self._set_orientation("landscape"), "Page en orientation paysage"),
            ("En-tête", lambda: self._add_preset("header"), "Ajouter un en-tête répété"),
            ("Pied", lambda: self._add_preset("footer"), "Ajouter un pied de page répété"),
            ("Marge", lambda: self._add_preset("left_margin"), "Ajouter une marge de notes"),
            ("Lier texte", self._link_text_frames, "Faire continuer le texte dans le cadre suivant"),
            ("Délier", self._unlink_text_frame, "Supprimer le chaînage du cadre"),
            ("N° page", lambda: self._insert_field("Page {{PAGE}} / {{PAGES}}"), "Numérotation automatique"),
            ("Date", lambda: self._insert_field("{{DATE}}"), "Insérer la date du jour"),
            ("Grouper", self._group_selected, "Regrouper les objets sélectionnés"),
            ("Dissocier", self._ungroup_selected, "Dissocier les objets"),
        ), color="#F9E8C8")

        self.body = ttk.Panedwindow(self, orient="horizontal")
        self.body.pack(fill="both", expand=True, padx=12, pady=(2, 0))
        canvas_frame = ttk.Frame(self.body, style="App.TFrame")
        self.body.add(canvas_frame, weight=5)
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
        self.canvas.bind("<Button-3>", self._show_context_menu)

        panel = ttk.Frame(self.body, style="Card.TFrame", padding=14)
        self.properties_panel = panel
        self.body.add(panel, weight=1)
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
        scope_actions = tk.Frame(panel, bg="white")
        scope_actions.pack(fill="x", pady=(2, 6))
        self._scope_button(scope_actions, "▣ Page", "Cette page", "#DCEBFA")
        self._scope_button(scope_actions, "▦ Toutes", "Toutes les pages", "#DDF3E7")
        self._scope_button(scope_actions, "☗ Choisir", "Pages choisies", "#F9E8C8")
        ttk.Label(panel, text="Pages (ex. 1,3-5)", style="Body.TLabel").pack(anchor="w")
        self.pages_var = tk.StringVar()
        pages_entry = ttk.Entry(panel, textvariable=self.pages_var)
        pages_entry.pack(fill="x", pady=(0, 5))
        pages_entry.bind("<Return>", lambda _event: self._apply_scope())
        ttk.Button(panel, text="Appliquer aux pages", command=self._apply_scope).pack(fill="x", pady=4)
        ttk.Label(panel, text="Glissez un objet pour le déplacer. Double-cliquez pour modifier son contenu.", style="Body.TLabel", wraplength=230, justify="left").pack(anchor="w", pady=14)

        self._build_context_menu()

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

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(
            label="Volet des propriétés",
            variable=self.properties_visible,
            command=self._toggle_properties_panel,
            accelerator="F4",
        )
        view_menu.add_checkbutton(
            label="Ruban d’outils",
            variable=self.ribbon_visible,
            command=self._toggle_ribbon,
        )
        view_menu.add_separator()
        view_menu.add_command(label="Zoom avant", command=lambda: self._set_zoom(0.1), accelerator="Ctrl++")
        view_menu.add_command(label="Zoom arrière", command=lambda: self._set_zoom(-0.1), accelerator="Ctrl+-")
        menu.add_cascade(label="Affichage", menu=view_menu)
        self.configure(menu=menu)
        self.bind("<Control-n>", lambda _event: self._new())
        self.bind("<Control-o>", lambda _event: self._load())
        self.bind("<Control-s>", lambda _event: self._save())
        self.bind("<Control-z>", lambda _event: self._undo())
        self.bind("<Control-y>", lambda _event: self._redo())
        self.bind("<Control-c>", self._copy_shortcut)
        self.bind("<Control-v>", self._paste_shortcut)
        self.bind("<Control-p>", lambda _event: self._print())
        self.bind("<Delete>", lambda _event: self._delete_selected())
        self.bind("<F4>", lambda _event: self._toggle_properties_panel())
        self.bind("<Escape>", lambda _event: self._cancel_text_link())

    def _buttons(
        self,
        parent: tk.Misc,
        items: tuple[tuple[str, object] | tuple[str, object, str], ...],
        *,
        color: str | None = None,
    ) -> None:
        for item in items:
            label, command = item[:2]
            tooltip = item[2] if len(item) == 3 else ""
            options = {"width": max(2, len(label))} if len(label) <= 4 else {}
            if color:
                button = tk.Button(
                    parent,
                    text=label,
                    command=command,
                    bg=color,
                    activebackground=self._darker(color),
                    relief="flat",
                    padx=7,
                    pady=3,
                    **options,
                )
            else:
                button = ttk.Button(
                    parent,
                    text=label,
                    command=command,
                    style="EditorTool.TButton",
                    **options,
                )
            button.pack(side="left", padx=1)
            if tooltip:
                self._add_tooltip(button, tooltip)

    @staticmethod
    def _darker(color: str) -> str:
        red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
        return f"#{max(0, red - 24):02X}{max(0, green - 24):02X}{max(0, blue - 24):02X}"

    def _scope_button(self, parent: tk.Misc, label: str, scope: str, color: str) -> None:
        tk.Button(
            parent,
            text=label,
            command=lambda: self._set_scope(scope),
            bg=color,
            activebackground=self._darker(color),
            relief="flat",
            padx=5,
            pady=3,
        ).pack(side="left", fill="x", expand=True, padx=1)

    def _set_scope(self, scope: str) -> None:
        self.scope_var.set(scope)
        if scope != "Pages choisies":
            self._apply_scope()
        else:
            self.status.configure(text="Indiquez les pages souhaitées, par exemple 1,3-5, puis validez.")

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        popup: list[tk.Toplevel | None] = [None]
        timer: list[str | None] = [None]

        def show() -> None:
            timer[0] = None
            if popup[0] is not None:
                return
            tip = tk.Toplevel(self)
            tip.wm_overrideredirect(True)
            tip.configure(bg="#152E4D")
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 5
            tip.geometry(f"+{x}+{y}")
            tk.Label(
                tip,
                text=text,
                bg="#152E4D",
                fg="white",
                padx=8,
                pady=4,
                font=("Sans", 9),
            ).pack()
            popup[0] = tip

        def enter(_event: object) -> None:
            timer[0] = self.after(450, show)

        def hide(_event: object) -> None:
            if timer[0] is not None:
                self.after_cancel(timer[0])
                timer[0] = None
            if popup[0] is not None:
                popup[0].destroy()
                popup[0] = None

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", hide, add="+")
        widget.bind("<ButtonPress>", hide, add="+")

    def _toggle_properties_panel(self) -> None:
        visible = self.properties_visible.get()
        panes = tuple(map(str, self.body.panes()))
        panel_name = str(self.properties_panel)
        currently_visible = panel_name in panes
        if visible == currently_visible:
            visible = not currently_visible
            self.properties_visible.set(visible)
        if visible and not currently_visible:
            self.body.add(self.properties_panel, weight=1)
        elif not visible and currently_visible:
            self.body.forget(self.properties_panel)

    def _toggle_ribbon(self) -> None:
        visible = self.ribbon_visible.get()
        managed = self.ribbon.winfo_manager() == "pack"
        if visible == managed:
            visible = not managed
            self.ribbon_visible.set(visible)
        if visible and not managed:
            self.ribbon.pack(fill="x", padx=8, pady=(4, 2), before=self.body)
        elif not visible and managed:
            self.ribbon.pack_forget()

    def _build_context_menu(self) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Modifier le contenu", command=self._edit_selected)
        menu.add_command(label="Copier", command=self._copy_objects)
        menu.add_command(label="Coller une copie indépendante", command=self._paste_objects)
        menu.add_command(label="Dupliquer ici", command=self._duplicate_objects)
        menu.add_separator()
        menu.add_command(label="Appliquer à cette page", command=lambda: self._set_scope("Cette page"))
        menu.add_command(label="Appliquer à toutes les pages", command=lambda: self._set_scope("Toutes les pages"))
        menu.add_command(label="Choisir les pages…", command=lambda: self._set_scope("Pages choisies"))
        menu.add_separator()
        menu.add_command(label="Chaîner vers une autre zone de texte…", command=self._link_text_frames)
        menu.add_command(label="Délier la zone de texte", command=self._unlink_text_frame)
        menu.add_separator()
        menu.add_command(label="Afficher / masquer les propriétés", command=self._toggle_properties_panel)
        menu.add_command(label="Supprimer", command=self._delete_selected)
        self.context_menu = menu

    def _show_context_menu(self, event: tk.Event[tk.Misc]) -> None:
        clicked = self._object_at_event(event)
        if self._pending_text_link_id and clicked is not None:
            target = self.document.objects[clicked]
            source = next(
                (item for item in self.document.objects if item.object_id == self._pending_text_link_id),
                None,
            )
            if source is not None and target.kind == "text" and target.object_id != source.object_id:
                self._pending_text_link_id = ""
                self.canvas.configure(cursor="")
                self._connect_text_frames(source, target)
                return
            self.status.configure(text="Cliquez sur une autre zone de texte pour terminer le chaînage.")
            return
        if clicked is not None and clicked not in self.selected_indices:
            self.selected = clicked
            self.selected_indices = {clicked}
            self._render()
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

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
        if self._editing_widget is not None:
            self._commit_inline_editor(render=False)
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
        if self._pending_text_link_id:
            self.canvas.create_rectangle(
                self.page_x,
                0,
                self.page_x + dw,
                28,
                fill="#1E7D55",
                outline="",
                tags=("link-help",),
            )
            self.canvas.create_text(
                self.page_x + dw / 2,
                14,
                text="CHAÎNAGE : cliquez sur le cadre vert qui doit recevoir la suite  •  Échap pour annuler",
                fill="white",
                font=("Sans", 10, "bold"),
                tags=("link-help",),
            )
        self.canvas.configure(scrollregion=(0, 0, max(viewport, self.page_x + dw + 40), self.page_y + dh + 35))
        self.page_label.configure(text=f"Page {self.current_page + 1} / {self.document.page_count}")
        self.zoom_label.configure(text=f"{round(self.zoom * 100)} %")
        self._show_properties()

    def _draw_object(self, index: int, item: PageObject) -> None:
        x, y = self.page_x + item.x * self.zoom, self.page_y + item.y * self.zoom
        w, h = item.width * self.zoom, item.height * self.zoom
        tag, selected = f"object:{index}", index in self.selected_indices
        if self._pending_text_link_id and item.kind == "text":
            outline = "#E47D16" if item.object_id == self._pending_text_link_id else "#1E9B66"
        else:
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
            flowed_text = flowed_text_for_object(item, self.document.objects)
            displayed_text = resolve_dynamic_text(flowed_text, self.current_page, self.document.page_count, source_name)
            emphasized = selected or bool(self._pending_text_link_id and item.kind == "text")
            self.canvas.create_rectangle(x, y, x + w, y + h, fill="#FFFFFF", stipple="gray12", outline=outline, width=4 if emphasized else 1, tags=tags)
            family = {"Serif": "Liberation Serif", "Monospace": "Liberation Mono", "Cursive": "URW Chancery L", "Symboles": "Noto Sans Symbols 2"}.get(item.font_family, "Liberation Sans")
            self.canvas.create_text(tx, y + 3, text=displayed_text, fill=item.color, anchor=anchor, justify=item.align if item.align != "justify" else "left", width=max(5, w - 8), font=(family, max(7, round(item.font_size * self.zoom)), style), tags=tags)
            linked = item.flow_next_id or any(
                candidate.flow_next_id == item.object_id for candidate in self.document.objects
            )
            if linked:
                self.canvas.create_text(
                    x + w - 5,
                    y + h - 5,
                    text="↳",
                    fill="#1769AA",
                    anchor="se",
                    font=("Sans", 14, "bold"),
                    tags=tags,
                )
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
        self._commit_inline_editor(render=False)
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
        predecessor = next(
            (
                (index, candidate)
                for index, candidate in enumerate(self.document.objects)
                if candidate.kind == "text" and candidate.flow_next_id == item.object_id
            ),
            None,
        )
        if predecessor is not None:
            index, root = predecessor
            visited = {item.object_id}
            while root.object_id not in visited:
                visited.add(root.object_id)
                earlier = next(
                    (
                        (candidate_index, candidate)
                        for candidate_index, candidate in enumerate(self.document.objects)
                        if candidate.kind == "text" and candidate.flow_next_id == root.object_id
                    ),
                    None,
                )
                if earlier is None:
                    break
                index, root = earlier
            self.current_page = root.page
            self.selected = index
            self.selected_indices = {index}
            self._render()
            self.status.configure(text="Modification du texte depuis le premier cadre de la chaîne.")
            self.after_idle(lambda: self._start_inline_text_editor(root))
            return
        self._start_inline_text_editor(item)

    def _start_inline_text_editor(self, item: PageObject) -> None:
        if self._editing_widget is not None:
            self._commit_inline_editor(render=False)
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
        self._editing_object_id = item.object_id
        self._editing_original_text = item.text
        self.canvas.create_window(
            x,
            y,
            window=widget,
            anchor="nw",
            width=max(60, item.width * self.zoom),
            height=max(35, item.height * self.zoom),
            tags=("inline-editor",),
        )

        def preview_flow(_event: object = None) -> None:
            if not widget.edit_modified():
                return
            item.text = widget.get("1.0", "end-1c")
            widget.edit_modified(False)
            linked_ids: set[str] = set()
            cursor = item
            visited: set[str] = set()
            by_id = {candidate.object_id: candidate for candidate in self.document.objects}
            while cursor.flow_next_id and cursor.object_id not in visited:
                visited.add(cursor.object_id)
                linked_ids.add(cursor.flow_next_id)
                cursor = by_id.get(cursor.flow_next_id, cursor)
            for index, candidate in enumerate(self.document.objects):
                if candidate.object_id in linked_ids and self.current_page in pages_for_object(
                    candidate, self.document.page_count
                ):
                    self.canvas.delete(f"object:{index}")
                    self.canvas.delete(f"resize:{index}")
                    self._draw_object(index, candidate)

        widget.bind("<Control-Return>", lambda _event: self._commit_inline_editor())
        widget.bind("<FocusOut>", lambda _event: self._commit_inline_editor())
        widget.bind("<<Modified>>", preview_flow)
        widget.edit_modified(False)
        widget.focus_set()
        widget.tag_configure("align", justify=item.align if item.align != "justify" else "left")
        widget.tag_add("align", "1.0", "end")

    def _commit_inline_editor(self, *, render: bool = True) -> None:
        widget = self._editing_widget
        if widget is None:
            return
        value = widget.get("1.0", "end-1c")
        item = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.object_id == self._editing_object_id
            ),
            None,
        )
        original_text = self._editing_original_text
        self._editing_widget = None
        self._editing_object_id = ""
        self._editing_original_text = ""
        if item is not None:
            item.text = value
            if value != original_text:
                snapshot = copy.deepcopy(self.document)
                snapshot_item = next(
                    candidate for candidate in snapshot.objects if candidate.object_id == item.object_id
                )
                snapshot_item.text = original_text
                self.undo_stack.append(snapshot)
                self.undo_stack = self.undo_stack[-80:]
                self.redo_stack.clear()
        widget.destroy()
        if render:
            self._render()

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

    def _copy_objects(self) -> None:
        indices = sorted(self.selected_indices)
        if not indices and self.selected is not None:
            indices = [self.selected]
        if not indices:
            self.status.configure(text="Sélectionnez un ou plusieurs objets à copier.")
            return
        self._object_clipboard = [copy.deepcopy(self.document.objects[index]) for index in indices]
        self.status.configure(
            text=f"{len(self._object_clipboard)} objet(s) copié(s). Changez de page puis utilisez Coller."
        )

    def _copy_shortcut(self, _event: object = None) -> str | None:
        if isinstance(self.focus_get(), (tk.Text, tk.Entry, ttk.Entry)):
            return None
        self._copy_objects()
        return "break"

    def _paste_shortcut(self, _event: object = None) -> str | None:
        if isinstance(self.focus_get(), (tk.Text, tk.Entry, ttk.Entry)):
            return None
        self._paste_objects()
        return "break"

    def _paste_objects(self) -> None:
        if not self._object_clipboard:
            self.status.configure(text="Aucun objet n’a encore été copié.")
            return
        self._checkpoint()
        id_map = {item.object_id: uuid.uuid4().hex for item in self._object_clipboard}
        group_map: dict[str, str] = {}
        pasted: list[int] = []
        for original in self._object_clipboard:
            item = copy.deepcopy(original)
            item.object_id = id_map[original.object_id]
            item.page = self.current_page
            item.pages = ""
            item.x += 12
            item.y += 12
            if item.group:
                group_map.setdefault(item.group, uuid.uuid4().hex)
                item.group = group_map[item.group]
            item.source_id = id_map.get(item.source_id, "")
            item.flow_next_id = id_map.get(item.flow_next_id, "")
            self.document.objects.append(item)
            pasted.append(len(self.document.objects) - 1)
        self.selected_indices = set(pasted)
        self.selected = pasted[-1]
        self.status.configure(
            text=f"{len(pasted)} copie(s) indépendante(s) collée(s) sur la page {self.current_page + 1}."
        )
        self._render()

    def _duplicate_objects(self) -> None:
        self._copy_objects()
        self._paste_objects()

    def _link_text_frames(self) -> None:
        indices = sorted(
            index
            for index in self.selected_indices
            if self.document.objects[index].kind == "text"
        )
        if len(indices) == 1:
            source = self.document.objects[indices[0]]
            self._pending_text_link_id = source.object_id
            self.canvas.configure(cursor="crosshair")
            self.status.configure(
                text="Chaînage actif : cliquez maintenant sur la zone de texte qui doit recevoir la suite."
            )
            self._render()
            return
        if len(indices) != 2:
            messagebox.showinfo(
                "Chaînage du texte",
                "Sélectionnez une zone de texte, cliquez sur Chaîner, puis cliquez sur la zone suivante.",
                parent=self,
            )
            return
        first, second = (self.document.objects[index] for index in indices)
        if (second.page, second.y, second.x) < (first.page, first.y, first.x):
            first, second = second, first
        self._connect_text_frames(first, second)

    def _cancel_text_link(self) -> None:
        if not self._pending_text_link_id:
            return
        self._pending_text_link_id = ""
        self.canvas.configure(cursor="")
        self.status.configure(text="Chaînage annulé.")
        self._render()

    def _connect_text_frames(self, first: PageObject, second: PageObject) -> None:
        by_id = {item.object_id: item for item in self.document.objects}
        cursor = second
        visited: set[str] = set()
        while cursor.flow_next_id and cursor.object_id not in visited:
            visited.add(cursor.object_id)
            if cursor.flow_next_id == first.object_id:
                messagebox.showwarning(
                    "Chaînage du texte",
                    "Ce lien créerait une boucle entre les zones de texte.",
                    parent=self,
                )
                return
            cursor = by_id.get(cursor.flow_next_id, cursor)
        self._checkpoint()
        first.flow_next_id = second.object_id
        if second.text and second.text.strip():
            first.text = f"{first.text}\n{second.text}".strip()
            second.text = ""
        self.status.configure(text="Zones liées : le texte trop long continue dans le second cadre.")
        self._render()

    def _unlink_text_frame(self) -> None:
        if self.selected is None or self.document.objects[self.selected].kind != "text":
            return
        item = self.document.objects[self.selected]
        predecessor = next(
            (
                candidate
                for candidate in self.document.objects
                if candidate.kind == "text" and candidate.flow_next_id == item.object_id
            ),
            None,
        )
        if not item.flow_next_id and predecessor is None:
            return
        self._checkpoint()
        if predecessor is not None:
            predecessor.flow_next_id = ""
        item.flow_next_id = ""
        self.status.configure(text="Zone de texte déliée.")
        self._render()

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
        self._commit_inline_editor(render=False)
        page = self.current_page + change
        if 0 <= page < self.document.page_count:
            self.current_page, self.selected = page, None
            self.selected_indices.clear()
            self._render()

    def _add_blank_page(self) -> None:
        self._commit_inline_editor(render=False)
        self._checkpoint()
        self.document.page_count += 1
        self.current_page, self.selected = self.document.page_count - 1, None
        self.selected_indices.clear()
        self._render()

    def _set_zoom(self, change: float) -> None:
        self._commit_inline_editor(render=False)
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
        self._commit_inline_editor(render=False)
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
        self._commit_inline_editor(render=False)
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
        self._commit_inline_editor(render=False)
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
        self._commit_inline_editor(render=False)
        target = Path(tempfile.gettempdir()) / "lou-codi-document-a-imprimer.pdf"
        try:
            export_canvas_pdf(self.document, target)
            open_path(target)
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror("Impression impossible", str(exc), parent=self)
            return
        messagebox.showinfo("Impression", "Le document a été ouvert. Utilisez la commande Imprimer du lecteur PDF.", parent=self)
