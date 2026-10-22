from __future__ import annotations

import sys
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from . import __version__
from .i18n import (
    LANGUAGES,
    get_language,
    install_messagebox_translations,
    load_language,
    set_language,
    translate_widget_tree,
)
from .licensing import activate, is_activated, license_state, request_free_license, service_configured
from .paths import initialize_workshop_directories
from .services.local_database import initialize_database
from .support import SUPPORT_URL, mark_support_reminder_shown, mark_welcome_seen, register_launch
from .telemetry import analytics_consent, set_analytics_consent, track_event
from .ui.about_dialog import show_about
from .ui.cutting_stock import CuttingStockWindow
from .ui.decorate_pdf import DecoratePdfWindow
from .ui.dialogs import install_branded_messageboxes
from .ui.document_editor import DocumentEditorWindow
from .ui.documents_to_pdf import DocumentsToPdfWindow
from .ui.organize_pdf import OrganizePdfWindow
from .ui.pdf_to_office import PdfToOfficeWindow
from .ui.support_dialog import show_support_reminder, show_welcome
from .ui.windowing import center_window, make_modal, maximize_window

NAVY = "#193B66"
BLUE = "#2368AF"
BACKGROUND = "#F0F4F9"
SUPPORT_GOLD = "#F4B942"
SUPPORT_DARK = "#713B00"
LOCKED = "#8A6D1D"


@dataclass(frozen=True)
class WorkshopModule:
    module_id: str
    title: str
    description: str
    installed: bool = True
    entitled: bool = True
    coming_soon: bool = False

    @property
    def available(self) -> bool:
        return self.installed and self.entitled and not self.coming_soon


