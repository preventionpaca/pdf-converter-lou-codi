from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pymupdf

from ..paths import collision_free_target, downloads_directory
from ..services.pdf_decoration import (
    DecorationSettings,
    MaskZone,
    apply_pdf_decorations,
    parse_page_selection,
)
from ..system import open_path
from .dialogs import show_success
from .directory_picker import choose_directory
from .pdf_picker import choose_documents, choose_pdfs
from .windowing import make_modal, maximize_window

BACKGROUND = "#F0F4F9"
NAVY = "#193B66"
MUTED = "#597089"


class DecoratePdfWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, class_="LouCodiPdfConverter")
        self.title("Habillage PDF — PDF Converter Lou Còdi")
        self.minsize(950, 680)
        self.configure(bg=BACKGROUND)
        maximize_window(self)
        self.source: Path | None = None
        self.page_count = 0
        self.preview_image: tk.PhotoImage | None = None
        self.last_output: Path | None = None
        self.temp_directory = tempfile.TemporaryDirectory(prefix="lou-codi-preview-")
        self.destination = tk.StringVar(value=str(downloads_directory()))
        self.pages = tk.StringVar(value="Toutes")
        self.watermark_text = tk.StringVar()
        self.watermark_image = tk.StringVar()
        self.watermark_size = tk.DoubleVar(value=52)
        self.watermark_rotation = tk.DoubleVar(value=35)
        self.watermark_opacity = tk.DoubleVar(value=18)
        self.watermark_color = tk.StringVar(value="#7A8795")
        self.watermark_x = tk.StringVar()
        self.watermark_y = tk.StringVar()
        self.watermark_front = tk.BooleanVar(value=True)
        self.logo_image = tk.StringVar()
        self.logo_x = tk.StringVar()
        self.logo_y = tk.StringVar()
        self.logo_width = tk.DoubleVar(value=28)
        self.logo_opacity = tk.DoubleVar(value=0)
        self.header_text = tk.StringVar()
        self.header_position = tk.StringVar(value="center")
        self.header_x = tk.StringVar()
        self.header_y = tk.DoubleVar(value=12)
        self.footer_text = tk.StringVar(value="Page {page} / {pages}")
        self.footer_position = tk.StringVar(value="center")
        self.footer_x = tk.StringVar()
        self.footer_y = tk.DoubleVar(value=10)
        self.text_size = tk.DoubleVar(value=9)
        self.text_color = tk.StringVar(value="#193B66")
        self.footer_line = tk.BooleanVar(value=False)
        self.mask_footer = tk.BooleanVar(value=False)
        self.mask_height = tk.DoubleVar(value=18)
        self.mask_zones: list[MaskZone] = []
        self.mask_name = tk.StringVar(value="Zone libre")
        self.mask_x = tk.DoubleVar(value=40)
        self.mask_y = tk.DoubleVar(value=40)
        self.mask_width = tk.DoubleVar(value=100)
        self.mask_zone_height = tk.DoubleVar(value=35)
        self.mask_color = tk.StringVar(value="#FFFFFF")
        self.placement_target = tk.StringVar(value="watermark")
        self.mask_drag_start: tuple[float, float] | None = None
        self.preview_scale = 1.0
        self.preview_page_width = 0.0
        self.preview_page_height = 0.0
        self.preview_origin = (0.0, 0.0)
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        make_modal(self, parent)

    def _build(self) -> None:
        app_icon = getattr(self._root(), "app_icon", None)
        if app_icon is not None:
            self.iconphoto(False, app_icon)
        header = tk.Frame(self, bg=NAVY, padx=22, pady=10)
        header.pack(fill="x")
        if app_icon is not None:
            self.workspace_logo = app_icon.subsample(17, 17)
            tk.Label(header, image=self.workspace_logo, bg=NAVY, borderwidth=0).pack(side="left", padx=(0, 14))
        titles = tk.Frame(header, bg=NAVY)
        titles.pack(side="left")
        tk.Label(titles, text="Habillage PDF", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(anchor="w")
        tk.Label(titles, text="Filigranes, en-têtes et pieds de page avec aperçu", bg=NAVY, fg="#CBDFF5", font=("Sans", 10)).pack(anchor="w")

        body = ttk.Frame(self, style="App.TFrame", padding=16)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="App.TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(body, style="Card.TFrame", padding=14, width=430)
        right.pack(side="right", fill="both")
        right.pack_propagate(False)

        source_card = ttk.Frame(left, style="Card.TFrame", padding=12)
        source_card.pack(fill="x", pady=(0, 8))
        ttk.Button(source_card, text="Choisir un PDF…", command=self._choose_pdf).pack(side="left")
        self.source_label = ttk.Label(source_card, text="Aucun document", style="Body.TLabel")
        self.source_label.pack(side="left", padx=12)
        ttk.Label(source_card, text="Pages :", style="Body.TLabel").pack(side="right")
        ttk.Entry(source_card, textvariable=self.pages, width=16).pack(side="right", padx=6)

        notebook = ttk.Notebook(left)
        notebook.pack(fill="both", expand=True, pady=(0, 8))
        watermark = ttk.Frame(notebook, padding=16)
        logo = ttk.Frame(notebook, padding=16)
        texts = ttk.Frame(notebook, padding=16)
        masking = ttk.Frame(notebook, padding=16)
        notebook.add(watermark, text="Filigrane")
        notebook.add(logo, text="Logo")
        notebook.add(texts, text="En-tête et pied de page")
        notebook.add(masking, text="Masquage visuel")
        self._build_watermark_tab(watermark)
        self._build_logo_tab(logo)
        self._build_text_tab(texts)
        self._build_mask_tab(masking)

        destination = ttk.Frame(left, style="Card.TFrame", padding=12)
        destination.pack(fill="x", pady=(0, 8))
        ttk.Label(destination, text="Destination", style="Title.TLabel").pack(side="left")
        ttk.Entry(destination, textvariable=self.destination).pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(destination, text="Parcourir…", command=self._choose_destination).pack(side="left")

        actions = ttk.Frame(left, style="App.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="Actualiser l’aperçu", command=self._preview).pack(side="left")
        ttk.Button(actions, text="Valider et exporter", style="Primary.TButton", command=self._export).pack(side="left", padx=8)
        self.open_button = ttk.Button(actions, text="Ouvrir le résultat", command=self._open_output, state="disabled")
        self.open_button.pack(side="left")
        self.status = ttk.Label(actions, text="Prêt.", background=BACKGROUND, foreground=MUTED)
        self.status.pack(side="right")

        ttk.Label(right, text="PLACEMENT À LA SOURIS", style="Title.TLabel").pack(anchor="w")
        placement = ttk.Frame(right, style="Card.TFrame")
        placement.pack(fill="x", pady=(8, 4))
        for text, value in (
            ("Filigrane", "watermark"),
            ("Logo", "logo"),
            ("En-tête", "header"),
            ("Pied", "footer"),
            ("Masque", "mask"),
        ):
            ttk.Radiobutton(
                placement,
                text=text,
                value=value,
                variable=self.placement_target,
            ).pack(side="left", padx=(0, 6))
        ttk.Label(
            right,
            text="Cliquez ou faites glisser l’élément choisi sur la page.",
            style="Body.TLabel",
            wraplength=390,
        ).pack(anchor="w", pady=(0, 6))
        self.preview_canvas = tk.Canvas(
            right,
            background="white",
            highlightthickness=1,
            highlightbackground="#D9E2ED",
            cursor="crosshair",
        )
        self.preview_canvas.pack(fill="both", expand=True, pady=6)
        self.preview_canvas.create_text(
            205,
            280,
            text="Choisissez un PDF puis cliquez sur\n« Actualiser l’aperçu ».",
            fill=MUTED,
            justify="center",
        )
        self.preview_canvas.bind("<Button-1>", self._placement_press)
        self.preview_canvas.bind("<B1-Motion>", self._placement_motion)
        self.preview_canvas.bind("<ButtonRelease-1>", self._placement_release)

    def _build_watermark_tab(self, tab: ttk.Frame) -> None:
        self._field(tab, "Texte libre", self.watermark_text, 0)
        presets = ttk.Frame(tab)
        presets.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 6))
        for label in ("Temporaire", "Financier", "Confidentiel", "Brouillon"):
            ttk.Button(
                presets,
                text=label,
                command=lambda value=label: self.watermark_text.set(value.upper()),
            ).pack(side="left", padx=(0, 6))
        ttk.Label(tab, text="Image de filigrane", style="Body.TLabel").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(tab, textvariable=self.watermark_image).grid(row=2, column=1, sticky="ew", padx=8)
        ttk.Button(tab, text="Choisir…", command=self._choose_watermark_image).grid(row=2, column=2)
        self._field(tab, "Taille", self.watermark_size, 3)
        self._field(tab, "Rotation (degrés)", self.watermark_rotation, 4)
        self._field(tab, "Transparence (%)", self.watermark_opacity, 5)
        self._field(tab, "Couleur hexadécimale", self.watermark_color, 6)
        self._field(tab, "Position X (mm, vide = centre)", self.watermark_x, 7)
        self._field(tab, "Position Y (mm, vide = centre)", self.watermark_y, 8)
        ttk.Checkbutton(tab, text="Placer au premier plan", variable=self.watermark_front).grid(row=9, column=1, sticky="w", pady=8)
        tab.columnconfigure(1, weight=1)

    def _build_logo_tab(self, tab: ttk.Frame) -> None:
        ttk.Label(tab, text="Logo appliqué aux pages sélectionnées").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(tab, text="Fichier PNG ou JPG").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(tab, textvariable=self.logo_image).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(tab, text="Choisir…", command=self._choose_logo_image).grid(row=1, column=2)
        self._field(tab, "Largeur (mm)", self.logo_width, 2)
        self._field(tab, "Transparence (%)", self.logo_opacity, 3)
        self._field(tab, "Position X (mm, vide = centre)", self.logo_x, 4)
        self._field(tab, "Position Y (mm, vide = haut)", self.logo_y, 5)
        ttk.Label(
            tab,
            text="Sélectionnez « Logo » à droite, puis cliquez ou faites glisser sur l’aperçu.",
            wraplength=700,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=14)
        tab.columnconfigure(1, weight=1)

    def _build_text_tab(self, tab: ttk.Frame) -> None:
        self._field(tab, "En-tête", self.header_text, 0)
        self._position_field(tab, "Position en-tête", self.header_position, 1)
        self._field(tab, "En-tête X (mm, vide = alignement)", self.header_x, 2)
        self._field(tab, "En-tête depuis le haut (mm)", self.header_y, 3)
        self._field(tab, "Pied de page", self.footer_text, 4)
        self._position_field(tab, "Position pied", self.footer_position, 5)
        self._field(tab, "Pied X (mm, vide = alignement)", self.footer_x, 6)
        self._field(tab, "Pied depuis le bas (mm)", self.footer_y, 7)
        self._field(tab, "Taille du texte", self.text_size, 8)
        self._field(tab, "Couleur", self.text_color, 9)
        ttk.Checkbutton(tab, text="Ajouter un liseré horizontal", variable=self.footer_line).grid(row=10, column=1, sticky="w", pady=8)
        ttk.Label(tab, text="Variables : {page}  {pages}  {document}  {date}", style="Body.TLabel").grid(row=11, column=0, columnspan=3, sticky="w", pady=10)
        tab.columnconfigure(1, weight=1)

    def _build_mask_tab(self, tab: ttk.Frame) -> None:
        presets = ttk.Frame(tab)
        presets.pack(fill="x", pady=(0, 10))
        ttk.Label(presets, text="Ajouter rapidement :").pack(side="left", padx=(0, 8))
        for label, kind in (
            ("Marge gauche", "left"),
            ("Marge droite", "right"),
            ("En-tête", "header"),
            ("Pied de page", "footer"),
            ("Zone libre", "free"),
        ):
            ttk.Button(
                presets,
                text=label,
                command=lambda value=kind: self._add_mask_preset(value),
            ).pack(side="left", padx=(0, 6))

        table_row = ttk.Frame(tab)
        table_row.pack(fill="both", expand=True)
        self.mask_tree = ttk.Treeview(
            table_row,
            columns=("name", "x", "y", "width", "height"),
            show="headings",
            selectmode="browse",
            height=5,
        )
        for column, label, width in (
            ("name", "Zone", 180),
            ("x", "X mm", 80),
            ("y", "Y mm", 80),
            ("width", "Largeur", 90),
            ("height", "Hauteur", 90),
        ):
            self.mask_tree.heading(column, text=label)
            self.mask_tree.column(column, width=width, stretch=column == "name")
        self.mask_tree.pack(side="left", fill="both", expand=True)
        self.mask_tree.bind("<<TreeviewSelect>>", self._load_selected_mask)

        editor = ttk.Frame(tab, padding=(14, 0, 0, 0))
        editor.pack(fill="x", pady=(12, 0))
        fields = (
            ("Nom", self.mask_name),
            ("X (mm)", self.mask_x),
            ("Y depuis le bas (mm)", self.mask_y),
            ("Largeur (mm)", self.mask_width),
            ("Hauteur (mm)", self.mask_zone_height),
            ("Couleur", self.mask_color),
        )
        for index, (label, variable) in enumerate(fields):
            ttk.Label(editor, text=label).grid(row=index // 3 * 2, column=index % 3, sticky="w")
            ttk.Entry(editor, textvariable=variable, width=18).grid(
                row=index // 3 * 2 + 1,
                column=index % 3,
                sticky="ew",
                padx=(0, 10),
                pady=(2, 8),
            )
        editor.columnconfigure((0, 1, 2), weight=1)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Ajouter avec ces coordonnées", command=self._add_mask_from_fields).pack(side="left")
        ttk.Button(buttons, text="Mettre à jour", command=self._update_selected_mask).pack(side="left", padx=6)
        ttk.Button(buttons, text="Supprimer", command=self._delete_selected_mask).pack(side="left")
        ttk.Label(
            buttons,
            text="Pour tracer : sélectionnez « Masque » à droite puis faites glisser sur l’aperçu.",
        ).pack(side="right")
        ttk.Label(
            tab,
            text="Attention : ces masques sont uniquement visuels. Ils ne suppriment pas de façon sécurisée les informations confidentielles du PDF.",
            foreground="#9A4B20",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

    def _field(self, parent: ttk.Frame, label: str, variable: tk.Variable, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, columnspan=2, sticky="ew", padx=8)

    def _position_field(self, parent: ttk.Frame, label: str, variable: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Combobox(parent, textvariable=variable, values=("left", "center", "right"), state="readonly").grid(row=row, column=1, sticky="ew", padx=8)

    def _choose_pdf(self) -> None:
        selected = choose_pdfs(self)
        if not selected:
            return
        self.source = selected[0]
        self.page_count = len(pymupdf.open(self.source))
        self.source_label.configure(text=f"{self.source.name} — {self.page_count} page(s)")

    def _choose_watermark_image(self) -> None:
        selected = choose_documents(self, {".png", ".jpg", ".jpeg"})
        if selected:
            self.watermark_image.set(str(selected[0]))

    def _choose_logo_image(self) -> None:
        selected = choose_documents(self, {".png", ".jpg", ".jpeg"})
        if selected:
            self.logo_image.set(str(selected[0]))

    def _choose_destination(self) -> None:
        selected = choose_directory(self, Path(self.destination.get()).expanduser())
        if selected:
            self.destination.set(str(selected))

    def _page_dimensions_mm(self) -> tuple[float, float]:
        if self.source:
            document = pymupdf.open(self.source)
            rect = document[0].rect
            document.close()
            return rect.width * 25.4 / 72, rect.height * 25.4 / 72
        return 210.0, 297.0

    def _add_mask_preset(self, kind: str) -> None:
        page_width, page_height = self._page_dimensions_mm()
        margin = 20.0
        if kind == "left":
            zone = MaskZone("Marge gauche", 0, 0, margin, page_height)
        elif kind == "right":
            zone = MaskZone("Marge droite", page_width - margin, 0, margin, page_height)
        elif kind == "header":
            zone = MaskZone("En-tête", 0, page_height - margin, page_width, margin)
        elif kind == "footer":
            zone = MaskZone("Pied de page", 0, 0, page_width, margin)
        else:
            zone = MaskZone("Zone libre", 40, 40, min(100, page_width - 40), 35)
        self.mask_zones.append(zone)
        self._refresh_mask_tree(len(self.mask_zones) - 1)

    def _add_mask_from_fields(self) -> None:
        try:
            zone = self._mask_from_fields()
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Masque invalide", str(exc), parent=self)
            return
        self.mask_zones.append(zone)
        self._refresh_mask_tree(len(self.mask_zones) - 1)

    def _mask_from_fields(self) -> MaskZone:
        return MaskZone(
            self.mask_name.get().strip() or "Zone libre",
            self.mask_x.get(),
            self.mask_y.get(),
            self.mask_width.get(),
            self.mask_zone_height.get(),
            self.mask_color.get().strip() or "#FFFFFF",
        )

    def _refresh_mask_tree(self, selected_index: int | None = None) -> None:
        self.mask_tree.delete(*self.mask_tree.get_children())
        for index, zone in enumerate(self.mask_zones):
            self.mask_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    zone.name,
                    f"{zone.x_mm:.1f}",
                    f"{zone.y_mm:.1f}",
                    f"{zone.width_mm:.1f}",
                    f"{zone.height_mm:.1f}",
                ),
            )
        if selected_index is not None and self.mask_tree.exists(str(selected_index)):
            self.mask_tree.selection_set(str(selected_index))
            self.mask_tree.see(str(selected_index))

    def _load_selected_mask(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.mask_tree.selection()
        if not selection:
            return
        zone = self.mask_zones[int(selection[0])]
        self.mask_name.set(zone.name)
        self.mask_x.set(zone.x_mm)
        self.mask_y.set(zone.y_mm)
        self.mask_width.set(zone.width_mm)
        self.mask_zone_height.set(zone.height_mm)
        self.mask_color.set(zone.color)

    def _update_selected_mask(self) -> None:
        selection = self.mask_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        try:
            self.mask_zones[index] = self._mask_from_fields()
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Masque invalide", str(exc), parent=self)
            return
        self._refresh_mask_tree(index)

    def _delete_selected_mask(self) -> None:
        selection = self.mask_tree.selection()
        if not selection:
            return
        self.mask_zones.pop(int(selection[0]))
        self._refresh_mask_tree()

    def _settings(self) -> DecorationSettings:
        if not self.source:
            raise ValueError("Choisissez d’abord un document PDF.")
        selected_pages = parse_page_selection(self.pages.get(), self.page_count)
        image_text = self.watermark_image.get().strip()
        return DecorationSettings(
            selected_pages=selected_pages,
            watermark_text=self.watermark_text.get(),
            watermark_image=Path(image_text) if image_text else None,
            watermark_x_mm=_optional_float(self.watermark_x.get()),
            watermark_y_mm=_optional_float(self.watermark_y.get()),
            watermark_size=self.watermark_size.get(),
            watermark_rotation=self.watermark_rotation.get(),
            watermark_opacity=1 - min(100, max(0, self.watermark_opacity.get())) / 100,
            watermark_color=self.watermark_color.get(),
            watermark_front=self.watermark_front.get(),
            logo_image=Path(self.logo_image.get()) if self.logo_image.get().strip() else None,
            logo_x_mm=_optional_float(self.logo_x.get()),
            logo_y_mm=_optional_float(self.logo_y.get()),
            logo_width_mm=self.logo_width.get(),
            logo_opacity=1 - min(100, max(0, self.logo_opacity.get())) / 100,
            header_text=self.header_text.get(),
            header_position=self.header_position.get(),
            header_x_mm=_optional_float(self.header_x.get()),
            header_y_mm=self.header_y.get(),
            footer_text=self.footer_text.get(),
            footer_position=self.footer_position.get(),
            footer_x_mm=_optional_float(self.footer_x.get()),
            footer_y_mm=self.footer_y.get(),
            text_size=self.text_size.get(),
            text_color=self.text_color.get(),
            footer_line=self.footer_line.get(),
            mask_original_footer=self.mask_footer.get(),
            footer_mask_height_mm=self.mask_height.get(),
            mask_zones=tuple(self.mask_zones),
        )

    def _preview(self) -> None:
        if not self.source:
            messagebox.showwarning("Aucun PDF", "Choisissez d’abord un document PDF.", parent=self)
            return
        target = Path(self.temp_directory.name) / "preview.pdf"
        try:
            apply_pdf_decorations(self.source, target, self._settings())
            document = pymupdf.open(target)
            page = document[0]
            scale = min(390 / page.rect.width, 600 / page.rect.height)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            self.preview_image = tk.PhotoImage(data=pixmap.tobytes("png"))
            self.preview_scale = scale
            self.preview_page_width = page.rect.width
            self.preview_page_height = page.rect.height
            document.close()
            self.preview_canvas.update_idletasks()
            origin_x = max(0, (self.preview_canvas.winfo_width() - self.preview_image.width()) / 2)
            origin_y = max(0, (self.preview_canvas.winfo_height() - self.preview_image.height()) / 2)
            self.preview_origin = (origin_x, origin_y)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(origin_x, origin_y, image=self.preview_image, anchor="nw")
            self.status.configure(text="Aperçu actualisé.")
        except Exception as exc:  # noqa: BLE001 - présenter toute erreur de configuration
            messagebox.showerror("Aperçu impossible", str(exc), parent=self)

    def _export(self) -> None:
        if not self.source:
            messagebox.showwarning("Aucun PDF", "Choisissez d’abord un document PDF.", parent=self)
            return
        destination = Path(self.destination.get()).expanduser()
        if not destination.is_dir():
            messagebox.showerror("Dossier introuvable", "Choisissez un dossier existant.", parent=self)
            return
        target = collision_free_target(destination, f"{self.source.stem}_habillé", ".pdf")
        try:
            apply_pdf_decorations(self.source, target, self._settings())
        except Exception as exc:  # noqa: BLE001 - présenter l’erreur d’export
            messagebox.showerror("Export impossible", str(exc), parent=self)
            return
        self.last_output = target
        self.open_button.configure(state="normal")
        self.status.configure(text=f"PDF créé : {target.name}")
        show_success(self, "Habillage terminé", f"Le document a été créé dans :\n\n{target}", action_label="Ouvrir le PDF", action=lambda: open_path(target))

    def _open_output(self) -> None:
        if self.last_output and self.last_output.is_file():
            open_path(self.last_output)

    def _placement_press(self, event: tk.Event[tk.Misc]) -> None:
        if self.placement_target.get() == "mask":
            self.mask_drag_start = (event.x, event.y)
            self.preview_canvas.delete("placement")
            return
        self._place_element(event)

    def _placement_motion(self, event: tk.Event[tk.Misc]) -> None:
        if self.placement_target.get() != "mask":
            self._place_element(event)
            return
        if not self.mask_drag_start:
            return
        start_x, start_y = self.mask_drag_start
        self.preview_canvas.delete("placement")
        self.preview_canvas.create_rectangle(
            start_x,
            start_y,
            event.x,
            event.y,
            outline="#2368AF",
            width=2,
            dash=(5, 3),
            tags="placement",
        )

    def _placement_release(self, event: tk.Event[tk.Misc]) -> None:
        if self.placement_target.get() == "mask":
            self._finish_mask_placement(event)
        else:
            self._finish_placement(event)

    def _event_to_pdf_mm(self, x: float, y: float) -> tuple[float, float]:
        origin_x, origin_y = self.preview_origin
        image_x = min(max(0, x - origin_x), self.preview_image.width())
        image_y = min(max(0, y - origin_y), self.preview_image.height())
        x_mm = image_x / self.preview_scale * 25.4 / 72
        y_mm = (self.preview_page_height - image_y / self.preview_scale) * 25.4 / 72
        return x_mm, y_mm

    def _finish_mask_placement(self, event: tk.Event[tk.Misc]) -> None:
        if not self.preview_image or not self.mask_drag_start:
            self.mask_drag_start = None
            return
        start_x_mm, start_y_mm = self._event_to_pdf_mm(*self.mask_drag_start)
        end_x_mm, end_y_mm = self._event_to_pdf_mm(event.x, event.y)
        zone = MaskZone(
            "Zone tracée",
            min(start_x_mm, end_x_mm),
            min(start_y_mm, end_y_mm),
            abs(end_x_mm - start_x_mm),
            abs(end_y_mm - start_y_mm),
        )
        self.mask_drag_start = None
        if zone.width_mm < 1 or zone.height_mm < 1:
            self.preview_canvas.delete("placement")
            return
        self.mask_zones.append(zone)
        self._refresh_mask_tree(len(self.mask_zones) - 1)
        self._preview()

    def _place_element(self, event: tk.Event[tk.Misc]) -> None:
        if not self.preview_image or not self.preview_page_width:
            return
        x_mm, y_from_bottom_mm = self._event_to_pdf_mm(event.x, event.y)
        target = self.placement_target.get()
        if target == "watermark":
            self.watermark_x.set(f"{x_mm:.1f}")
            self.watermark_y.set(f"{y_from_bottom_mm:.1f}")
        elif target == "logo":
            self.logo_x.set(f"{x_mm:.1f}")
            self.logo_y.set(f"{y_from_bottom_mm:.1f}")
        elif target == "header":
            self.header_x.set(f"{x_mm:.1f}")
            page_height_mm = self.preview_page_height * 25.4 / 72
            self.header_y.set(round(page_height_mm - y_from_bottom_mm, 1))
        else:
            self.footer_x.set(f"{x_mm:.1f}")
            self.footer_y.set(round(y_from_bottom_mm, 1))
        self.preview_canvas.delete("placement")
        self.preview_canvas.create_oval(
            event.x - 7,
            event.y - 7,
            event.x + 7,
            event.y + 7,
            outline="#2368AF",
            width=2,
            tags="placement",
        )
        self.status.configure(text=f"Placement {target} : X {x_mm:.1f} mm")

    def _finish_placement(self, _event: tk.Event[tk.Misc]) -> None:
        if self.preview_image:
            self._preview()

    def _close(self) -> None:
        self.temp_directory.cleanup()
        self.destroy()


def _optional_float(value: str) -> float | None:
    return float(value.replace(",", ".")) if value.strip() else None
