from __future__ import annotations

import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import ttk

from . import __version__
from .i18n import LANGUAGES, get_language, load_language, set_language, tr, translate_widget_tree
from .ui.decorate_pdf import DecoratePdfWindow
from .ui.documents_to_pdf import DocumentsToPdfWindow
from .ui.organize_pdf import OrganizePdfWindow
from .ui.pdf_to_office import PdfToOfficeWindow
from .ui.windowing import center_window, make_modal

NAVY = "#193B66"
BLUE = "#2368AF"
BACKGROUND = "#F0F4F9"


class Application(tk.Tk):
    """Cross-platform shell. Feature panels are integrated incrementally."""

    MODULES = (
        ("PDF vers Office", "Conversion PDF vers Word et extraction de tableaux Excel."),
        ("Documents vers PDF", "Documents bureautiques et images, individuellement ou par lots."),
        ("Organiser les PDF", "Fusion, extraction, réorganisation et rotation des pages."),
        ("Habillage PDF", "Filigranes, en-têtes et pieds de page avec aperçu."),
    )

    def __init__(self) -> None:
        set_language(load_language(), save=False)
        super().__init__(className="LouCodiPdfConverter")
        self.title(f"PDF Converter – Lou Còdi | v{__version__}")
        self.geometry("1100x720")
        self.minsize(850, 600)
        self.configure(bg=BACKGROUND)
        center_window(self, 1100, 720)
        self._configure_styles()
        self._build()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background="white")
        style.configure("Title.TLabel", background="white", foreground=NAVY, font=("Sans", 15, "bold"))
        style.configure("Body.TLabel", background="white", foreground="#597089", font=("Sans", 10))
        style.configure("Primary.TButton", background=BLUE, foreground="white", padding=(16, 10))

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, height=95)
        header.pack(fill="x")
        header.pack_propagate(False)
        logo_path = Path(__file__).with_name("assets") / "croix-lou-codi.png"
        self.app_icon = tk.PhotoImage(file=str(logo_path))
        self.iconphoto(True, self.app_icon)
        self.brand_logo = self.app_icon.subsample(15, 15)
        tk.Label(header, image=self.brand_logo, bg=NAVY, borderwidth=0).pack(
            side="left", padx=(22, 15), pady=7
        )
        titles = tk.Frame(header, bg=NAVY)
        titles.pack(side="left", pady=20)
        tk.Label(titles, text="PDF Converter", bg=NAVY, fg="white", font=("Sans", 21, "bold")).pack(anchor="w")
        tk.Label(titles, text="LOU CÒDI  •  TRAITEMENT LOCAL", bg=NAVY, fg="#CBDFF5", font=("Sans", 9)).pack(anchor="w")
        tk.Button(header, text="Soutenir Lou Còdi ♥", command=lambda: webbrowser.open("https://loucodi.fr"), bg="#28507D", fg="white", relief="flat", padx=16, pady=8).pack(side="right", padx=24)
        self.language_name = tk.StringVar(value=LANGUAGES[get_language()])
        language_selector = ttk.Combobox(
            header,
            textvariable=self.language_name,
            values=tuple(LANGUAGES.values()),
            state="readonly",
            width=12,
        )
        language_selector.pack(side="right", padx=(8, 0), pady=31)
        language_selector.bind("<<ComboboxSelected>>", self._change_language)
        tk.Label(header, text="Langue", bg=NAVY, fg="white", font=("Sans", 9)).pack(
            side="right", pady=31
        )

        content = ttk.Frame(self, style="App.TFrame", padding=24)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="Que souhaitez-vous faire ?", background=BACKGROUND, foreground=NAVY, font=("Sans", 19, "bold")).pack(anchor="w", pady=(0, 16))
        grid = ttk.Frame(content, style="App.TFrame")
        grid.pack(fill="both", expand=True)
        for index, (title, description) in enumerate(self.MODULES):
            card = ttk.Frame(grid, style="Card.TFrame", padding=22)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=8, pady=8)
            ttk.Label(card, text=f"{index + 1:02d}  {title}", style="Title.TLabel").pack(anchor="w")
            ttk.Label(card, text=description, style="Body.TLabel", wraplength=390).pack(anchor="w", pady=(12, 18))
            ttk.Button(card, text="Ouvrir le module", style="Primary.TButton", command=lambda name=title: self._open_module(name)).pack(anchor="w")
        grid.columnconfigure((0, 1), weight=1, uniform="modules")
        grid.rowconfigure((0, 1), weight=1, uniform="modules")
        tk.Label(self, text=f"Lou Còdi  •  v{__version__}  •  {tr('Aucun document transmis sur Internet')}", bg=BACKGROUND, fg="#597089", font=("Sans", 9)).pack(anchor="e", padx=24, pady=(0, 12))
        translate_widget_tree(self)

    def _change_language(self, _event: tk.Event[tk.Misc]) -> None:
        selected = next(
            (code for code, name in LANGUAGES.items() if name == self.language_name.get()),
            "fr",
        )
        set_language(selected)
        for child in self.winfo_children():
            child.destroy()
        self._build()

    def _open_module(self, name: str) -> None:
        if name == "PDF vers Office":
            window = PdfToOfficeWindow(self)
            self.wait_window(window)
            return
        if name == "Documents vers PDF":
            window = DocumentsToPdfWindow(self)
            self.wait_window(window)
            return
        if name == "Organiser les PDF":
            window = OrganizePdfWindow(self)
            self.wait_window(window)
            return
        if name == "Habillage PDF":
            window = DecoratePdfWindow(self)
            self.wait_window(window)
            return
        dialog = tk.Toplevel(self, class_="LouCodiPdfConverter")
        dialog.title(f"{name} — PDF Converter Lou Còdi")
        dialog.geometry("680x260")
        dialog.configure(bg=BACKGROUND)
        tk.Label(dialog, text=name, bg=BACKGROUND, fg=NAVY, font=("Sans", 18, "bold")).pack(pady=(35, 15))
        tk.Label(dialog, text="Le moteur local de ce module est prêt. L’interface détaillée sera intégrée au prochain lot.", bg=BACKGROUND, fg="#597089", wraplength=560, justify="center").pack()
        ttk.Button(dialog, text="Fermer", command=dialog.destroy).pack(pady=28)
        make_modal(dialog, self)
        self.wait_window(dialog)


def main() -> None:
    Application().mainloop()


if __name__ == "__main__":
    main()