class Application(tk.Tk):
    """Modular cross-platform launcher for the Lou Còdi tools."""

    MODULES = (
        WorkshopModule(
            "pdf_studio",
            "PDF Studio",
            "Convertir, organiser et enrichir vos documents PDF.",
        ),
        WorkshopModule(
            "document_studio",
            "Document Studio",
            "Créer et mettre en page des documents, dessins et schémas.",
        ),
        WorkshopModule(
            "cutting_optimization",
            "Optimisation de découpe",
            "Disposer les pièces, calculer les coupes et réduire les chutes.",
        ),
        WorkshopModule(
            "practical_calculators",
            "Calculateurs pratiques",
            "Regrouper les petits calculs utiles à l’atelier.",
            coming_soon=True,
        ),
        WorkshopModule(
            "home_automation",
            "Domotique et automatismes",
            "Préparer des installations, commandes et automatismes simples.",
            coming_soon=True,
        ),
        WorkshopModule(
            "workshop_memo",
            "Mémo d’atelier",
            "Lexique, conversions, formules et références techniques.",
            coming_soon=True,
        ),
        WorkshopModule(
            "gcode_workshop",
            "G-code Workshop",
            "Préparer les trajectoires d’outil et les programmes d’usinage.",
            coming_soon=True,
        ),
    )

    PDF_MODULES = (
        WorkshopModule("pdf_to_office", "PDF vers Office", "Conversion vers Word et extraction de tableaux Excel."),
        WorkshopModule("documents_to_pdf", "Documents vers PDF", "Documents bureautiques et images, seuls ou par lots."),
        WorkshopModule("organize_pdf", "Organiser les PDF", "Fusion, extraction, réorganisation et rotation des pages."),
        WorkshopModule("decorate_pdf", "Habillage PDF", "Filigranes, en-têtes et pieds de page avec aperçu."),
    )

    def __init__(self, project_path: Path | None = None) -> None:
        set_language(load_language(), save=False)
        install_messagebox_translations()
        super().__init__(className="Loucodiworkshop")
        self.title(f"Lou Còdi Workshop | v{__version__}")
        self.geometry("1265x830")
        self.minsize(1050, 700)
        self.configure(bg=BACKGROUND)
        self.local_database = initialize_database()
        self.workshop_directory = initialize_workshop_directories()
        center_window(self, 1265, 830)
        self._configure_styles()
        install_branded_messageboxes()
        self._build()
        if sys.platform == "darwin":
            self.createcommand("::tk::mac::OpenDocument", self._mac_open_document)
        self.launch_state = register_launch()
        track_event("workshop", "open")
        self.after(350, self._show_launch_information)
        if project_path is not None:
            self.after(50, lambda: self._open_document_project(project_path))

    def _open_document_project(self, project_path: Path) -> None:
        try:
            window = DocumentEditorWindow(self, project_path=project_path)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            messagebox.showerror("Document illisible", str(exc), parent=self)
            return
        self._replace_workspace(self, window, force_maximized=True)

    def _mac_open_document(self, *paths: str) -> None:
        if paths:
            candidate = Path(paths[0]).expanduser()
            if candidate.suffix.lower() in {".code", ".cod", ".loucodi-document"}:
                self._open_document_project(candidate.resolve())

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
        tk.Label(titles, text="Lou Còdi Workshop", bg=NAVY, fg="white", font=("Sans", 21, "bold")).pack(anchor="w")
        tk.Label(titles, text="DES OUTILS PRATIQUES, EN LOCAL, POUR CRÉER ET FABRIQUER", bg=NAVY, fg="#CBDFF5", font=("Sans", 9)).pack(anchor="w")
        tk.Button(header, text="Soutenir Lou Còdi ♥", command=lambda: webbrowser.open(SUPPORT_URL), bg="#28507D", fg="white", relief="flat", padx=16, pady=8).pack(side="right", padx=(8, 24))
        tk.Button(header, text="À propos", command=lambda: show_about(self), bg="#28507D", fg="white", relief="flat", padx=14, pady=8).pack(side="right", padx=4)
        tk.Button(header, text="Confidentialité", command=self._analytics_dialog, bg="#28507D", fg="white", relief="flat", padx=12, pady=8).pack(side="right", padx=4)
        tk.Button(header, text="Licence", command=self._license_dialog, bg="#28507D", fg="white", relief="flat", padx=12, pady=8).pack(side="right", padx=4)
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
        visible_modules = [module for module in self.MODULES if module.installed]
        for index, module in enumerate(visible_modules):
            card = ttk.Frame(grid, style="Card.TFrame", padding=16)
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
            ttk.Label(card, text=f"{index + 1:02d}  {module.title}", style="Title.TLabel").pack(anchor="w")
            ttk.Label(card, text=module.description, style="Body.TLabel", wraplength=335).pack(anchor="w", pady=(8, 12))
            if module.coming_soon:
                ttk.Label(card, text="Bientôt disponible", background="white", foreground=LOCKED, font=("Sans", 10, "bold")).pack(anchor="w")
            elif not module.entitled:
                ttk.Button(card, text="Découvrir le module", command=lambda item=module: self._show_locked_module(item)).pack(anchor="w")
            else:
                ttk.Button(card, text="Ouvrir le module", style="Primary.TButton", command=lambda item=module: self._open_module(item.module_id)).pack(anchor="w")
        self._build_support_card(grid, len(visible_modules), "Soutenir Lou Còdi", "Les outils PDF restent gratuits. Votre soutien aide à maintenir le projet et à développer les prochains modules.")
        grid.columnconfigure((0, 1, 2), weight=1, uniform="modules")
        for row in range((len(visible_modules) + 3) // 3):
            grid.rowconfigure(row, weight=1, uniform="modules")
        tk.Label(self, text=f"Lou Còdi  •  v{__version__}  •  Aucun document transmis sur Internet", bg=BACKGROUND, fg="#597089", font=("Sans", 9)).pack(anchor="e", padx=24, pady=(0, 12))
        translate_widget_tree(self)

    def _build_support_card(
        self,
        grid: ttk.Frame,
        index: int,
        title: str,
        description: str,
    ) -> None:
        card = tk.Frame(grid, bg="#FFF1C9", padx=18, pady=16, highlightthickness=2, highlightbackground=SUPPORT_GOLD)
        card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
        tk.Label(
            card,
            text=f"♥  {title}",
            bg="#FFF1C9",
            fg=SUPPORT_DARK,
            font=("Sans", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            card,
            text=description,
            bg="#FFF1C9",
            fg="#714F25",
            font=("Sans", 10),
            justify="left",
            wraplength=335,
        ).pack(anchor="w", pady=(8, 12))
        tk.Button(
            card,
            text="Découvrir et soutenir ♥",
            command=lambda: webbrowser.open(SUPPORT_URL),
            bg="#D66A1F",
            fg="white",
            activebackground="#B95013",
            activeforeground="white",
            relief="flat",
            font=("Sans", 10, "bold"),
            padx=14,
            pady=8,
        ).pack(anchor="w")

    def _change_language(self, _event: tk.Event[tk.Misc]) -> None:
        selected = next(
            (code for code, name in LANGUAGES.items() if name == self.language_name.get()),
            "fr",
        )
        set_language(selected)
        for child in self.winfo_children():
            child.destroy()
        self._build()

    def _show_launch_information(self) -> None:
        if self.launch_state.show_welcome:
            show_welcome(self)
            mark_welcome_seen()
        elif self.launch_state.show_support_reminder:
            disabled = show_support_reminder(self)
            mark_support_reminder_shown(
                self.launch_state.launch_count,
                disable_future_reminders=disabled,
            )
        if analytics_consent() is None:
            self._analytics_dialog(first_choice=True)

    def _analytics_dialog(self, *, first_choice: bool = False) -> None:
        current = analytics_consent()
        message = (
            "Aider à améliorer Lou Còdi Workshop en envoyant des statistiques anonymes ?\n\n"
            "Sont envoyés : module utilisé, réussite ou erreur générale, version et système. "
            "Le serveur pourra agréger le pays et la grande région.\n\n"
            "Ne sont jamais envoyés automatiquement : documents, textes, noms ou chemins de fichiers.\n\n"
            "Vous pourrez modifier ce choix avec le bouton Confidentialité."
        )
        enabled = messagebox.askyesno(
            "Statistiques anonymes",
            message,
            parent=self,
            default="no" if first_choice else ("yes" if current else "no"),
        )
        set_analytics_consent(enabled)
        if not first_choice:
            messagebox.showinfo(
                "Confidentialité",
                "Statistiques anonymes activées." if enabled else "Statistiques anonymes désactivées et file locale supprimée.",
                parent=self,
            )

    def _license_dialog(self) -> None:
        dialog = tk.Toplevel(self, class_="Loucodiworkshop")
        dialog.title("Licence gratuite — Lou Còdi Workshop")
        dialog.configure(bg=BACKGROUND, padx=24, pady=22)
        dialog.resizable(False, False)
        tk.Label(dialog, text="Licence gratuite", bg=BACKGROUND, fg=NAVY, font=("Sans", 18, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(dialog, text="Une même licence peut activer jusqu’à trois ordinateurs.", bg=BACKGROUND, fg="#597089").grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 18))
        tk.Label(dialog, text="Adresse électronique", bg=BACKGROUND, fg=NAVY).grid(row=2, column=0, sticky="w", pady=5)
        email = tk.StringVar(value=str(license_state().get("email", "")))
        ttk.Entry(dialog, textvariable=email, width=44).grid(row=2, column=1, sticky="ew", pady=5)
        tk.Label(dialog, text="Clé reçue", bg=BACKGROUND, fg=NAVY).grid(row=3, column=0, sticky="w", pady=5)
        key = tk.StringVar(value=str(license_state().get("license_key", "")))
        ttk.Entry(dialog, textvariable=key, width=44).grid(row=3, column=1, sticky="ew", pady=5)
        initial_status = "Licence activée sur cet ordinateur." if is_activated() else "Licence non activée."
        if not service_configured():
            initial_status = "Interface prête : le service sera actif après le déploiement Apps Script."
        status = tk.StringVar(value=initial_status)
        tk.Label(dialog, textvariable=status, bg=BACKGROUND, fg="#157347", wraplength=500, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 8))

        def request() -> None:
            try:
                status.set(request_free_license(email.get()))
            except RuntimeError as exc:
                status.set(str(exc))

        def validate() -> None:
            try:
                state = activate(email.get(), key.get())
                status.set(f"Licence activée — {state['slots_used']} poste(s) utilisé(s) sur 3.")
            except RuntimeError as exc:
                status.set(str(exc))

        actions = ttk.Frame(dialog, style="App.TFrame")
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(actions, text="Recevoir une licence", command=request).pack(side="left", padx=4)
        ttk.Button(actions, text="Activer", style="Primary.TButton", command=validate).pack(side="left", padx=4)
        ttk.Button(actions, text="Fermer", command=dialog.destroy).pack(side="left", padx=4)
        dialog.update_idletasks()
        center_window(dialog, max(620, dialog.winfo_reqwidth()), max(300, dialog.winfo_reqheight()))
        make_modal(dialog, self)

    def _open_module(self, module_id: str) -> None:
        if getattr(self, "_workspace_opening", False):
            return
        self._workspace_opening = True
        try:
            self._open_module_now(module_id)
        finally:
            self._workspace_opening = False

    def _open_module_now(self, module_id: str) -> None:
        track_event(module_id, "open")
        if module_id == "pdf_studio":
            self._open_pdf_studio()
            return
        if module_id == "pdf_to_office":
            window = PdfToOfficeWindow(self)
            self._replace_workspace(self, window)
            return
        if module_id == "documents_to_pdf":
            window = DocumentsToPdfWindow(self)
            self._replace_workspace(self, window)
            return
        if module_id == "organize_pdf":
            window = OrganizePdfWindow(self)
            self._replace_workspace(self, window)
            return
        if module_id == "decorate_pdf":
            window = DecoratePdfWindow(self)
            self._replace_workspace(self, window)
            return
        if module_id == "document_studio":
            window = DocumentEditorWindow(self)
            self._replace_workspace(self, window, force_maximized=True)
            return
        if module_id == "cutting_optimization":
            window = CuttingStockWindow(self)
            self._replace_workspace(self, window, force_maximized=True)
            return
        module = next((item for item in self.MODULES if item.module_id == module_id), None)
        name = module.title if module else module_id
        dialog = tk.Toplevel(self, class_="Loucodiworkshop")
        dialog.title(f"{name} — Lou Còdi Workshop")
        dialog.geometry("680x260")
        dialog.configure(bg=BACKGROUND)
        tk.Label(dialog, text=name, bg=BACKGROUND, fg=NAVY, font=("Sans", 18, "bold")).pack(pady=(35, 15))
        tk.Label(dialog, text="Le moteur local de ce module est prêt. L’interface détaillée sera intégrée au prochain lot.", bg=BACKGROUND, fg="#597089", wraplength=560, justify="center").pack()
        ttk.Button(dialog, text="Fermer", command=dialog.destroy).pack(pady=28)
        make_modal(dialog, self)
        self._replace_workspace(self, dialog)

    def _open_pdf_studio(self) -> None:
        dialog = tk.Toplevel(self, class_="Loucodiworkshop")
        dialog.title("PDF Studio — Lou Còdi Workshop")
        dialog.geometry("1050x610")
        dialog.minsize(860, 520)
        dialog.configure(bg=BACKGROUND)
        header = tk.Frame(dialog, bg=NAVY, padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(header, text="PDF Studio", bg=NAVY, fg="white", font=("Sans", 22, "bold")).pack(anchor="w")
        tk.Label(header, text="CONVERTIR, ORGANISER ET ENRICHIR VOS PDF — EN LOCAL", bg=NAVY, fg="#CBDFF5", font=("Sans", 9)).pack(anchor="w")
        body = ttk.Frame(dialog, style="App.TFrame", padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Que souhaitez-vous faire ?", background=BACKGROUND, foreground=NAVY, font=("Sans", 19, "bold")).pack(anchor="w", pady=(0, 16))
        grid = ttk.Frame(body, style="App.TFrame")
        grid.pack(fill="both", expand=True)
        for index, module in enumerate(self.PDF_MODULES):
            card = ttk.Frame(grid, style="Card.TFrame", padding=18)
            card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=7, pady=7)
            ttk.Label(card, text=f"{index + 1:02d}  {module.title}", style="Title.TLabel").pack(anchor="w")
            ttk.Label(card, text=module.description, style="Body.TLabel", wraplength=390).pack(anchor="w", pady=(9, 14))
            ttk.Button(card, text="Ouvrir le module", style="Primary.TButton", command=lambda item=module, parent=dialog: self._open_child_module(parent, item.module_id)).pack(anchor="w")
        grid.columnconfigure((0, 1), weight=1, uniform="pdf-modules")
        grid.rowconfigure((0, 1), weight=1, uniform="pdf-modules")
        ttk.Button(body, text="Fermer", command=dialog.destroy).pack(anchor="e", pady=(12, 0))
        make_modal(dialog, self)
        self._replace_workspace(self, dialog)

    def _open_child_module(self, parent: tk.Toplevel, module_id: str) -> None:
        if getattr(parent, "_child_workspace_open", False):
            return
        parent._child_workspace_open = True  # type: ignore[attr-defined]
        factories = {
            "pdf_to_office": PdfToOfficeWindow,
            "documents_to_pdf": DocumentsToPdfWindow,
            "organize_pdf": OrganizePdfWindow,
            "decorate_pdf": DecoratePdfWindow,
        }
        try:
            factory = factories[module_id]
            window = factory(parent)
            parent.wait_window(window)
        finally:
            parent._child_workspace_open = False  # type: ignore[attr-defined]

    def _replace_workspace(
        self,
        previous: tk.Tk | tk.Toplevel,
        window: tk.Toplevel,
        *,
        force_maximized: bool = False,
    ) -> None:
        """Show one workspace at a time and restore the previous one on close."""
        previous.update_idletasks()
        previous_geometry = previous.geometry()
        previous_state = previous.state()
        # A transient window is hidden automatically when its parent is withdrawn on
        # Linux. Promote the module to a normal top-level workspace. WM_CLASS already
        # groups it with the launcher; keeping the withdrawn root as WM group leader
        # makes some desktops lose the running indicator for maximized workspaces.
        try:
            window.tk.call("wm", "transient", window._w, "")
            window.tk.call("wm", "group", window._w, "")
        except tk.TclError:
            pass
        try:
            window.grab_release()
        except tk.TclError:
            pass
        try:
            window.iconphoto(True, self.app_icon)
        except tk.TclError:
            pass
        if force_maximized or previous_state == "zoomed":
            maximize_window(window)
        else:
            window.geometry(previous_geometry)
        window.deiconify()
        window.update_idletasks()
        # Remove the previous workspace from the task switcher. Keeping the launcher
        # iconified makes Linux restore it instead of the module actually in use.
        previous.withdraw()
        window.lift()
        window.focus_force()
        previous.wait_window(window)
        if previous.winfo_exists():
            previous.deiconify()
            if previous_state == "zoomed":
                maximize_window(previous)
            else:
                previous.geometry(previous_geometry)
            previous.lift()
            previous.focus_force()

    def _show_locked_module(self, module: WorkshopModule) -> None:
        messagebox.showinfo(
            "Module optionnel",
            f"{module.title} est disponible comme module optionnel.\n\n"
            "Une future gestion des licences permettra de l’activer ici.",
            parent=self,
        )


def main() -> None:
    project_path = None
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1]).expanduser()
        if candidate.suffix.lower() in {".code", ".cod", ".loucodi-document"}:
            project_path = candidate.resolve()
    Application(project_path=project_path).mainloop()


if __name__ == "__main__":
    main()
