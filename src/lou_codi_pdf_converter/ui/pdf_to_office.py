from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk

from ..i18n import tr, translate_widget_tree
from ..paths import collision_free_target, module_output_directory
from ..services.pdf_inspection import PdfPasswordRequired, inspect_pdf
from ..services.pdf_to_office import convert_pdf_to_docx, convert_pdf_to_xlsx
from ..system import open_path
from .dialogs import show_success
from .directory_picker import choose_directory
from .pdf_picker import choose_pdfs
from .windowing import make_modal, maximize_window

NAVY = "#193B66"
BACKGROUND = "#F0F4F9"
MUTED = "#597089"


def _docx_progress_fraction(stage: str, current: int | None, total: int | None) -> float:
    ratio = (current / total) if current is not None and total else 0.0
    if stage == "Ouverture du PDF":
        return 0.02
    if stage == "Analyse de la mise en page":
        return 0.08
    if stage == "Lecture des pages":
        return 0.10 + 0.65 * ratio
    if stage == "Création du document Word":
        return 0.75 + 0.25 * ratio
    return 0.01


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    target: Path | None
    error: str | None


class PdfToOfficeWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title("PDF vers Office — Lou Còdi Workshop")
        self.geometry("960x680")
        self.minsize(760, 540)
        self.configure(bg=BACKGROUND)
        maximize_window(self)
        self.files: list[Path] = []
        self.generated: list[Path] = []
        self.output_by_source: dict[Path, Path] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.conversion_started_at: float | None = None
        self.last_progress_at: float | None = None
        self.mode = tk.StringVar(value="docx")
        self.destination = tk.StringVar(value=str(module_output_directory("PDF vers Office")))
        self.password = tk.StringVar()
        self._build()
        translate_widget_tree(self)
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self.after(100, self._poll)
        make_modal(self, parent)

    def _build(self) -> None:
        app_icon = getattr(self._root(), "app_icon", None)
        if app_icon is not None:
            self.iconphoto(False, app_icon)
        header = tk.Frame(self, bg=NAVY, padx=22, pady=12)
        header.pack(fill="x")
        if app_icon is not None:
            self.workspace_logo = app_icon.subsample(17, 17)
            tk.Label(header, image=self.workspace_logo, bg=NAVY, borderwidth=0).pack(side="left", padx=(0, 14))
        titles = tk.Frame(header, bg=NAVY)
        titles.pack(side="left")
        tk.Label(titles, text="PDF vers Office", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(anchor="w")
        tk.Label(titles, text="Conversion locale par lots", bg=NAVY, fg="#CBDFF5", font=("Sans", 10)).pack(anchor="w")

        body = ttk.Frame(self, style="App.TFrame", padding=22)
        body.pack(fill="both", expand=True)
        format_row = ttk.Frame(body, style="Card.TFrame", padding=15)
        format_row.pack(fill="x", pady=(0, 12))
        ttk.Label(format_row, text="Format :", style="Title.TLabel").pack(side="left")
        ttk.Radiobutton(format_row, text="Word (.docx)", variable=self.mode, value="docx").pack(side="left", padx=(20, 12))
        ttk.Radiobutton(format_row, text="Excel (.xlsx) — tableaux", variable=self.mode, value="xlsx").pack(side="left")
        ttk.Button(format_row, text="Ajouter des PDF…", command=self._add_files).pack(side="right")

        table_frame = ttk.Frame(body, style="Card.TFrame", padding=15)
        table_frame.pack(fill="both", expand=True, pady=(0, 12))
        self.tree = ttk.Treeview(table_frame, columns=("name", "pages", "type", "status"), show="headings", selectmode="extended")
        for column, label, width in (
            ("name", "Document", 360),
            ("pages", "Pages", 70),
            ("type", "Analyse", 180),
            ("status", "État", 210),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=60, stretch=column in {"name", "status"})
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._open_selected_result)
        scroll = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        controls = ttk.Frame(body, style="App.TFrame")
        controls.pack(fill="x", pady=(0, 12))
        ttk.Button(controls, text="Retirer", command=self._remove_selected).pack(side="left")
        ttk.Button(controls, text="Tout effacer", command=self._clear).pack(side="left", padx=8)
        ttk.Label(controls, text="Mot de passe PDF :", background=BACKGROUND).pack(side="left", padx=(20, 5))
        ttk.Entry(controls, textvariable=self.password, show="•", width=20).pack(side="left")

        destination = ttk.Frame(body, style="Card.TFrame", padding=15)
        destination.pack(fill="x", pady=(0, 12))
        ttk.Label(destination, text="Destination", style="Title.TLabel").pack(side="left")
        ttk.Entry(destination, textvariable=self.destination).pack(side="left", fill="x", expand=True, padx=14)
        ttk.Button(destination, text="Parcourir…", command=self._choose_destination).pack(side="left")

        actions = ttk.Frame(body, style="App.TFrame")
        actions.pack(fill="x")
        self.convert_button = ttk.Button(actions, text="Convertir", style="Primary.TButton", command=self._start)
        self.convert_button.pack(side="left")
        self.open_button = ttk.Button(actions, text="Ouvrir les résultats", command=self._open_results, state="disabled")
        self.open_button.pack(side="left", padx=10)
        self.status = ttk.Label(actions, text="Prêt.", background=BACKGROUND, foreground=MUTED)
        self.status.pack(side="right")
        self.progress = ttk.Progressbar(body, maximum=100)
        self.progress.pack(fill="x", pady=(13, 0))

    def _add_files(self) -> None:
        for path in choose_pdfs(self):
            if path in self.files:
                continue
            self.files.append(path)
            item = self.tree.insert("", "end", iid=str(path), values=(path.name, "…", "Analyse…", "En attente"))
            try:
                inspection = inspect_pdf(path, self.password.get() or None)
                kind = "PDF scanné probable" if inspection.scanned_likely else "Texte détecté"
                self.tree.item(item, values=(path.name, inspection.page_count, kind, "En attente"))
            except PdfPasswordRequired:
                self.tree.item(item, values=(path.name, "?", "PDF chiffré", "Mot de passe requis"))
            except Exception as exc:  # noqa: BLE001 - afficher toute erreur de fichier dans l’interface
                self.tree.item(item, values=(path.name, "?", "Illisible", str(exc)))

    def _remove_selected(self) -> None:
        for item in self.tree.selection():
            path = Path(item)
            if path in self.files:
                self.files.remove(path)
            self.tree.delete(item)

    def _clear(self) -> None:
        if self.running:
            return
        self.files.clear()
        self.tree.delete(*self.tree.get_children())

    def _choose_destination(self) -> None:
        selected = choose_directory(self, Path(self.destination.get()).expanduser())
        if selected:
            self.destination.set(str(selected))

    def _start(self) -> None:
        if self.running:
            return
        if not self.files:
            messagebox.showwarning("Aucun PDF", "Ajoutez au moins un document PDF.", parent=self)
            return
        destination = Path(self.destination.get()).expanduser()
        if not destination.is_dir():
            messagebox.showerror("Dossier introuvable", "Choisissez un dossier de destination existant.", parent=self)
            return
        self.running = True
        self.conversion_started_at = time.monotonic()
        self.last_progress_at = self.conversion_started_at
        self.generated.clear()
        self.output_by_source.clear()
        self.open_button.configure(state="disabled")
        self.convert_button.configure(state="disabled")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        threading.Thread(
            target=self._worker,
            args=(list(self.files), destination, self.mode.get(), self.password.get() or None),
            daemon=True,
        ).start()

    def _worker(self, files: list[Path], destination: Path, mode: str, password: str | None) -> None:
        results: list[ConversionResult] = []
        for position, source in enumerate(files, 1):
            self.events.put(("status", f"Conversion {position}/{len(files)} : {source.name}"))
            self.events.put(("row", (source, "Conversion…")))
            target = collision_free_target(destination, source.stem, f".{mode}")
            try:
                inspection = inspect_pdf(source, password)
                if inspection.scanned_likely:
                    raise ValueError("PDF scanné probable : OCR local non encore disponible.")
                if mode == "docx":
                    def report_progress(stage: str, current: int | None, total: int | None) -> None:
                        if current is not None and total:
                            detail = f"{stage} — page {current}/{total}"
                        else:
                            detail = stage
                        self.events.put(("progress", (position, len(files), detail, current, total)))

                    convert_pdf_to_docx(source, target, password, report_progress)
                else:
                    convert_pdf_to_xlsx(source, target, password)
                results.append(ConversionResult(source, target, None))
                self.events.put(("converted", (source, target)))
                self.events.put(("row", (source, f"Terminé → {target.name}")))
            except Exception as exc:  # noqa: BLE001 - isoler chaque conversion du lot
                if target.exists():
                    target.unlink()
                results.append(ConversionResult(source, None, str(exc)))
                self.events.put(("row", (source, f"Échec : {exc}")))
        self.events.put(("finished", results))

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.configure(text=tr(str(value)))
                elif kind == "row":
                    source, row_status = value  # type: ignore[misc]
                    current = self.tree.item(str(source), "values")
                    if current:
                        self.tree.item(str(source), values=(*current[:3], row_status))
                elif kind == "converted":
                    source, target = value  # type: ignore[misc]
                    self.output_by_source[source] = target
                elif kind == "progress":
                    file_position, file_count, detail, current, total = value  # type: ignore[misc]
                    self.last_progress_at = time.monotonic()
                    file_fraction = _docx_progress_fraction(detail.split(" — ", 1)[0], current, total)
                    overall = ((file_position - 1) + file_fraction) / file_count * 100
                    self.progress.configure(value=max(1, min(99, overall)))
                    self.status.configure(
                        text=tr(f"Conversion {file_position}/{file_count} : {detail}")
                    )
                elif kind == "finished":
                    self._finish(value)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        if self.running and self.last_progress_at is not None:
            stalled_for = time.monotonic() - self.last_progress_at
            if stalled_for >= 30:
                elapsed = int(time.monotonic() - (self.conversion_started_at or time.monotonic()))
                self.status.configure(
                    text=tr(
                        f"Conversion toujours en cours ({elapsed} s) — ce PDF est complexe ou pose un problème."
                    )
                )
        if self.winfo_exists():
            self.after(100, self._poll)

    def _finish(self, results: list[ConversionResult]) -> None:
        self.running = False
        self.conversion_started_at = None
        self.last_progress_at = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.convert_button.configure(state="normal")
        self.generated = [result.target for result in results if result.target is not None]
        failures = [result for result in results if result.error]
        self.open_button.configure(state="normal" if self.generated else "disabled")
        self.status.configure(
            text=tr(
                f"Terminé : {len(self.generated)} réussite(s), {len(failures)} échec(s)."
            )
        )
        if failures:
            details = "\n".join(f"• {result.source.name} : {result.error}" for result in failures[:8])
            messagebox.showwarning("Conversion terminée", details, parent=self)
        else:
            target = self.generated[0] if len(self.generated) == 1 else self.generated[0].parent
            action_label = "Ouvrir le document" if len(self.generated) == 1 else "Ouvrir le dossier"
            show_success(
                self,
                "Conversion terminée",
                f"{len(self.generated)} document(s) créé(s) dans :\n\n"
                f"{self.generated[0].parent}",
                action_label=action_label,
                action=lambda: open_path(target),
            )

    def _open_results(self) -> None:
        if len(self.generated) == 1:
            open_path(self.generated[0])
        elif self.generated:
            open_path(self.generated[0].parent)

    def _open_selected_result(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.tree.selection()
        if len(selection) != 1:
            return
        target = self.output_by_source.get(Path(selection[0]))
        if target and target.is_file():
            self._open_with_feedback(target)

    def _open_with_feedback(self, target: Path) -> None:
        previous_status = self.status.cget("text")
        self.configure(cursor="watch")
        self.status.configure(text=tr(f"Ouverture de {target.name}…"))
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        self.update_idletasks()
        try:
            open_path(target)
        except OSError as exc:
            messagebox.showerror("Ouverture impossible", str(exc), parent=self)

        def restore() -> None:
            if not self.winfo_exists():
                return
            self.progress.stop()
            self.progress.configure(mode="determinate", value=100)
            self.status.configure(text=previous_status)
            self.configure(cursor="")

        self.after(900, restore)

    def _request_close(self) -> None:
        if self.running and not messagebox.askyesno(
            "Conversion en cours",
            "Une conversion est encore en cours. Fermer cette fenêtre masquera son suivi.\n\n"
            "Voulez-vous vraiment fermer ?",
            parent=self,
        ):
            return
        self.destroy()
