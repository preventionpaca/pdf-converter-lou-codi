from __future__ import annotations

import copy
import tempfile
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import colorchooser, messagebox, simpledialog, ttk

import pymupdf
from PIL import Image, ImageDraw, ImageFont, ImageTk

from ..i18n import settings_path, translate_widget_tree
from ..paths import collision_free_target, downloads_directory
from ..services.canvas_document import (
    A4_HEIGHT,
    A4_WIDTH,
    FLOW_BREAK_TOKEN,
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
        self._editing_dialog: tk.Toplevel | None = None
        self._editing_object_id = ""
        self._editing_original_text = ""
        self._format_clipboard: dict[str, object] | None = None
        self._object_clipboard: list[PageObject] = []
        self.properties_visible = tk.BooleanVar(value=False)
        self.ribbon_visible = tk.BooleanVar(value=True)
        self._pending_text_link_id = ""
        self._last_clicked_index: int | None = None
        self._polyline_points: list[tuple[float, float]] = []
        self._drawing_polyline = False
        icon = getattr(self._root(), "app_icon", None)
        if icon is not None:
            self.iconphoto(False, icon)
        self._build()
        self._toggle_properties_panel()
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
        diagrams = ttk.Frame(self.ribbon, style="App.TFrame", padding=(12, 7))
        self.ribbon.add(formatting, text="Accueil")
        self.ribbon.add(insertion, text="Insertion")
        self.ribbon.add(layout, text="Mise en page")
        self.ribbon.add(diagrams, text="Schémas")
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
            ("A−", lambda: self._change_font(-1), "Réduire la taille du texte"),
            ("A+", lambda: self._change_font(1), "Agrandir la taille du texte"),
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
        self._color_menu_button(formatting, "A▾", "color", "Couleur du texte")
        self._color_menu_button(formatting, "Fond▾", "fill", "Couleur de fond de la zone")
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
        tk.Label(
            layout,
            text="Chaînage : 1  sélectionnez la première zone   →   2  cliquez sur Lier texte   →   3  cliquez sur la zone verte",
            bg="#FFF5DE",
            fg="#744500",
            font=("Sans", 9, "bold"),
            padx=10,
            pady=5,
        ).pack(side="right", padx=(12, 0))
        self._buttons(diagrams, (
            ("▭ Rectangle", lambda: self._add_shape("rectangle"), "Insérer un rectangle"),
            ("◯ Ellipse", lambda: self._add_shape("ellipse"), "Insérer une ellipse"),
            ("△ Triangle", lambda: self._add_shape("triangle"), "Insérer un triangle"),
            ("Trapèze", lambda: self._add_shape("trapezoid"), "Insérer un trapèze"),
            ("➜ Flèche", lambda: self._add_shape("arrow"), "Insérer une flèche"),
            ("／ Trait", self._add_line, "Tracer un trait"),
            ("⌁ Polyligne", self._start_polyline, "Tracer un profil point par point"),
            ("┄ Axe", self._add_axis, "Insérer un trait d’axe"),
            ("↻ 90°", self._rotate_selected, "Faire pivoter de 90 degrés"),
            ("⇆ Miroir H", lambda: self._mirror_selected("horizontal"), "Symétrie horizontale"),
            ("⇅ Miroir V", lambda: self._mirror_selected("vertical"), "Symétrie verticale"),
            ("Miroir + copie", self._mirror_copy_about_axis, "Créer la partie opposée autour du trait d’axe sélectionné"),
            ("Aligner G", lambda: self._align_objects("left"), "Aligner les objets à gauche"),
            ("Aligner H", lambda: self._align_objects("middle"), "Aligner verticalement"),
        ), color="#E8E0F5")
        ttk.Label(diagrams, text="Trait", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.border_style_var = tk.StringVar(value="Continu")
        border_style = ttk.Combobox(
            diagrams,
            textvariable=self.border_style_var,
            values=("Continu", "Pointillé", "Tirets"),
            state="readonly",
            width=9,
        )
        border_style.pack(side="left", padx=2)
        border_style.bind("<<ComboboxSelected>>", lambda _event: self._apply_border_style())
        self.border_width_var = tk.StringVar(value="1.5")
        border_width = ttk.Combobox(
            diagrams,
            textvariable=self.border_width_var,
            values=("0", "0.5", "1", "1.5", "2", "3", "4", "6"),
            width=4,
        )
        border_width.pack(side="left", padx=2)
        border_width.bind("<<ComboboxSelected>>", lambda _event: self._apply_border_width())
        border_width.bind("<Return>", lambda _event: self._apply_border_width())
        self._color_menu_button(diagrams, "Bordure▾", "border_color", "Couleur de la bordure")
        ttk.Label(diagrams, text="Pas (mm)", style="Body.TLabel").pack(side="left", padx=(10, 3))
        self.nudge_var = tk.StringVar(value="1")
        ttk.Combobox(
            diagrams,
            textvariable=self.nudge_var,
            values=("10", "1", "0.1", "0.01"),
            state="readonly",
            width=5,
        ).pack(side="left", padx=2)

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
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<Button-3>", self._show_context_menu)

        panel = ttk.Frame(self.body, style="Card.TFrame", padding=14)
        self.properties_panel = panel
        self.body.add(panel, weight=1)
        ttk.Label(panel, text="OBJET SÉLECTIONNÉ", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.kind_label = ttk.Label(panel, text="Aucun objet", style="Body.TLabel")
        self.kind_label.pack(anchor="w", pady=(0, 8))
        self.property_vars: dict[str, tk.StringVar] = {}
        for key, label in (("x", "X (mm)"), ("y", "Y (mm)"), ("width", "Largeur (mm)"), ("height", "Hauteur (mm)"), ("font_size", "Taille du texte (pt)")):
            ttk.Label(panel, text=label, style="Body.TLabel").pack(anchor="w")
            var = tk.StringVar()
            self.property_vars[key] = var
            entry = ttk.Entry(panel, textvariable=var)
            entry.pack(fill="x", pady=(0, 6))
            entry.bind("<Return>", lambda _event: self._apply_properties())
            entry.bind("<Tab>", lambda _event: self._apply_properties(silent=True), add="+")
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
        self.bind("<Escape>", self._cancel_current_action)
        self.bind("<Return>", self._finish_polyline)
        self.bind("<Left>", lambda event: self._nudge_selected(event, -1, 0))
        self.bind("<Right>", lambda event: self._nudge_selected(event, 1, 0))
        self.bind("<Up>", lambda event: self._nudge_selected(event, 0, -1))
        self.bind("<Down>", lambda event: self._nudge_selected(event, 0, 1))

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

    def _color_menu_button(self, parent: tk.Misc, label: str, attribute: str, tooltip: str) -> None:
        button = tk.Menubutton(
            parent,
            text=label,
            bg="#DCEBFA",
            activebackground="#B8D7F4",
            relief="flat",
            padx=7,
            pady=3,
        )
        menu = tk.Menu(button, tearoff=False)
        presets = (
            ("Noir", "#000000"),
            ("Bleu", "#2368AF"),
            ("Rouge", "#C83232"),
            ("Vert", "#258A55"),
            ("Orange", "#E87524"),
            ("Violet", "#7B4DB5"),
            ("Blanc", "#FFFFFF"),
        )
        for name, value in presets:
            menu.add_command(
                label=f"■  {name}   {value}",
                foreground=value,
                command=lambda color=value, key=attribute: self._set_object_color(key, color),
            )
        if attribute == "fill":
            menu.add_command(
                label="▧  Transparent",
                command=lambda: self._set_object_color("fill", "transparent"),
            )
        menu.add_separator()
        menu.add_command(
            label="Saisir un code hexadécimal…",
            command=lambda key=attribute: self._enter_hex_color(key),
        )
        menu.add_command(
            label="Sélecteur de couleur…",
            command=lambda key=attribute: self._choose_color(key),
        )
        button.configure(menu=menu)
        button.pack(side="left", padx=2)
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
        selected_kind = (
            self.document.objects[self.selected].kind
            if self.selected is not None and self.selected < len(self.document.objects)
            else ""
        )
        text_state = "normal" if selected_kind == "text" else "disabled"
        self.context_menu.entryconfigure("Chaîner vers une autre zone de texte…", state=text_state)
        self.context_menu.entryconfigure("Délier la zone de texte", state=text_state)
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
        self.page_x, self.page_y = max(48.0, (viewport - dw) / 2), 48.0
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
        self._draw_rulers(width, height)
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

    def _draw_rulers(self, width: float, height: float) -> None:
        """Draw page rulers in millimetres around the current sheet."""
        points_per_mm = 72 / 25.4
        page_right = self.page_x + width * self.zoom
        page_bottom = self.page_y + height * self.zoom
        self.canvas.create_rectangle(self.page_x, self.page_y - 24, page_right, self.page_y, fill="#EEF2F6", outline="#A8B2BD", tags=("ruler",))
        self.canvas.create_rectangle(self.page_x - 32, self.page_y, self.page_x, page_bottom, fill="#EEF2F6", outline="#A8B2BD", tags=("ruler",))
        for millimetre in range(0, int(width / points_per_mm) + 1, 10):
            px = self.page_x + millimetre * points_per_mm * self.zoom
            major = millimetre % 50 == 0
            self.canvas.create_line(px, self.page_y - (14 if major else 8), px, self.page_y, fill="#52677C", tags=("ruler",))
            if major:
                self.canvas.create_text(px + 2, self.page_y - 16, text=str(millimetre), anchor="sw", font=("Sans", 7), fill="#385571", tags=("ruler",))
        for millimetre in range(0, int(height / points_per_mm) + 1, 10):
            py = self.page_y + millimetre * points_per_mm * self.zoom
            major = millimetre % 50 == 0
            self.canvas.create_line(self.page_x - (14 if major else 8), py, self.page_x, py, fill="#52677C", tags=("ruler",))
            if major:
                self.canvas.create_text(self.page_x - 16, py + 2, text=str(millimetre), anchor="ne", font=("Sans", 7), fill="#385571", tags=("ruler",))

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
        elif item.kind == "shape":
            dash = (5, 3) if item.border_style == "dashed" else (1, 3) if item.border_style == "dotted" else None
            options = {
                "fill": "" if item.fill.lower() in {"", "none", "transparent"} else item.fill,
                "outline": item.border_color,
                "width": max(1, round(item.border_width * self.zoom)),
                "dash": dash,
                "tags": tags,
            }
            if item.shape == "ellipse":
                self.canvas.create_oval(x, y, x + w, y + h, **options)
            elif item.shape == "triangle":
                self.canvas.create_polygon(x + w / 2, y, x + w, y + h, x, y + h, **options)
            elif item.shape == "trapezoid":
                inset = w * 0.2
                self.canvas.create_polygon(x + inset, y, x + w - inset, y, x + w, y + h, x, y + h, **options)
            elif item.shape == "arrow":
                if item.rotation % 180 == 90:
                    middle, head, thickness = x + w / 2, h * 0.28, w * 0.28
                    points = [
                        (middle - thickness, y), (middle - thickness, y + h - head),
                        (x, y + h - head), (middle, y + h), (x + w, y + h - head),
                        (middle + thickness, y + h - head), (middle + thickness, y),
                    ]
                    if item.flip_vertical:
                        points = [(px, 2 * y + h - py) for px, py in points]
                else:
                    middle, head, thickness = y + h / 2, w * 0.28, h * 0.28
                    points = [
                        (x, middle - thickness), (x + w - head, middle - thickness),
                        (x + w - head, y), (x + w, middle), (x + w - head, y + h),
                        (x + w - head, middle + thickness), (x, middle + thickness),
                    ]
                    if item.flip_horizontal:
                        points = [(2 * x + w - px, py) for px, py in points]
                self.canvas.create_polygon(*(coordinate for point in points for coordinate in point), **options)
            else:
                self.canvas.create_rectangle(x, y, x + w, y + h, **options)
        elif item.kind == "line":
            dash = (8, 3, 2, 3) if item.shape == "axis" else (5, 3) if item.border_style == "dashed" else (1, 3) if item.border_style == "dotted" else None
            self.canvas.create_line(x, y, x + w, y + h, fill=item.border_color, width=max(1, item.border_width * self.zoom), dash=dash, tags=tags)
        elif item.kind == "polyline":
            dash = (5, 3) if item.border_style == "dashed" else (1, 3) if item.border_style == "dotted" else None
            coordinates = [
                coordinate
                for point in item.points
                for coordinate in (self.page_x + (item.x + point[0]) * self.zoom, self.page_y + (item.y + point[1]) * self.zoom)
            ]
            if len(coordinates) >= 4:
                self.canvas.create_line(*coordinates, fill=item.border_color, width=max(1, item.border_width * self.zoom), dash=dash, tags=tags)
        elif item.kind == "chart":
            self._draw_chart_preview(item, x, y, w, h, tags)
        else:
            source_name = Path(self.document.source_pdf).stem if self.document.source_pdf else (self.project_path.stem if self.project_path else "Nouveau document")
            flowed_text = flowed_text_for_object(item, self.document.objects)
            displayed_text = resolve_dynamic_text(flowed_text, self.current_page, self.document.page_count, source_name)
            emphasized = selected or bool(self._pending_text_link_id and item.kind == "text")
            self.canvas.create_rectangle(
                x,
                y,
                x + w,
                y + h,
                fill="" if item.fill.lower() in {"", "none", "transparent"} else item.fill,
                outline=outline,
                width=4 if emphasized else 1,
                tags=tags,
            )
            picture = self._text_preview(item, displayed_text, max(1, round(w)), max(1, round(h)))
            self._overlay_images.append(picture)
            self.canvas.create_image(x, y, image=picture, anchor="nw", tags=tags)
            self.canvas.create_rectangle(
                x,
                y,
                x + w,
                y + h,
                outline=outline if emphasized else item.border_color,
                width=4 if emphasized else max(1, round(item.border_width * self.zoom)),
                dash=None if emphasized or item.border_style == "solid" else (5, 3) if item.border_style == "dashed" else (1, 3),
                tags=tags,
            )
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

    def _text_preview(self, item: PageObject, text: str, width: int, height: int) -> ImageTk.PhotoImage:
        """Render and clip a text frame exactly inside its visible rectangle."""
        transparent = item.fill.lower() in {"", "none", "transparent"}
        image = Image.new("RGBA", (width, height), (255, 255, 255, 0)) if transparent else Image.new("RGB", (width, height), item.fill)
        draw = ImageDraw.Draw(image)
        size = max(7, round(item.font_size * self.zoom))
        suffix = "-BoldOblique" if item.bold and item.italic else "-Bold" if item.bold else "-Oblique" if item.italic else ""
        family = "DejaVuSansMono" if item.font_family == "Monospace" else "DejaVuSerif" if item.font_family == "Serif" else "DejaVuSans"
        try:
            font = ImageFont.truetype(f"{family}{suffix}.ttf", size)
        except OSError:
            font = ImageFont.load_default()
        maximum = max(1, width - 10)
        lines: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for character in paragraph:
                candidate = current + character
                if current and draw.textlength(candidate, font=font) > maximum:
                    lines.append(current)
                    current = character.lstrip() if character.isspace() else character
                else:
                    current = candidate
            lines.append(current)
        line_height = max(size + 3, round(size * 1.35))
        for row, line in enumerate(lines):
            py = 4 + row * line_height
            if py + line_height > height:
                break
            length = draw.textlength(line, font=font)
            px = 5 if item.align in {"left", "justify"} else (width - length) / 2 if item.align == "center" else width - length - 5
            draw.text((px, py), line, font=font, fill=item.color)
        return ImageTk.PhotoImage(image)

    def _add_object(self, item: PageObject) -> None:
        self._checkpoint()
        self.document.objects.append(item)
        self.selected = len(self.document.objects) - 1
        self.selected_indices = {self.selected}
        self._render()

    def _add_text(self) -> None:
        width, height = self._page_size()
        occupied = [
            item
            for item in self.document.objects
            if item.kind == "text" and self.current_page in pages_for_object(item, self.document.page_count)
        ]
        x, y = 70.0, 80.0
        for step in range(1, 25):
            if not any(abs(item.x - x) < 12 and abs(item.y - y) < 12 for item in occupied):
                break
            offset = step * 22
            x = min(max(20.0, width - 300.0), 70.0 + offset)
            y = min(max(20.0, height - 100.0), 80.0 + offset)
        self._add_object(PageObject("text", self.current_page, x, y, 280, 80))
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
        self._add_object(PageObject("line", self.current_page, 70, 120, 260, 0, border_color="#193B66", border_width=1.5))

    def _add_axis(self) -> None:
        self._add_object(
            PageObject(
                "line",
                self.current_page,
                70,
                220,
                360,
                0,
                shape="axis",
                border_color="#6A7480",
                border_width=1,
                border_style="dashed",
            )
        )

    def _start_polyline(self) -> None:
        self._drawing_polyline = True
        self._polyline_points.clear()
        self.canvas.configure(cursor="crosshair")
        self.status.configure(text="Polyligne : cliquez chaque sommet sur la feuille, puis Entrée pour terminer. Échap annule.")

    def _finish_polyline(self, _event: object = None) -> str | None:
        if not self._drawing_polyline:
            return None
        if len(self._polyline_points) >= 2:
            minimum_x = min(point[0] for point in self._polyline_points)
            minimum_y = min(point[1] for point in self._polyline_points)
            maximum_x = max(point[0] for point in self._polyline_points)
            maximum_y = max(point[1] for point in self._polyline_points)
            relative = [[x - minimum_x, y - minimum_y] for x, y in self._polyline_points]
            self._add_object(
                PageObject(
                    "polyline",
                    self.current_page,
                    minimum_x,
                    minimum_y,
                    max(1, maximum_x - minimum_x),
                    max(1, maximum_y - minimum_y),
                    points=relative,
                    border_color="#193B66",
                    border_width=1.5,
                )
            )
            self.status.configure(text=f"Polyligne créée avec {len(relative)} sommets.")
        self._drawing_polyline = False
        self._polyline_points.clear()
        self.canvas.configure(cursor="")
        self.canvas.delete("polyline-preview")
        return "break"

    def _cancel_current_action(self, _event: object = None) -> str:
        if self._drawing_polyline:
            self._drawing_polyline = False
            self._polyline_points.clear()
            self.canvas.delete("polyline-preview")
            self.canvas.configure(cursor="")
            self.status.configure(text="Tracé de la polyligne annulé.")
        else:
            self._cancel_text_link()
        return "break"

    def _add_shape(self, shape: str) -> None:
        width, height = (180, 75) if shape == "arrow" else (150, 100)
        self._add_object(
            PageObject(
                "shape",
                self.current_page,
                80,
                100,
                width,
                height,
                shape=shape,
                color="#193B66",
                border_color="#193B66",
                border_width=1.5,
                fill="#FFFFFF",
            )
        )

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
        self.canvas.focus_set()
        if self._drawing_polyline:
            page_x = (self.canvas.canvasx(event.x) - self.page_x) / self.zoom
            page_y = (self.canvas.canvasy(event.y) - self.page_y) / self.zoom
            width, height = self._page_size()
            if 0 <= page_x <= width and 0 <= page_y <= height:
                self._polyline_points.append((page_x, page_y))
                self.canvas.delete("polyline-preview")
                coordinates = [
                    coordinate
                    for point_x, point_y in self._polyline_points
                    for coordinate in (self.page_x + point_x * self.zoom, self.page_y + point_y * self.zoom)
                ]
                if len(coordinates) >= 4:
                    self.canvas.create_line(*coordinates, fill="#193B66", width=2, tags=("polyline-preview",))
                for point_x, point_y in self._polyline_points:
                    px, py = self.page_x + point_x * self.zoom, self.page_y + point_y * self.zoom
                    self.canvas.create_oval(px - 3, py - 3, px + 3, py + 3, fill="#E87524", outline="white", tags=("polyline-preview",))
                self.status.configure(text=f"Polyligne : {len(self._polyline_points)} sommet(s). Entrée termine, Échap annule.")
            return
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
        if clicked is not None:
            self._last_clicked_index = clicked
        if self._pending_text_link_id:
            source = next(
                (item for item in self.document.objects if item.object_id == self._pending_text_link_id),
                None,
            )
            target = self.document.objects[clicked] if clicked is not None else None
            if source is not None and target is not None and target.kind == "text" and target.object_id != source.object_id:
                self._pending_text_link_id = ""
                self.canvas.configure(cursor="")
                self._connect_text_frames(source, target)
            else:
                self.status.configure(
                    text="Chaînage en attente : cliquez dans une autre zone de texte verte, ou Échap pour annuler."
                )
            return
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

    def _double_click(self, _event: tk.Event[tk.Misc]) -> str:
        if self._last_clicked_index is not None and self._last_clicked_index < len(self.document.objects):
            self.selected = self._last_clicked_index
            self.selected_indices = {self.selected}
            self.after_idle(self._edit_selected)
        return "break"

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        if self.selected is not None and self._resize_origin is not None:
            sx, sy, old_width, old_height = self._resize_origin
            item = self.document.objects[self.selected]
            new_width = max(20, old_width + (self.canvas.canvasx(event.x) - sx) / self.zoom)
            new_height = max(20, old_height + (self.canvas.canvasy(event.y) - sy) / self.zoom)
            if item.kind == "polyline" and item.width and item.height:
                item.points = [
                    [point[0] * new_width / item.width, point[1] * new_height / item.height]
                    for point in item.points
                ]
            item.width, item.height = new_width, new_height
            self._render()
            width_mm, height_mm = item.width * 25.4 / 72, item.height * 25.4 / 72
            self.canvas.create_text(
                self.page_x + (item.x + item.width) * self.zoom + 8,
                self.page_y + (item.y + item.height) * self.zoom + 8,
                text=f"{width_mm:.1f} × {height_mm:.1f} mm",
                anchor="nw",
                fill="white",
                font=("Sans", 9, "bold"),
                tags=("dimension-guide",),
            )
            self.canvas.create_rectangle(
                self.canvas.bbox("dimension-guide"),
                fill="#193B66",
                outline="",
                tags=("dimension-guide-bg",),
            )
            self.canvas.tag_raise("dimension-guide")
            self.status.configure(text=f"Dimensions : {width_mm:.1f} × {height_mm:.1f} mm")
            return
        if self.selected is None or self._drag_origin is None:
            return
        sx, sy, _object_x, _object_y = self._drag_origin
        pw, ph = self._page_size()
        dx = (self.canvas.canvasx(event.x) - sx) / self.zoom
        dy = (self.canvas.canvasy(event.y) - sy) / self.zoom
        for index, (start_x, start_y) in self._drag_positions.items():
            item = self.document.objects[index]
            new_x = max(0, min(pw - item.width, start_x + dx))
            new_y = max(0, min(ph - item.height, start_y + dy))
            move_x = (new_x - item.x) * self.zoom
            move_y = (new_y - item.y) * self.zoom
            item.x, item.y = new_x, new_y
            self.canvas.move(f"object:{index}", move_x, move_y)
            self.canvas.move(f"resize:{index}", move_x, move_y)
        if self.selected is not None:
            self._update_geometry_fields(self.document.objects[self.selected])

    def _release(self, _event: tk.Event[tk.Misc]) -> None:
        changed = False
        if self._resize_origin is not None and self.selected is not None:
            _, _, old_width, old_height = self._resize_origin
            item = self.document.objects[self.selected]
            if (item.width, item.height) != (old_width, old_height):
                changed = True
                snapshot = copy.deepcopy(self.document)
                snapshot.objects[self.selected].width = old_width
                snapshot.objects[self.selected].height = old_height
                self.undo_stack.append(snapshot)
                self.redo_stack.clear()
        self._resize_origin = None
        moved = self._drag_origin is not None and self._drag_before is not None and any(
            (self.document.objects[index].x, self.document.objects[index].y) != position
            for index, position in self._drag_positions.items()
        )
        if moved:
            changed = True
            self.undo_stack.append(self._drag_before)
            self.redo_stack.clear()
        self._drag_origin = None
        self._drag_before = None
        if changed:
            self._render()

    def _edit_selected(self, _event: object = None) -> None:
        if self.selected is None and self._last_clicked_index is not None:
            if 0 <= self._last_clicked_index < len(self.document.objects):
                self.selected = self._last_clicked_index
                self.selected_indices = {self.selected}
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
            self._redraw_text_chain(item)

        widget.bind("<Control-Return>", lambda _event: self._commit_inline_editor())
        widget.bind("<FocusOut>", lambda _event: self._commit_inline_editor())
        widget.bind("<<Modified>>", preview_flow)
        widget.edit_modified(False)
        widget.focus_set()
        widget.tag_configure("align", justify=item.align if item.align != "justify" else "left")
        widget.tag_add("align", "1.0", "end")

    def _start_linked_text_editor(self, item: PageObject) -> None:
        dialog = tk.Toplevel(self, class_="LouCodiPdfConverter")
        dialog.title("Texte chaîné — Lou Còdi")
        dialog.configure(bg=BACKGROUND)
        dialog.transient(self)
        dialog.geometry(
            f"720x300+{max(20, self.winfo_screenwidth() - 750)}+{max(80, self.winfo_rooty() + 120)}"
        )
        tk.Label(
            dialog,
            text="Modifier le texte chaîné",
            bg=NAVY,
            fg="white",
            font=("Sans", 16, "bold"),
            padx=18,
            pady=10,
        ).pack(fill="x")
        tk.Label(
            dialog,
            text="Écrivez ou collez ici : la page montre immédiatement la répartition entre les cadres liés.",
            bg=BACKGROUND,
            fg="#385571",
            font=("Sans", 10),
            padx=16,
            pady=7,
        ).pack(fill="x")
        widget = tk.Text(
            dialog,
            wrap="word",
            font=("Liberation Sans", 12),
            bg="white",
            fg=item.color,
            relief="solid",
            borderwidth=1,
            undo=True,
            padx=8,
            pady=8,
        )
        widget.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        widget.insert("1.0", item.text)
        actions = tk.Frame(dialog, bg=BACKGROUND)
        actions.pack(fill="x", padx=14, pady=(0, 10))
        distribution = tk.Label(actions, bg=BACKGROUND, fg="#385571", font=("Sans", 9))
        distribution.pack(side="left")
        tk.Button(
            actions,
            text="Terminer",
            command=self._commit_inline_editor,
            bg="#2368AF",
            fg="white",
            activebackground="#174D85",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=6,
        ).pack(side="right")
        tk.Button(
            actions,
            text="Passer au cadre suivant →",
            command=lambda: widget.insert("insert", f"\n{FLOW_BREAK_TOKEN}\n"),
            relief="flat",
            padx=12,
            pady=6,
        ).pack(side="right", padx=(8, 0))
        self._editing_widget = widget
        self._editing_dialog = dialog
        self._editing_object_id = item.object_id
        self._editing_original_text = item.text

        def preview(_event: object = None) -> None:
            if not widget.edit_modified():
                return
            item.text = widget.get("1.0", "end-1c")
            widget.edit_modified(False)
            self._redraw_text_chain(item)
            chain: list[PageObject] = []
            cursor = item
            known = {candidate.object_id: candidate for candidate in self.document.objects}
            visited: set[str] = set()
            while cursor.object_id not in visited:
                visited.add(cursor.object_id)
                chain.append(cursor)
                if not cursor.flow_next_id or cursor.flow_next_id not in known:
                    break
                cursor = known[cursor.flow_next_id]
            counts = [len(flowed_text_for_object(frame, self.document.objects)) for frame in chain]
            distribution.configure(
                text="Répartition : "
                + "  •  ".join(
                    f"cadre {number + 1} : {count}" for number, count in enumerate(counts)
                )
            )

        widget.bind("<<Modified>>", preview)
        widget.bind("<Control-Return>", lambda _event: self._commit_inline_editor())
        widget.edit_modified(False)
        widget.edit_modified(True)
        preview()
        dialog.protocol("WM_DELETE_WINDOW", self._commit_inline_editor)
        dialog.lift()
        widget.focus_set()

    def _redraw_text_chain(self, root: PageObject) -> None:
        chain_ids = {root.object_id}
        cursor = root
        visited: set[str] = set()
        by_id = {candidate.object_id: candidate for candidate in self.document.objects}
        while cursor.flow_next_id and cursor.object_id not in visited:
            visited.add(cursor.object_id)
            chain_ids.add(cursor.flow_next_id)
            cursor = by_id.get(cursor.flow_next_id, cursor)
        for index, candidate in enumerate(self.document.objects):
            if candidate.object_id in chain_ids and self.current_page in pages_for_object(
                candidate, self.document.page_count
            ):
                if (
                    candidate.object_id == self._editing_object_id
                    and self._editing_widget is not None
                    and self._editing_dialog is None
                ):
                    continue
                self.canvas.delete(f"object:{index}")
                self.canvas.delete(f"resize:{index}")
                self._draw_object(index, candidate)

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
        dialog = self._editing_dialog
        self._editing_dialog = None
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
        if dialog is not None:
            dialog.destroy()
        elif widget.winfo_exists():
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

    def _set_object_color(self, attribute: str, value: str) -> None:
        if attribute == "fill" and value.lower() == "transparent":
            self._mutate(lambda item: setattr(item, "fill", "transparent"))
            return
        normalized = value if value.startswith("#") else f"#{value}"
        try:
            self.winfo_rgb(normalized)
        except tk.TclError:
            messagebox.showerror(
                "Couleur incorrecte",
                "Utilisez un code hexadécimal, par exemple #2368AF.",
                parent=self,
            )
            return
        self._mutate(lambda item: setattr(item, attribute, normalized.upper()))

    def _enter_hex_color(self, attribute: str) -> None:
        if self.selected is None:
            return
        current = getattr(self.document.objects[self.selected], attribute)
        value = simpledialog.askstring(
            "Code couleur",
            "Code hexadécimal (exemple : #2368AF) :",
            initialvalue=current,
            parent=self,
        )
        if value:
            self._set_object_color(attribute, value.strip())

    def _choose_color(self, attribute: str = "color") -> None:
        if self.selected is not None:
            chosen = colorchooser.askcolor(
                getattr(self.document.objects[self.selected], attribute), parent=self
            )[1]
            if chosen:
                self._set_object_color(attribute, chosen)

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
        first_index = self.document.objects.index(first)
        self.selected = first_index
        self.selected_indices = {first_index}
        self.status.configure(
            text="Liaison validée automatiquement. Écrivez directement dans le premier cadre : la suite apparaît dans les suivants."
        )
        self._render()
        self.after_idle(lambda: self._start_inline_text_editor(first))

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

    def _rotate_selected(self) -> None:
        if not self.selected_indices:
            return
        self._checkpoint()
        for index in self.selected_indices:
            item = self.document.objects[index]
            center_x, center_y = item.x + item.width / 2, item.y + item.height / 2
            old_width, old_height = item.width, item.height
            if item.kind == "polyline":
                item.points = [[old_height - point[1], point[0]] for point in item.points]
            item.width, item.height = item.height, item.width
            item.x, item.y = center_x - item.width / 2, center_y - item.height / 2
            item.rotation = (item.rotation + 90) % 360
        self._render()

    def _mirror_selected(self, direction: str) -> None:
        if not self.selected_indices:
            return
        self._checkpoint()
        objects = [self.document.objects[index] for index in self.selected_indices]
        left = min(item.x for item in objects)
        right = max(item.x + item.width for item in objects)
        top = min(item.y for item in objects)
        bottom = max(item.y + item.height for item in objects)
        for item in objects:
            if direction == "horizontal":
                item.x = left + right - item.x - item.width
                item.flip_horizontal = not item.flip_horizontal
                if item.kind == "polyline":
                    item.points = [[item.width - point[0], point[1]] for point in item.points]
            else:
                item.y = top + bottom - item.y - item.height
                item.flip_vertical = not item.flip_vertical
                if item.kind == "polyline":
                    item.points = [[point[0], item.height - point[1]] for point in item.points]
        self._render()

    def _mirror_copy_about_axis(self) -> None:
        indices = sorted(self.selected_indices)
        axis_indices = [
            index
            for index in indices
            if self.document.objects[index].kind == "line"
            and self.document.objects[index].shape == "axis"
        ]
        profile_indices = [index for index in indices if index not in axis_indices]
        if len(axis_indices) != 1 or not profile_indices:
            messagebox.showinfo(
                "Symétrie de révolution",
                "Avec Ctrl, sélectionnez un trait d’axe et les éléments du profil, puis relancez « Miroir + copie ».",
                parent=self,
            )
            return
        self._checkpoint()
        axis = self.document.objects[axis_indices[0]]
        horizontal = abs(axis.width) >= abs(axis.height)
        coordinate = axis.y + axis.height / 2 if horizontal else axis.x + axis.width / 2
        copies: list[int] = []
        for index in profile_indices:
            clone = copy.deepcopy(self.document.objects[index])
            clone.object_id = uuid.uuid4().hex
            clone.flow_next_id = ""
            clone.source_id = ""
            clone.group = ""
            if horizontal:
                clone.y = 2 * coordinate - clone.y - clone.height
                clone.flip_vertical = not clone.flip_vertical
                if clone.kind == "polyline":
                    clone.points = [[point[0], clone.height - point[1]] for point in clone.points]
            else:
                clone.x = 2 * coordinate - clone.x - clone.width
                clone.flip_horizontal = not clone.flip_horizontal
                if clone.kind == "polyline":
                    clone.points = [[clone.width - point[0], point[1]] for point in clone.points]
            self.document.objects.append(clone)
            copies.append(len(self.document.objects) - 1)
        self.selected_indices = set(copies)
        self.selected = copies[-1]
        self.status.configure(text=f"Symétrie créée : {len(copies)} élément(s) copiés autour du trait d’axe.")
        self._render()

    def _apply_border_style(self) -> None:
        styles = {"Continu": "solid", "Pointillé": "dotted", "Tirets": "dashed"}
        self._mutate(lambda item: setattr(item, "border_style", styles[self.border_style_var.get()]))

    def _apply_border_width(self) -> None:
        try:
            width = max(0.0, min(20.0, float(self.border_width_var.get().replace(",", "."))))
        except ValueError:
            return
        self._mutate(lambda item: setattr(item, "border_width", width))

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
        names = {"text": "Zone de texte", "image": "Image", "mask": "Masque", "table": "Tableau", "line": "Trait", "polyline": "Polyligne", "chart": "Graphique", "shape": "Forme"}
        selection = f" — {len(self.selected_indices)} objets" if len(self.selected_indices) > 1 else ""
        self.kind_label.configure(text=names.get(item.kind, item.kind) + selection)
        self._update_geometry_fields(item)
        self.font_size_var.set(f"{item.font_size:g}")
        self.font_family_var.set(item.font_family)
        self.border_width_var.set(f"{item.border_width:g}")
        self.border_style_var.set({"solid": "Continu", "dotted": "Pointillé", "dashed": "Tirets"}.get(item.border_style, "Continu"))
        self.scope_var.set("Toutes les pages" if item.pages == "all" else "Pages choisies" if item.pages else "Cette page")
        self.pages_var.set("" if item.pages == "all" else item.pages)

    def _apply_scope(self) -> None:
        if self.selected is None:
            return
        scope = self.scope_var.get()
        pages = "all" if scope == "Toutes les pages" else self.pages_var.get().strip() if scope == "Pages choisies" else ""
        self._mutate(lambda item: setattr(item, "pages", pages))

    def _update_geometry_fields(self, item: PageObject) -> None:
        for key, var in self.property_vars.items():
            value = getattr(item, key)
            if key in {"x", "y", "width", "height"}:
                value = value * 25.4 / 72
            digits = 2 if key in {"x", "y", "width", "height"} else 1
            var.set(f"{value:.{digits}f}")

    def _apply_properties(self, *, silent: bool = False) -> None:
        if self.selected is None:
            return
        try:
            values = {key: float(var.get().replace(",", ".")) for key, var in self.property_vars.items()}
        except ValueError:
            if not silent:
                messagebox.showerror("Valeur incorrecte", "Utilisez uniquement des nombres.", parent=self)
            return
        def apply(item: PageObject) -> None:
            old_width, old_height = item.width, item.height
            for key, value in values.items():
                if key in {"x", "y", "width", "height"}:
                    value = value * 72 / 25.4
                setattr(item, key, max(0 if key in {"x", "y"} else 6, value))
            if item.kind == "polyline" and old_width and old_height:
                item.points = [
                    [point[0] * item.width / old_width, point[1] * item.height / old_height]
                    for point in item.points
                ]
        self._mutate(apply)

    def _nudge_selected(self, event: tk.Event[tk.Misc], horizontal: int, vertical: int) -> str | None:
        if event.widget.winfo_class() in {"Entry", "TEntry", "Text", "TCombobox"}:
            return None
        if not self.selected_indices:
            return None
        try:
            millimetres = float(self.nudge_var.get().replace(",", "."))
        except ValueError:
            millimetres = 1.0
        if event.state & 0x0001:
            millimetres *= 10
        delta = millimetres * 72 / 25.4
        self._checkpoint()
        page_width, page_height = self._page_size()
        for index in self.selected_indices:
            item = self.document.objects[index]
            item.x = max(0, min(page_width - item.width, item.x + horizontal * delta))
            item.y = max(0, min(page_height - item.height, item.y + vertical * delta))
        self._render()
        self.status.configure(text=f"Déplacement précis : {millimetres:g} mm.")
        return "break"

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
