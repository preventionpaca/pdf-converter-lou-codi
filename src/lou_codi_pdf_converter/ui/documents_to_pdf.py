from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..paths import collision_free_target, downloads_directory
from ..services.documents_to_pdf import IMAGE_SUFFIXES, OFFICE_SUFFIXES, convert_document_to_pdf
from ..services.pdf_organizer import merge_pdfs
from ..system import open_path
from .dialogs import show_success
from .directory_picker import choose_directory
from .pdf_picker import choose_documents
from .windowing import make_modal, maximize_window

BACKGROUND = "#F0F4F9"
NAVY = "#193B66"
MUTED = "#597089"
SUPPORTED_SUFFIXES = OFFICE_SUFFIXES | IMAGE_SUFFIXES


class DocumentsToPdfWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, class_="LouCodiPdfConverter")
        self.title("Documents vers PDF — PDF Converter Lou Còdi")
        self.minsize(850, 600)
        self.configure(bg=BACKGROUND)
        maximize_window(self)
        self.files: list[Path] = []
        self.generated: list[Path] = []
        self.output_by_source: dict[Path, Path] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.running = False
        self.destination = tk.StringVar(value=str(downloads_directory()))
        self.merge_results = tk.BooleanVar(value=False)
        self._build()
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
        tk.Label(titles, text="Documents vers PDF", bg=NAVY, fg="white", font=("Sans", 19, "bold")).pack(anchor="w")
        tk.Label(
            titles,
            text="Documents bureautiques et images — traitement local par lots",
            bg=NAVY,
            fg="#CBDFF5",
            font=("Sans", 10),
        ).pack(anchor="w")

        body = ttk.Frame(self, style="App.TFrame", padding=22)
        body.pack(fill="both", expand=True)
        toolbar = ttk.Frame(body, style="Card.TFrame", padding=15)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, text="Fichiers à convertir", style="Title.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Ajouter des documents…", command=self._add_files).pack(side="right")

        table_frame = ttk.Frame(body, style="Card.TFrame", padding=15)
        table_frame.pack(fill="both", expand=True, pady=(0, 12))
        self.tree = ttk.Treeview(
            table_frame,
            columns=("name", "format", "folder", "status"),
            show="headings",
            selectmode="extended",
        )
        for column, label, width in (
            ("name", "Document", 380),
            ("format", "Format", 100),
            ("folder", "Dossier", 320),
            ("status", "État", 260),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=70, stretch=column != "format")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._open_selected_result)
        scrollbar = ttk.Scrollbar(table_frame, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        options = ttk.Frame(body, style="App.TFrame")
        options.pack(fill="x", pady=(0, 12))
        ttk.Button(options, text="Retirer", command=self._remove_selected).pack(side="left")
        ttk.Button(options, text="Tout effacer", command=self._clear).pack(side="left", padx=8)
        ttk.Checkbutton(
            options,
            text="Fusionner tous les PDF produits dans un document supplémentaire",
            variable=self.merge_results,
        ).pack(side="left", padx=20)

        destination = ttk.Frame(body, style="Card.TFrame", padding=15)
        destination.pack(fill="x", pady=(0, 12))
        ttk.Label(destination, text="Destination", style="Title.TLabel").pack(side="left")
        ttk.Entry(destination, textvariable=self.destination).pack(side="left", fill="x", expand=True, padx=14)
        ttk.Button(destination, text="Parcourir…", command=self._choose_destination).pack(side="left")

        actions = ttk.Frame(body, style="App.TFrame")
        actions.pack(fill="x")
        self.convert_button = ttk.Button(
            actions,
            text="Convertir en PDF",
            style="Primary.TButton",
            command=self._start,
        )
        self.convert_button.pack(side="left")
        self.open_button = ttk.Button(
            actions,
            text="Ouvrir les résultats",
            command=self._open_results,
            state="disabled",
        )
        self.open_button.pack(side="left", padx=10)
        self.status = ttk.Label(actions, text="Prêt.", background=BACKGROUND, foreground=MUTED)
        self.status.pack(side="right")
        self.progress = ttk.Progressbar(body, maximum=100)
        self.progress.pack(fill="x", pady=(13, 0))

    def _add_files(self) -> None:
        for path in choose_documents(self, SUPPORTED_SUFFIXES):
            if path in self.files or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            self.files.append(path)
            self.tree.insert(
                "",
                "end",
                iid=str(path),
                values=(path.name, path.suffix.upper().lstrip("."), str(path.parent), "En attente"),
            )

    def _remove_selected(self) -> None:
        if self.running:
            return
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
            messagebox.showwarning("Aucun document", "Ajoutez au moins un document.", parent=self)
            return
        destination = Path(self.destination.get()).expanduser()
        if not destination.is_dir():
            messagebox.showerror("Dossier introuvable", "Choisissez un dossier existant.", parent=self)
            return
        self.running = True
        self.generated.clear()
        self.output_by_source.clear()
        self.convert_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(12)
        threading.Thread(
            target=self._worker,
            args=(list(self.files), destination, self.merge_results.get()),
            daemon=True,
        ).start()

    def _worker(self, files: list[Path], destination: Path, merge: bool) -> None:
        generated: list[Path] = []
        failures: list[str] = []
        for index, source in enumerate(files, 1):
            self.events.put(("status", f"Conversion {index}/{len(files)} : {source.name}"))
            self.events.put(("row", (source, "Conversion…")))
            target = collision_free_target(destination, source.stem, ".pdf")
            try:
                convert_document_to_pdf(source, target)
                generated.append(target)
                self.events.put(("converted", (source, target)))
                self.events.put(("row", (source, f"Terminé → {target.name}")))
            except Exception as exc:  # noqa: BLE001 - isoler chaque élément du lot
                if target.exists():
                    target.unlink()
                failures.append(f"{source.name} : {exc}")
                self.events.put(("row", (source, f"Échec : {exc}")))
        if merge and generated:
            merged = collision_free_target(destination, "documents_fusionnes", ".pdf")
            try:
                merge_pdfs(generated, merged)
                generated.append(merged)
            except Exception as exc:  # noqa: BLE001 - conserver les conversions individuelles
                failures.append(f"Fusion : {exc}")
        self.events.put(("finished", (generated, failures)))

    def _poll(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.configure(text=str(value))
                elif kind == "row":
                    source, row_status = value  # type: ignore[misc]
                    current = self.tree.item(str(source), "values")
                    if current:
                        self.tree.item(str(source), values=(*current[:3], row_status))
                elif kind == "finished":
                    generated, failures = value  # type: ignore[misc]
                    self._finish(generated, failures)
                elif kind == "converted":
                    source, target = value  # type: ignore[misc]
                    self.output_by_source[source] = target
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _finish(self, generated: list[Path], failures: list[str]) -> None:
        self.running = False
        self.generated = generated
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self.convert_button.configure(state="normal")
        self.open_button.configure(state="normal" if generated else "disabled")
        self.status.configure(text=f"Terminé : {len(generated)} PDF, {len(failures)} échec(s).")
        if failures:
            messagebox.showwarning("Conversion terminée", "\n".join(failures[:8]), parent=self)
        else:
            target = generated[0] if len(generated) == 1 else generated[0].parent
            action_label = "Ouvrir le PDF" if len(generated) == 1 else "Ouvrir le dossier"
            show_success(
                self,
                "Conversion terminée",
                f"{len(generated)} PDF créé(s) dans :\n\n{generated[0].parent}",
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
        self.status.configure(text=f"Ouverture de {target.name}…")
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
