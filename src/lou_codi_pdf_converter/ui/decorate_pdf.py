from __future__ import annotations

import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pymupdf

from ..paths import collision_free_target, downloads_directory
from ..services.pdf_decoration import (
    DecorationSettings,
    apply_pdf_decorations,
    parse_page_selection,
)
from ..system import open_path
from .dialogs import show_success
from .directory_picker import choose_directory
from .pdf_picker import choose_pdfs
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
        self.header_text = tk.StringVar()
        self.header_position = tk.StringVar(value="center")
        self.footer_text = tk.StringVar(value="Page {page} / {pages}")
        self.footer_position = tk.StringVar(value="center")
        self.text_size = tk.DoubleVar(value=9)
        self.text_color = tk.StringVar(value="#193B66")
        self.footer_line = tk.BooleanVar(value=False)
        self.mask_footer = tk.BooleanVar(value=False)
        self.mask_height = tk.DoubleVar(value=18)
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
        texts = ttk.Frame(notebook, padding=16)
        masking = ttk.Frame(notebook, padding=16)
        notebook.add(watermark, text="Filigrane")
        notebook.add(texts, text="En-tête et pied de page")
        notebook.add(masking, text="Masquage visuel")
        self._build_watermark_tab(watermark)
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

        ttk.Label(right, text="APERÇU DE LA PREMIÈRE PAGE", style="Title.TLabel").pack(anchor="w")
        self.preview_label = ttk.Label(
            right,
            text="Choisissez un PDF puis cliquez sur\n« Actualiser l’aperçu ».",
            style="Body.TLabel",
            anchor="center",
            justify="center",
        )
        self.preview_label.pack(fill="both", expand=True, pady=12)

    def _build_watermark_tab(self, tab: ttk.Frame) -> None:
        self._field(tab, "Texte libre", self.watermark_text, 0)
        ttk.Label(tab, text="Image ou logo PNG", style="Body.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(tab, textvariable=self.watermark_image).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(tab, text="Choisir…", command=self._choose_watermark_image).grid(row=1, column=2)
        self._field(tab, "Taille", self.watermark_size, 2)
        self._field(tab, "Rotation (degrés)", self.watermark_rotation, 3)
        self._field(tab, "Transparence (%)", self.watermark_opacity, 4)
        self._field(tab, "Couleur hexadécimale", self.watermark_color, 5)
        self._field(tab, "Position X (mm, vide = centre)", self.watermark_x, 6)
        self._field(tab, "Position Y (mm, vide = centre)", self.watermark_y, 7)
        ttk.Checkbutton(tab, text="Placer au premier plan", variable=self.watermark_front).grid(row=8, column=1, sticky="w", pady=8)
        tab.columnconfigure(1, weight=1)

    def _build_text_tab(self, tab: ttk.Frame) -> None:
        self._field(tab, "En-tête", self.header_text, 0)
        self._position_field(tab, "Position en-tête", self.header_position, 1)
        self._field(tab, "Pied de page", self.footer_text, 2)
        self._position_field(tab, "Position pied", self.footer_position, 3)
        self._field(tab, "Taille du texte", self.text_size, 4)
        self._field(tab, "Couleur", self.text_color, 5)
        ttk.Checkbutton(tab, text="Ajouter un liseré horizontal", variable=self.footer_line).grid(row=6, column=1, sticky="w", pady=8)
        ttk.Label(tab, text="Variables : {page}  {pages}  {document}  {date}", style="Body.TLabel").grid(row=7, column=0, columnspan=3, sticky="w", pady=10)
        tab.columnconfigure(1, weight=1)

    def _build_mask_tab(self, tab: ttk.Frame) -> None:
        ttk.Checkbutton(tab, text="Recouvrir l’ancien pied de page par une zone blanche", variable=self.mask_footer).pack(anchor="w", pady=8)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="Hauteur de la zone blanche (mm)").pack(side="left")
        ttk.Entry(row, textvariable=self.mask_height, width=10).pack(side="left", padx=12)
        ttk.Label(
            tab,
            text="Attention : ce masquage est uniquement visuel. Il ne supprime pas de façon sécurisée les informations confidentielles du PDF.",
            foreground="#9A4B20",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=18)

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
        selected = filedialog.askopenfilename(parent=self, initialdir=downloads_directory(), filetypes=(("Images", "*.png *.jpg *.jpeg"),))
        if selected:
            self.watermark_image.set(selected)

    def _choose_destination(self) -> None:
        selected = choose_directory(self, Path(self.destination.get()).expanduser())
        if selected:
            self.destination.set(str(selected))

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
            header_text=self.header_text.get(),
            header_position=self.header_position.get(),
            footer_text=self.footer_text.get(),
            footer_position=self.footer_position.get(),
            text_size=self.text_size.get(),
            text_color=self.text_color.get(),
            footer_line=self.footer_line.get(),
            mask_original_footer=self.mask_footer.get(),
            footer_mask_height_mm=self.mask_height.get(),
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
            document.close()
            self.preview_label.configure(image=self.preview_image, text="")
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

    def _close(self) -> None:
        self.temp_directory.cleanup()
        self.destroy()


def _optional_float(value: str) -> float | None:
    return float(value.replace(",", ".")) if value.strip() else None

