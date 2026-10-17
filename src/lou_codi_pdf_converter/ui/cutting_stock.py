from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..i18n import translate_widget_tree
from ..services.canvas_document import CanvasDocument
from ..services.cutting_optimizer import Part, Sheet, optimize_cutting
from ..services.local_database import (
    add_stock_sheet,
    clear_stock_sheets,
    list_stock_sheets,
    set_stock_sheet_status,
)
from .pdf_picker import choose_documents
from .windowing import make_modal, maximize_window

NAVY = "#193B66"
BLUE = "#2368AF"
BACKGROUND = "#F0F4F9"
PLACEMENT_COLORS = ("#BDE3F2", "#D6EDC4", "#FFE0A6", "#E1CEF2", "#F5C8C8")


class CuttingStockWindow(tk.Toplevel):
    """Local sheet stock and rectangular cutting-plan workspace."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title("Stock et plan de découpe — Lou Còdi")
        self.configure(bg=BACKGROUND)
        self.parts: list[Part] = []
        self._build()
        self._refresh_stock()
        maximize_window(self)
        make_modal(self, parent)
        translate_widget_tree(self)

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, height=94)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="Stock et plan de découpe",
            bg=NAVY,
            fg="white",
            font=("Sans", 21, "bold"),
        ).pack(anchor="w", padx=24, pady=(16, 2))
        tk.Label(
            header,
            text="Plaques, chutes réutilisables et optimisation locale des découpes",
            bg=NAVY,
            fg="#CBDFF5",
            font=("Sans", 10),
        ).pack(anchor="w", padx=24)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=14)
        controls = ttk.Frame(body, padding=8)
        preview = ttk.Frame(body, padding=8)
        body.add(controls, weight=3)
        body.add(preview, weight=2)

        self._build_stock(controls)
        self._build_parts(controls)

        ttk.Label(preview, text="APERÇU DU PLAN", font=("Sans", 15, "bold"), foreground=NAVY).pack(
            anchor="w", pady=(0, 8)
        )
        canvas_frame = ttk.Frame(preview)
        canvas_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#D7DFE9", highlightthickness=0)
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=y_scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda _event: self._redraw_last_plan())
        self.last_plan = None
        self.status = ttk.Label(preview, text="Ajoutez le stock et les pièces à découper.")
        self.status.pack(fill="x", pady=(8, 0))

    def _build_stock(self, parent: ttk.Frame) -> None:
        stock_box = ttk.LabelFrame(parent, text="1 — Mon stock de plaques", padding=10)
        stock_box.pack(fill="both", expand=True, pady=(0, 10))
        form = ttk.Frame(stock_box)
        form.pack(fill="x", pady=(0, 8))
        self.stock_vars = {
            "label": tk.StringVar(value="Plaque"),
            "material": tk.StringVar(value="Bois"),
            "width": tk.StringVar(value="2500"),
            "height": tk.StringVar(value="1250"),
            "thickness": tk.StringVar(value="18"),
            "quantity": tk.StringVar(value="1"),
        }
        fields = (
            ("Nom", "label", 16),
            ("Matière", "material", 13),
            ("Largeur mm", "width", 9),
            ("Hauteur mm", "height", 9),
            ("Épaisseur", "thickness", 8),
            ("Quantité", "quantity", 7),
        )
        for column, (label, key, width) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=column, sticky="w", padx=3)
            ttk.Entry(form, textvariable=self.stock_vars[key], width=width).grid(
                row=1, column=column, sticky="ew", padx=3
            )
            form.columnconfigure(column, weight=1)
        ttk.Button(form, text="Ajouter au stock", command=self._add_stock).grid(
            row=1, column=len(fields), padx=(8, 3)
        )

        columns = ("id", "label", "material", "dimensions", "thickness", "quantity", "status")
        self.stock_tree = ttk.Treeview(stock_box, columns=columns, show="headings", height=6)
        headings = ("ID", "Nom", "Matière", "Dimensions (mm)", "Ép.", "Qté", "État")
        widths = (45, 130, 100, 145, 60, 55, 90)
        for column, heading, width in zip(columns, headings, widths, strict=True):
            self.stock_tree.heading(column, text=heading)
            self.stock_tree.column(column, width=width, anchor="center" if column != "label" else "w")
        self.stock_tree.pack(fill="both", expand=True)
        actions = ttk.Frame(stock_box)
        actions.pack(fill="x", pady=(7, 0))
        ttk.Button(actions, text="Disponible", command=lambda: self._set_stock_status("available")).pack(side="left")
        ttk.Button(actions, text="Utilisée", command=lambda: self._set_stock_status("used")).pack(side="left", padx=5)
        ttk.Button(actions, text="Chute inutilisable", command=lambda: self._set_stock_status("scrap")).pack(side="left")
        ttk.Button(actions, text="Vider mon magasin", command=self._clear_stock).pack(side="left", padx=(12, 0))
        ttk.Label(actions, text="Les données restent uniquement sur cet ordinateur.").pack(side="right")

    def _build_parts(self, parent: ttk.Frame) -> None:
        part_box = ttk.LabelFrame(parent, text="2 — Pièces à obtenir", padding=10)
        part_box.pack(fill="both", expand=True)
        form = ttk.Frame(part_box)
        form.pack(fill="x", pady=(0, 8))
        self.part_vars = {
            "label": tk.StringVar(value="Pièce"),
            "width": tk.StringVar(value="500"),
            "height": tk.StringVar(value="300"),
            "quantity": tk.StringVar(value="1"),
            "rotation": tk.BooleanVar(value=True),
        }
        for column, (label, key, width) in enumerate(
            (("Nom", "label", 18), ("Largeur mm", "width", 10), ("Hauteur mm", "height", 10), ("Quantité", "quantity", 8))
        ):
            ttk.Label(form, text=label).grid(row=0, column=column, sticky="w", padx=3)
            ttk.Entry(form, textvariable=self.part_vars[key], width=width).grid(row=1, column=column, padx=3)
        ttk.Checkbutton(form, text="Rotation autorisée", variable=self.part_vars["rotation"]).grid(
            row=1, column=4, padx=8
        )
        ttk.Button(form, text="Ajouter la pièce", command=self._add_part).grid(row=1, column=5, padx=3)

        columns = ("label", "dimensions", "quantity", "rotation")
        self.parts_tree = ttk.Treeview(part_box, columns=columns, show="headings", height=6)
        for column, heading, width in zip(
            columns,
            ("Pièce", "Dimensions (mm)", "Quantité", "Rotation"),
            (180, 160, 80, 90),
            strict=True,
        ):
            self.parts_tree.heading(column, text=heading)
            self.parts_tree.column(column, width=width, anchor="center")
        self.parts_tree.pack(fill="both", expand=True)

        actions = ttk.Frame(part_box)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Retirer", command=self._remove_part).pack(side="left")
        ttk.Button(actions, text="Tout vider", command=self._clear_parts).pack(side="left", padx=5)
        ttk.Button(
            actions,
            text="Importer les rectangles d’un dessin",
            command=self._import_drawing_rectangles,
        ).pack(side="left", padx=(5, 14))
        ttk.Label(actions, text="Épaisseur de lame (mm)").pack(side="left", padx=(18, 4))
        self.kerf_var = tk.StringVar(value="3")
        ttk.Entry(actions, textvariable=self.kerf_var, width=7).pack(side="left")
        ttk.Button(actions, text="Calculer le plan de découpe", command=self._optimize).pack(
            side="right"
        )

    @staticmethod
    def _number(value: str, label: str, *, integer: bool = False) -> float | int:
        try:
            result = float(value.replace(",", "."))
        except ValueError as exc:
            raise ValueError(f"{label} doit être un nombre.") from exc
        if result <= 0:
            raise ValueError(f"{label} doit être supérieur à zéro.")
        if integer:
            if not result.is_integer():
                raise ValueError(f"{label} doit être un nombre entier.")
            return int(result)
        return result

    def _add_stock(self) -> None:
        try:
            thickness_text = self.stock_vars["thickness"].get().strip()
            add_stock_sheet(
                self.stock_vars["label"].get() or "Plaque",
                self.stock_vars["material"].get(),
                float(self._number(self.stock_vars["width"].get(), "La largeur")),
                float(self._number(self.stock_vars["height"].get(), "La hauteur")),
                float(self._number(thickness_text, "L’épaisseur")) if thickness_text else None,
                int(self._number(self.stock_vars["quantity"].get(), "La quantité", integer=True)),
            )
        except ValueError as exc:
            messagebox.showwarning("Valeur incorrecte", str(exc), parent=self)
            return
        self._refresh_stock()

    def _refresh_stock(self) -> None:
        for item in self.stock_tree.get_children():
            self.stock_tree.delete(item)
        labels = {"available": "Disponible", "reserved": "Réservée", "used": "Utilisée", "scrap": "Inutilisable"}
        for sheet in list_stock_sheets():
            self.stock_tree.insert(
                "",
                "end",
                iid=str(sheet.id),
                values=(sheet.id, sheet.label, sheet.material, f"{sheet.width_mm:g} × {sheet.height_mm:g}", f"{sheet.thickness_mm:g}" if sheet.thickness_mm else "—", sheet.quantity, labels[sheet.status]),
            )

    def _set_stock_status(self, status: str) -> None:
        selected = self.stock_tree.selection()
        if not selected:
            messagebox.showinfo("Stock", "Sélectionnez d’abord une plaque.", parent=self)
            return
        for item in selected:
            set_stock_sheet_status(int(item), status)
        self._refresh_stock()

    def _clear_stock(self) -> None:
        if not list_stock_sheets():
            messagebox.showinfo("Vider mon magasin", "Le magasin est déjà vide.", parent=self)
            return
        confirmed = messagebox.askyesno(
            "Vider mon magasin",
            "Supprimer définitivement toutes les plaques et toutes les chutes du magasin local ?",
            parent=self,
        )
        if not confirmed:
            return
        clear_stock_sheets()
        self.last_plan = None
        self.canvas.delete("all")
        self.status.configure(text="Magasin vidé. Ajoutez une plaque pour préparer un nouveau plan.")
        self._refresh_stock()

    def _add_part(self) -> None:
        try:
            part = Part(
                self.part_vars["label"].get() or "Pièce",
                float(self._number(self.part_vars["width"].get(), "La largeur")),
                float(self._number(self.part_vars["height"].get(), "La hauteur")),
                int(self._number(self.part_vars["quantity"].get(), "La quantité", integer=True)),
                self.part_vars["rotation"].get(),
            )
        except ValueError as exc:
            messagebox.showwarning("Valeur incorrecte", str(exc), parent=self)
            return
        self.parts.append(part)
        self.parts_tree.insert(
            "", "end", iid=str(len(self.parts) - 1), values=(part.label, f"{part.width:g} × {part.height:g}", part.quantity, "Oui" if part.rotation_allowed else "Non")
        )

    def _remove_part(self) -> None:
        selected = {int(item) for item in self.parts_tree.selection()}
        self.parts = [part for index, part in enumerate(self.parts) if index not in selected]
        self._refresh_parts()

    def _clear_parts(self) -> None:
        self.parts.clear()
        self._refresh_parts()

    def _refresh_parts(self) -> None:
        for item in self.parts_tree.get_children():
            self.parts_tree.delete(item)
        for index, part in enumerate(self.parts):
            self.parts_tree.insert("", "end", iid=str(index), values=(part.label, f"{part.width:g} × {part.height:g}", part.quantity, "Oui" if part.rotation_allowed else "Non"))

    def _import_drawing_rectangles(self) -> None:
        files = choose_documents(self, {".cod", ".loucodi-document"})
        if not files:
            return
        try:
            document = CanvasDocument.load(files[0])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Dessin illisible", str(exc), parent=self)
            return
        conversion = 25.4 / 72.0
        rectangles = [
            item
            for item in document.objects
            if item.kind == "shape" and item.shape in {"", "rectangle"}
        ]
        for index, item in enumerate(rectangles, start=1):
            self.parts.append(
                Part(
                    f"Rectangle {index}",
                    abs(item.width) * conversion,
                    abs(item.height) * conversion,
                    1,
                    True,
                )
            )
        self._refresh_parts()
        if rectangles:
            self.status.configure(
                text=f"{len(rectangles)} rectangle(s) importé(s) depuis {files[0].name}."
            )
        else:
            messagebox.showinfo(
                "Importer un dessin",
                "Ce projet ne contient aucun rectangle utilisable comme pièce.",
                parent=self,
            )

    def _optimize(self) -> None:
        stock = list_stock_sheets(available_only=True)
        if not stock or not self.parts:
            messagebox.showinfo("Plan de découpe", "Ajoutez au moins une plaque disponible et une pièce.", parent=self)
            return
        try:
            kerf = float(self.kerf_var.get().replace(",", "."))
            if kerf < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Valeur incorrecte", "L’épaisseur de lame doit être positive.", parent=self)
            return
        sheets = [Sheet(item.id, item.label or f"Plaque {item.id}", item.width_mm, item.height_mm, item.quantity) for item in stock]
        self.last_plan = optimize_cutting(sheets, self.parts, kerf)
        self._draw_plan()

    def _redraw_last_plan(self) -> None:
        if self.last_plan is not None:
            self.after_idle(self._draw_plan)

    def _draw_plan(self) -> None:
        plan = self.last_plan
        if plan is None:
            return
        self.canvas.delete("all")
        canvas_width = max(320, self.canvas.winfo_width() - 45)
        top = 30.0
        efficiencies: list[float] = []
        for sheet_index, sheet in enumerate(plan.sheets):
            scale = min(canvas_width / sheet.width, 330 / sheet.height)
            width = sheet.width * scale
            height = sheet.height * scale
            left = 20.0
            self.canvas.create_text(left, top - 12, text=f"{sheet.label} — {sheet.width:g} × {sheet.height:g} mm", anchor="w", font=("Sans", 10, "bold"))
            self.canvas.create_rectangle(left, top, left + width, top + height, fill="white", outline=NAVY, width=2)
            for index, item in enumerate(sheet.placements):
                x1 = left + item.x * scale
                y1 = top + item.y * scale
                x2 = x1 + item.width * scale
                y2 = y1 + item.height * scale
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=PLACEMENT_COLORS[(index + sheet_index) % len(PLACEMENT_COLORS)], outline="#34506D")
                if x2 - x1 > 45 and y2 - y1 > 24:
                    suffix = " ↻" if item.rotated else ""
                    self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=f"{item.label}{suffix}\n{item.width:g} × {item.height:g}", justify="center", font=("Sans", 8))
            efficiencies.append(sheet.efficiency)
            top += height + 55
        if not plan.sheets:
            self.canvas.create_text(30, 40, text="Aucune pièce n’a pu être placée.", anchor="w")
        self.canvas.configure(scrollregion=(0, 0, canvas_width + 40, max(top, self.canvas.winfo_height())))
        average = sum(efficiencies) / len(efficiencies) if efficiencies else 0
        message = f"{len(plan.sheets)} plaque(s) utilisée(s) — rendement moyen {average:.1%}."
        if plan.unplaced:
            message += f"  {len(plan.unplaced)} pièce(s) non placée(s)."
        self.status.configure(text=message)
