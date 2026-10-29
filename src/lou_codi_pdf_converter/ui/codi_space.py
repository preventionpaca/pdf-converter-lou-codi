from __future__ import annotations

import re
import threading
import tkinter as tk
import webbrowser
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from tkinterdnd2 import DND_ALL

from ..services.google_mail import (
    GoogleMailUnavailable,
    active_account,
    check_drive_access,
    connect_account,
    gmail_query_from_target,
    google_resource_metadata,
    list_accounts,
    list_drive_folder,
    list_gmail_message_choices,
    load_drive_link_index,
    read_drive_file,
    save_drive_link_index,
    set_active_account,
    upload_drive_file,
)
from ..services.photo_archive import PhotoArchiveResult, import_google_photos_archive
from ..space_library import (
    CodiSpace,
    SpaceResource,
    all_tags,
    ai_conversation_kind,
    ai_provider_label,
    import_space_index,
    library_path,
    load_spaces,
    move_resources_between_spaces,
    new_identifier,
    resource_from_drop,
    save_spaces,
    space_is_descendant,
    space_deletion_blocker,
)
from ..system import open_path
from ..paths import collision_free_target, module_output_directory
from ..i18n import tr, translate_widget_tree
from .directory_picker import choose_directory
from .input_dialogs import ask_text
from .module_links import add_help_contact_buttons
from .windowing import maximize_window

NAVY = "#193B66"
BLUE = "#2368AF"
BACKGROUND = "#F0F4F9"

RESOURCE_KINDS = {
    "Fiche de connaissance IA": "ai_knowledge",
    "Fiche ChatGPT": "ai_chatgpt_knowledge",
    "Fiche Claude": "ai_claude_knowledge",
    "Fiche Gemini": "ai_gemini_knowledge",
    "Conversation ChatGPT": "ai_chatgpt_conversation",
    "Conversation Claude": "ai_claude_conversation",
    "Conversation Gemini": "ai_gemini_conversation",
    "Fichier local": "local_file",
    "Dossier local": "local_folder",
    "Dossier Google Drive": "google_drive_folder",
    "Document Google Drive": "google_drive_document",
    "Tableur Google Sheets": "google_sheets",
    "Album Google Photos": "google_photos_album",
    "Courriel Gmail": "gmail_message",
    "Lien Internet ou vidéo": "web_link",
}


def drive_folder_id(value: str) -> str:
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    return value.strip() if re.fullmatch(r"[A-Za-z0-9_-]{10,}", value.strip()) else ""


def drive_folder_url(value: str) -> str:
    """Return the canonical browser URL for a linked Drive folder."""
    identifier = drive_folder_id(value)
    return f"https://drive.google.com/drive/folders/{identifier}" if identifier else ""


def clipboard_is_single_url(value: str) -> bool:
    """Only a clipboard made exclusively of one URL is treated as a link."""
    return bool(re.fullmatch(r"https?://\S+", value.strip()))


class CodiSpaceWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        project_path: Path | None = None,
        initial_space_id: str | None = None,
    ) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title("Lou Còdi Espace — Lou Còdi Workshop")
        self.geometry("1220x780")
        self.minsize(980, 620)
        self.configure(bg=BACKGROUND)
        self.spaces = load_spaces()
        known_space_ids = {space.identifier for space in self.spaces}
        self.current_space_id = initial_space_id if initial_space_id in known_space_ids else "inbox"
        if project_path is not None:
            imported = import_space_index(project_path, self.spaces)
            self.current_space_id = imported.identifier
            save_spaces(self.spaces)
        self.account = tk.StringVar(value=active_account())
        self.search = tk.StringVar()
        self.tag_search = tk.StringVar()
        self.resource_sort = "manual"
        self.resource_sort_reverse = False
        self._resource_drag_ids: tuple[str, ...] = ()
        self._space_drag_id = ""
        self._display_resources: dict[str, SpaceResource] = {}
        self._drive_items_by_space: dict[str, list] = {}
        self._photo_archive_results: Queue[tuple[PhotoArchiveResult | None, str, str, str]] = Queue()
        self._build()
        translate_widget_tree(self)
        self._refresh_spaces()
        self._library_mtime = self._current_library_mtime()
        self.after(1200, self._poll_external_library)
        maximize_window(self)
        self.after(250, self._check_google_setup)

    @staticmethod
    def _current_library_mtime() -> int:
        try:
            return library_path().stat().st_mtime_ns
        except OSError:
            return 0

    def _poll_external_library(self) -> None:
        if not self.winfo_exists():
            return
        current_mtime = self._current_library_mtime()
        if current_mtime != self._library_mtime:
            self._library_mtime = current_mtime
            self.spaces = load_spaces()
            if not any(space.identifier == self.current_space_id for space in self.spaces):
                self.current_space_id = "inbox"
            self._refresh_spaces(refresh_drive=False)
            self.status.configure(text="Nouvel élément reçu depuis Lou Còdi Capture.")
        self.after(1200, self._poll_external_library)

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, padx=22, pady=15)
        header.pack(fill="x")
        add_help_contact_buttons(header, "codi-espace")
        tk.Label(header, text="Lou Còdi Espace", bg=NAVY, fg="white", font=("Sans", 22, "bold")).pack(side="left")
        tk.Label(
            header,
            text="RELIER DOCUMENTS, DRIVE, COURRIELS, LIENS, ALBUMS PHOTOS ET FICHES DE CONNAISSANCE IA",
            bg=NAVY,
            fg="#CBDFF5",
            font=("Sans", 9),
        ).pack(side="left", padx=18)
        account_controls = tk.Frame(header, bg=NAVY)
        account_controls.pack(side="right")
        tk.Label(account_controls, text="Compte Google", bg=NAVY, fg="white").pack(side="left", padx=8)
        self.account_box = ttk.Combobox(
            account_controls, textvariable=self.account, state="readonly", width=34
        )
        self.account_box.pack(side="left")
        self.account_box.bind("<<ComboboxSelected>>", self._account_changed)
        ttk.Button(account_controls, text="+ Compte", command=self._add_google_account).pack(side="left", padx=(6, 0))
        self._refresh_accounts()

        toolbar = ttk.Frame(self, padding=(14, 10))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="+ Nouvel espace", command=self._new_space).pack(side="left")
        ttk.Button(toolbar, text="+ Sous-espace", command=self._new_subspace).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Supprimer l’espace", command=self._delete_space).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Classer l’espace", command=self._classify_space).pack(side="left")
        ttk.Button(toolbar, text="+ Ajouter une ressource", command=self._add_resource).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Ajouter lien ou texte copié", command=self._add_from_clipboard).pack(side="left")
        ttk.Button(toolbar, text="Lier un dossier Drive", command=self._link_drive_folder).pack(side="left")
        ttk.Button(toolbar, text="Ouvrir dossier Drive", command=self._open_linked_drive_folder).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(toolbar, text="Actualiser Drive", command=self._manual_refresh_drive).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Archiver l’album Photos", command=self._archive_photo_album).pack(
            side="left",
        )
        ttk.Button(
            toolbar, text="Dossier albums NAS", command=self._configure_photo_archive_folder,
        ).pack(side="left", padx=(6, 0))
        ttk.Entry(toolbar, textvariable=self.search, width=34).pack(side="right")
        ttk.Label(toolbar, text="Rechercher").pack(side="right", padx=6)
        self.search.trace_add("write", lambda *_args: self._refresh_resources(refresh_drive=False))

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        left = ttk.Frame(panes, padding=10)
        right = ttk.Frame(panes, padding=10)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        ttk.Label(left, text="Mes espaces", font=("Sans", 15, "bold")).pack(anchor="w", pady=(0, 8))
        space_list = ttk.Frame(left)
        space_list.pack(fill="both", expand=True)
        self.space_tree = ttk.Treeview(space_list, show="tree", selectmode="browse")
        self.space_tree.grid(row=0, column=0, sticky="nsew")
        space_scroll = ttk.Scrollbar(space_list, orient="vertical", command=self.space_tree.yview)
        space_scroll.grid(row=0, column=1, sticky="ns")
        space_scroll_x = ttk.Scrollbar(space_list, orient="horizontal", command=self.space_tree.xview)
        space_scroll_x.grid(row=1, column=0, sticky="ew")
        space_list.rowconfigure(0, weight=1)
        space_list.columnconfigure(0, weight=1)
        self.space_tree.configure(yscrollcommand=space_scroll.set, xscrollcommand=space_scroll_x.set)
        self.space_tree.bind("<<TreeviewSelect>>", self._select_space)
        self.space_tree.bind("<ButtonPress-1>", self._start_space_drag, add="+")
        self.space_tree.bind("<ButtonRelease-1>", self._finish_space_drag, add="+")
        ttk.Separator(left).pack(fill="x", pady=10)
        ttk.Label(left, text="Dictionnaire des tags", font=("Sans", 12, "bold")).pack(anchor="w")
        ttk.Entry(left, textvariable=self.tag_search).pack(fill="x", pady=(5, 4))
        self.tag_list = tk.Listbox(left, height=8, exportselection=False)
        self.tag_list.pack(fill="x")
        self.tag_list.bind("<<ListboxSelect>>", self._filter_with_selected_tag)
        self.tag_search.trace_add("write", lambda *_args: self._refresh_tag_catalog())

        self.space_title = tk.StringVar(value="À classer")
        ttk.Label(right, textvariable=self.space_title, font=("Sans", 17, "bold")).pack(anchor="w")
        self.space_detail = tk.StringVar()
        ttk.Label(right, textvariable=self.space_detail, foreground="#597089").pack(anchor="w", pady=(2, 10))
        ttk.Label(
            right,
            text="Déposez ici fichiers, dossiers ou liens — images, ZIP, tableurs et documents sont acceptés.",
            foreground="#2368AF",
        ).pack(anchor="w", pady=(0, 6))
        columns = ("details", "kind", "date", "tags", "account", "target")
        self.resource_tree = ttk.Treeview(right, columns=columns, show="tree headings", selectmode="extended")
        self.resource_tree.heading("#0", text="Titre")
        self.resource_tree.heading("details", text="Expéditeur / destinataire")
        self.resource_tree.heading("kind", text="Type")
        self.resource_tree.heading("date", text="Date d’ajout")
        self.resource_tree.heading("tags", text="Tags")
        self.resource_tree.heading("account", text="Compte")
        self.resource_tree.heading("target", text="Emplacement")
        self.resource_tree.column("#0", width=240)
        self.resource_tree.column("details", width=240)
        self.resource_tree.column("kind", width=145)
        self.resource_tree.column("date", width=130)
        self.resource_tree.column("tags", width=150)
        self.resource_tree.column("account", width=210)
        self.resource_tree.column("target", width=360)
        self.resource_tree.pack(fill="both", expand=True)
        for column, label in (
            ("#0", "title"), ("details", "details"), ("kind", "kind"),
            ("date", "date"), ("tags", "tags"), ("account", "account"),
        ):
            self.resource_tree.heading(
                column,
                command=lambda selected=label: self._sort_resources(selected),
            )
        self.resource_tree.bind("<Double-Button-1>", lambda _event: self._open_resource())
        self.resource_tree.bind("<Button-3>", self._show_resource_menu)
        self.resource_tree.bind("<ButtonPress-1>", self._start_resource_drag, add="+")
        self.resource_tree.bind("<ButtonRelease-1>", self._finish_resource_drag, add="+")
        self.resource_tree.drop_target_register(DND_ALL)
        self.resource_tree.dnd_bind("<<Drop>>", self._drop_resources)
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Ouvrir", command=self._open_resource).pack(side="left")
        ttk.Button(actions, text="Modifier les tags", command=self._edit_tags).pack(side="left", padx=6)
        ttk.Button(actions, text="Renommer", command=self._rename_resource).pack(side="left")
        ttk.Button(actions, text="Actualiser les infos", command=self._refresh_resource_metadata).pack(
            side="left", padx=6,
        )
        ttk.Button(actions, text="↑", command=lambda: self._move_resources(-1)).pack(side="left")
        ttk.Button(actions, text="↓", command=lambda: self._move_resources(1)).pack(side="left")
        ttk.Button(actions, text="Déplacer vers…", command=self._move_resources_to_space).pack(side="left", padx=6)
        ttk.Button(actions, text="Retirer de l’espace", command=self._remove_resource).pack(side="left")
        self.status = ttk.Label(actions, text="Les éléments restent à leur emplacement d’origine.")
        self.status.pack(side="right")
        self.activity = ttk.Progressbar(actions, mode="indeterminate", length=90)
        self.activity.pack(side="right", padx=(8, 6))
        self.after(250, self._poll_photo_archive_results)

    def _begin_activity(self, message: str) -> None:
        self.status.configure(text=message)
        self.activity.start(12)
        self.configure(cursor="watch")
        self.update_idletasks()

    def _end_activity(self) -> None:
        self.activity.stop()
        self.configure(cursor="")

    def _manual_refresh_drive(self) -> None:
        self._begin_activity("Actualisation du dossier Drive…")
        try:
            self._refresh_resources(refresh_drive=True)
        finally:
            self._end_activity()

    def _archive_photo_album(self) -> None:
        resource = self._selected_resource()
        if resource is None or resource.kind != "google_photos_album":
            messagebox.showinfo(
                "Album Google Photos",
                "Sélectionnez d’abord un album Google Photos dans la liste.",
                parent=self,
            )
            return
        webbrowser.open(resource.target)
        messagebox.showinfo(
            "Télécharger l’album",
            "Dans Google Photos, utilisez le menu ⋮ puis « Tout télécharger ».\n\n"
            "Quand le téléchargement est terminé, sélectionnez l’archive ZIP dans la fenêtre suivante.",
            parent=self,
        )
        archive = self._choose_photo_archive()
        if not archive:
            return
        space = self._selected_space()
        configured = Path(space.photo_archive_folder).expanduser() if space.photo_archive_folder else None
        if configured is not None and configured.is_dir():
            destination = str(configured)
        else:
            if configured is not None:
                messagebox.showinfo(
                    "Dossier d’archives indisponible",
                    "Le dossier mémorisé n’est pas accessible. Vérifiez que le NAS est connecté, "
                    "puis choisissez de nouveau le dossier.",
                    parent=self,
                )
            destination_path = choose_directory(self, configured or Path.home())
            destination = str(destination_path) if destination_path else ""
            if destination:
                space.photo_archive_folder = destination
                save_spaces(self.spaces)
        if not destination:
            return
        self._begin_activity("Import de l’album en cours… Lou Còdi vérifie chaque fichier.")
        album_title = resource.title if resource.title != "Album Google Photos" else Path(archive).stem
        space_id = self.current_space_id

        def import_archive() -> None:
            try:
                result = import_google_photos_archive(Path(archive), Path(destination), album_title)
                self._photo_archive_results.put((result, space_id, resource.identifier, ""))
            except Exception as exc:  # noqa: BLE001 - report archive and filesystem failures.
                self._photo_archive_results.put((None, space_id, resource.identifier, str(exc)))

        threading.Thread(target=import_archive, daemon=True).start()

    def _configure_photo_archive_folder(self) -> None:
        space = self._selected_space()
        if space.identifier == "inbox":
            messagebox.showinfo(
                "Dossier albums NAS",
                "Sélectionnez d’abord l’espace concerné.",
                parent=self,
            )
            return
        initial = Path(space.photo_archive_folder).expanduser() if space.photo_archive_folder else Path.home()
        destination = choose_directory(self, initial)
        if destination is None:
            return
        space.photo_archive_folder = str(destination)
        save_spaces(self.spaces)
        self.status.configure(
            text=f"Dossier d’archives mémorisé pour « {space.title} » : {destination}"
        )

    def _choose_photo_archive(self) -> str:
        dialog = tk.Toplevel(self)
        dialog.title("Archive téléchargée depuis Google Photos")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("720x430")
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Lou Còdi actualise cette liste automatiquement. "
            "Une archive en cours de téléchargement apparaîtra lorsqu’elle sera terminée.",
            wraplength=680,
        ).pack(anchor="w", pady=(0, 8))
        tree = ttk.Treeview(frame, columns=("size", "date"), show="tree headings", height=13)
        tree.heading("#0", text="Archive ZIP")
        tree.heading("size", text="Taille")
        tree.heading("date", text="Modification")
        tree.column("#0", width=390)
        tree.column("size", width=100, anchor="e")
        tree.column("date", width=170)
        tree.pack(fill="both", expand=True)
        result = ""
        paths: dict[str, Path] = {}

        def format_size(size: int) -> str:
            value = float(size)
            for unit in ("o", "Ko", "Mo", "Go", "To"):
                if value < 1024 or unit == "To":
                    return f"{value:.1f} {unit}" if unit != "o" else f"{int(value)} {unit}"
                value /= 1024
            return f"{size} o"

        def download_directories() -> list[Path]:
            candidates = [Path.home() / "Downloads", Path.home() / "Téléchargements"]
            return [path for index, path in enumerate(candidates) if path.is_dir() and path not in candidates[:index]]

        def refresh() -> None:
            if not dialog.winfo_exists():
                return
            previous = tree.selection()
            archives = sorted(
                (path for directory in download_directories() for path in directory.glob("*.zip")),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            tree.delete(*tree.get_children())
            paths.clear()
            for index, path in enumerate(archives):
                identifier = str(index)
                paths[identifier] = path
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
                tree.insert(
                    "", "end", iid=identifier, text=path.name,
                    values=(format_size(path.stat().st_size), modified),
                )
            if previous and tree.exists(previous[0]):
                tree.selection_set(previous[0])
            elif archives:
                tree.selection_set("0")
            dialog.after(1500, refresh)

        def choose(_event=None) -> None:
            nonlocal result
            selection = tree.selection()
            if selection and selection[0] in paths:
                result = str(paths[selection[0]])
                dialog.destroy()

        def browse() -> None:
            nonlocal result
            selected = filedialog.askopenfilename(
                parent=dialog, title="Choisir une archive ZIP",
                filetypes=(("Archive ZIP", "*.zip"), ("Tous les fichiers", "*")),
            )
            if selected:
                result = selected
                dialog.destroy()

        tree.bind("<Double-Button-1>", choose)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Parcourir ailleurs…", command=browse).pack(side="left")
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Utiliser cette archive", command=choose).pack(side="right", padx=6)
        refresh()
        dialog.wait_window()
        return result

    def _poll_photo_archive_results(self) -> None:
        try:
            while True:
                result, space_id, resource_id, error = self._photo_archive_results.get_nowait()
                self._end_activity()
                if error:
                    messagebox.showerror("Import de l’album impossible", error, parent=self)
                    self.status.configure(text="Import de l’album interrompu.")
                    continue
                if result is None:
                    continue
                space = next((item for item in self.spaces if item.identifier == space_id), None)
                if space is None:
                    continue
                source = next((item for item in space.resources if item.identifier == resource_id), None)
                title = f"Sauvegarde — {source.title}" if source else result.directory.name
                if not any(item.target == str(result.directory) for item in space.resources):
                    space.resources.append(SpaceResource(
                        identifier=new_identifier(), title=title, kind="local_folder",
                        target=str(result.directory), tags=["archive photos"],
                        account_email=self.account.get(),
                    ))
                save_spaces(self.spaces)
                self._refresh_resources(refresh_drive=False)
                self.status.configure(
                    text=f"Album archivé : {result.extracted} fichier(s), "
                    f"{result.duplicates} doublon(s) ignoré(s).",
                )
        except Empty:
            pass
        if self.winfo_exists():
            self.after(250, self._poll_photo_archive_results)

    def _selected_space(self) -> CodiSpace:
        return next((space for space in self.spaces if space.identifier == self.current_space_id), self.spaces[0])

    def _tag_values(self) -> list[str]:
        return all_tags(self.spaces)

    def _refresh_tag_catalog(self) -> None:
        if not hasattr(self, "tag_list"):
            return
        needle = self.tag_search.get().casefold().strip()
        self.tag_list.delete(0, "end")
        for tag in self._tag_values():
            if not needle or needle in tag.casefold():
                self.tag_list.insert("end", tag)

    def _filter_with_selected_tag(self, _event=None) -> None:
        selection = self.tag_list.curselection()
        if selection:
            self.search.set(self.tag_list.get(selection[0]))

    def _configure_tag_combobox(self, box: ttk.Combobox, variable: tk.StringVar) -> None:
        prefix_holder = {"value": ""}

        def fragment() -> str:
            return variable.get().rsplit(",", 1)[-1].strip()

        def filter_values(_event=None) -> None:
            current = variable.get()
            prefix_holder["value"] = current.rsplit(",", 1)[0].strip() if "," in current else ""
            needle = fragment().casefold()
            values = [tag for tag in self._tag_values() if not needle or tag.casefold().startswith(needle)]
            box.configure(values=values)

        def choose(_event=None) -> None:
            chosen = box.get().strip()
            prefix = prefix_holder["value"]
            variable.set(f"{prefix}, {chosen}" if prefix else chosen)
            box.icursor("end")

        box.configure(values=self._tag_values())
        box.bind("<KeyRelease>", filter_values)
        box.bind("<<ComboboxSelected>>", choose)

    def _ask_tags(self, initial: list[str]) -> list[str] | None:
        dialog = tk.Toplevel(self)
        dialog.title("Modifier les tags")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Tags séparés par des virgules").pack(anchor="w")
        value = tk.StringVar(value=", ".join(initial))
        box = ttk.Combobox(frame, textvariable=value, width=55)
        box.pack(fill="x", pady=(6, 4))
        self._configure_tag_combobox(box, value)
        ttk.Label(
            frame,
            text="Tapez quelques lettres : les tags existants sont proposés automatiquement.",
            foreground="#597089",
        ).pack(anchor="w")
        result: list[str] | None = None

        def validate() -> None:
            nonlocal result
            result = [tag.strip() for tag in value.get().split(",") if tag.strip()]
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e", pady=(14, 0))
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="left")
        ttk.Button(buttons, text="Valider", command=validate).pack(side="left", padx=(6, 0))
        box.focus_set()
        dialog.wait_window()
        return result

    def _drop_values(self, data: str) -> list[str]:
        urls = re.findall(r"https?://[^\s{}<>\"]+", data)
        if urls:
            if len(urls) == 1:
                return [data.strip()]
            return list(dict.fromkeys(url.rstrip(").,;'") for url in urls))
        try:
            values = list(self.tk.splitlist(data))
        except tk.TclError:
            values = [line.strip() for line in data.splitlines() if line.strip()]
        expanded = []
        for value in values:
            lines = [line.strip() for line in value.splitlines() if line.strip()]
            expanded.extend(lines or [value])
        return expanded

    def _add_dropped_values(self, values: list[str]) -> int:
        space = self._selected_space()
        added = 0
        for value in values:
            account = space.account_email if space.drive_folder else self.account.get()
            resource = resource_from_drop(value, account)
            if resource is not None:
                if resource.kind == "local_file" and space.drive_folder:
                    folder_id = drive_folder_id(space.drive_folder)
                    if not folder_id:
                        messagebox.showerror(
                            "Dossier Drive invalide",
                            "L’espace n’est pas lié à un véritable dossier Google Drive. "
                            "Cliquez sur « Lier un dossier Drive » et collez l’adresse d’un dossier Drive, "
                            "pas celle d’un album Photos.",
                            parent=self,
                        )
                        continue
                    try:
                        upload_drive_file(account, folder_id, Path(resource.target))
                    except Exception as exc:  # noqa: BLE001 - surface Drive upload failures.
                        messagebox.showerror(
                            "Téléversement Drive impossible", self._drive_error_message(exc), parent=self
                        )
                        continue
                    added += 1
                else:
                    try:
                        resolved_title, details = google_resource_metadata(
                            account, resource.kind, resource.target,
                        )
                    except Exception:  # noqa: BLE001 - retain the useful generic title offline.
                        resolved_title, details = "", ""
                    if resolved_title:
                        resource.title = resolved_title
                    if details:
                        resource.details = details
                    if resource.kind == "gmail_message" and not resolved_title:
                        selected = self._choose_gmail_message(account, resource.target)
                        if selected:
                            resource.title, resource.details = selected
                    space.resources.append(resource)
                    added += 1
        if added:
            self._save()
            destination = " dans Drive" if space.drive_folder else ""
            self.status.configure(text=f"{added} ressource(s) ajoutée(s){destination}.")
        return added

    def _drop_resources(self, event) -> str:
        if not self._add_dropped_values(self._drop_values(str(event.data))):
            self.status.configure(
                text="Dépôt non reconnu. Pour Gmail, copiez l’adresse du message puis utilisez Ajouter le presse-papiers."
            )
        return "break"

    def _add_from_clipboard(self) -> None:
        try:
            content = self.clipboard_get()
        except tk.TclError:
            content = ""
        if not content:
            messagebox.showinfo(
                "Presse-papiers",
                "Copiez d’abord un lien ou un passage de conversation, puis réessayez.",
                parent=self,
            )
            return
        stripped_content = content.strip()
        if clipboard_is_single_url(stripped_content) and self._add_dropped_values([stripped_content]):
            return
        title = ask_text(
            self,
            "Nouvelle fiche de connaissance",
            "Titre de cette fiche :",
            stripped_content.splitlines()[0][:100],
        )
        if not title or not title.strip():
            return
        source = ask_text(
            self,
            "Source de la fiche",
            "Lien vers la conversation (facultatif) :",
            "",
        )
        source_value = (source or "").strip()
        provider = ai_provider_label(ai_conversation_kind(source_value, knowledge=True))
        safe_stem = re.sub(r"[^\w .-]+", "_", title.strip(), flags=re.UNICODE).strip(" .")
        note_path = collision_free_target(
            module_output_directory("Lou Còdi Espace") / "Fiches de connaissance",
            safe_stem or "Fiche de connaissance",
            ".md",
        )
        note_path.parent.mkdir(parents=True, exist_ok=True)
        source_line = f"\nSource : {source_value}\n" if source_value else ""
        note_path.write_text(
            f"# {title.strip()}\n\nType : fiche de connaissance {provider}\n"
            f"{source_line}\n{stripped_content}\n",
            encoding="utf-8",
        )
        resource = SpaceResource(
            identifier=new_identifier(),
            title=title.strip(),
            kind=ai_conversation_kind(source_value, knowledge=True),
            target=source_value or str(note_path),
            account_email=self._selected_space().account_email,
            details=stripped_content,
        )
        self._selected_space().resources.append(resource)
        self._save()
        self.status.configure(text="Fiche de connaissance ajoutée depuis le presse-papiers.")

    def _show_text_resource(self, resource: SpaceResource, content: str) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(resource.title)
        dialog.geometry("1050x720")
        dialog.minsize(700, 450)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=resource.title, font=("Sans", 16, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=f"Fiche {ai_provider_label(resource.kind)}",
            foreground="#597089",
        ).pack(anchor="w", pady=(2, 10))
        viewer = ScrolledText(frame, wrap="word", font=("Monospace", 11), undo=False)
        viewer.pack(fill="both", expand=True)
        viewer.insert("1.0", content)
        viewer.configure(state="disabled")

        def copy_selected() -> None:
            try:
                value = viewer.get("sel.first", "sel.last")
            except tk.TclError:
                value = ""
            if value:
                self.clipboard_clear()
                self.clipboard_append(value)
                self.status.configure(text="Texte sélectionné copié.")

        def copy_all() -> None:
            self.clipboard_clear()
            self.clipboard_append(content)
            self.status.configure(text="Contenu de la fiche copié.")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Copier la sélection", command=copy_selected).pack(side="left")
        ttk.Button(buttons, text="Tout copier", command=copy_all).pack(side="left", padx=6)
        if resource.target and Path(resource.target).is_file():
            ttk.Button(
                buttons,
                text="Ouvrir le fichier .md",
                command=lambda: open_path(Path(resource.target)),
            ).pack(side="left")
        ttk.Button(buttons, text="Fermer", command=dialog.destroy).pack(side="right")

    def _refresh_accounts(self, selected: str = "") -> None:
        accounts = [account.email for account in list_accounts()]
        self.account_box.configure(values=accounts)
        chosen = selected or active_account()
        if chosen in accounts:
            self.account.set(chosen)
        elif accounts:
            self.account.set(accounts[0])
            set_active_account(accounts[0])
        else:
            self.account.set("")

    def _add_google_account(self) -> None:
        self.status.configure(text="Ouverture de la connexion Google dans votre navigateur…")
        self.update_idletasks()
        try:
            connected = connect_account()
        except Exception as exc:  # noqa: BLE001 - Google libraries expose several transport errors.
            self.status.configure(text=str(exc))
            messagebox.showerror("Connexion Google impossible", str(exc), parent=self)
            return
        self._refresh_accounts(connected.email)
        self.status.configure(text=f"Compte Google connecté : {connected.email}")
        self._manual_refresh_drive()

    @staticmethod
    def _drive_error_message(exc: Exception) -> str:
        message = str(exc)
        if "SERVICE_DISABLED" in message or "accessNotConfigured" in message:
            return (
                "Google Drive API n’est pas encore activée dans le projet loucodi-workshop. "
                "Cette activation se fait une seule fois et vaudra ensuite pour tous les ordinateurs."
            )
        return message

    def _check_google_setup(self, *, offer_connection: bool = True) -> None:
        accounts = [account.email for account in list_accounts()]
        if not accounts:
            self.status.configure(text="Aucun compte Google n’est connecté sur cet ordinateur.")
            if offer_connection and messagebox.askyesno(
                "Compte Google requis",
                "Lou Còdi Espace utilise principalement Google Drive. Voulez-vous connecter un compte maintenant ?",
                parent=self,
            ):
                self._add_google_account()
            return
        email = self.account.get() if self.account.get() in accounts else accounts[0]
        try:
            check_drive_access(email)
        except GoogleMailUnavailable as exc:
            self.status.configure(text=str(exc))
            if offer_connection and messagebox.askyesno(
                "Autorisation Google à renouveler",
                f"{exc}\n\nVoulez-vous reconnecter ce compte maintenant ?",
                parent=self,
            ):
                self._add_google_account()
            return
        except Exception as exc:  # noqa: BLE001 - surface the provider's actionable response.
            message = self._drive_error_message(exc)
            self.status.configure(text=message)
            if offer_connection and message != str(exc) and messagebox.askyesno(
                "Configuration Google Drive",
                f"{message}\n\nOuvrir maintenant la page d’activation Google Drive API ?",
                parent=self,
            ):
                webbrowser.open(
                    "https://console.cloud.google.com/apis/library/drive.googleapis.com"
                    "?project=loucodi-workshop"
                )
            return
        self.status.configure(text=f"{tr('Google Drive prêt')} — {email}")

    def _refresh_spaces(self, *, refresh_drive: bool = True) -> None:
        self.space_tree.delete(*self.space_tree.get_children())
        inbox = next((space for space in self.spaces if space.identifier == "inbox"), None)
        if inbox is not None:
            self.space_tree.insert("", "end", iid=inbox.identifier, text=inbox.title)
        normal_spaces = [space for space in self.spaces if space.identifier != "inbox"]
        by_id = {space.identifier: space for space in normal_spaces}
        children: dict[str, list[CodiSpace]] = {}
        roots: list[CodiSpace] = []
        for space in normal_spaces:
            if space.parent_id and space.parent_id in by_id and space.parent_id != space.identifier:
                children.setdefault(space.parent_id, []).append(space)
            else:
                roots.append(space)
        groups: dict[str, str] = {}

        def insert_branch(space: CodiSpace, parent: str, ancestry: set[str]) -> None:
            self.space_tree.insert(parent, "end", iid=space.identifier, text=space.title, open=True)
            if space.identifier in ancestry:
                return
            for child in children.get(space.identifier, []):
                insert_branch(child, space.identifier, {*ancestry, space.identifier})

        for space in roots:
            group = space.group.strip() or self._default_space_group(space)
            group_id = groups.get(group)
            if group_id is None:
                group_id = f"group:{len(groups)}"
                groups[group] = group_id
                self.space_tree.insert("", "end", iid=group_id, text=group, open=True)
            insert_branch(space, group_id, set())
        if self.space_tree.exists(self.current_space_id):
            self.space_tree.selection_set(self.current_space_id)
        self._refresh_tag_catalog()
        self._refresh_resources(refresh_drive=refresh_drive)

    def _refresh_resources(self, *, refresh_drive: bool = True) -> None:
        space = self._selected_space()
        self.space_title.set(space.title)
        details = [f"Compte : {space.account_email or 'non défini'}"]
        if space.drive_folder:
            details.append("dossier Drive lié")
        self.space_detail.set("  •  ".join(details))
        if refresh_drive and space.drive_folder and space.account_email:
            folder_id = drive_folder_id(space.drive_folder)
            if folder_id:
                try:
                    remote_links = load_drive_link_index(space.account_email, folder_id, space.title)
                except Exception:  # noqa: BLE001 - folder listing below provides the visible error.
                    remote_links = []
            else:
                remote_links = []
            local_by_id = {resource.identifier: resource for resource in space.resources}
            changed = False
            for raw in remote_links:
                if not isinstance(raw, dict) or not raw.get("target"):
                    continue
                identifier = str(raw.get("identifier") or new_identifier())
                incoming = SpaceResource(
                    identifier=identifier,
                    title=str(raw.get("title") or raw["target"]),
                    kind=str(raw.get("kind") or "web_link"),
                    target=str(raw["target"]),
                    tags=[str(tag) for tag in raw.get("tags", []) if str(tag).strip()],
                    account_email=space.account_email,
                )
                if identifier not in local_by_id:
                    space.resources.append(incoming)
                    local_by_id[identifier] = incoming
                    changed = True
            if changed:
                save_spaces(self.spaces)
        self.resource_tree.delete(*self.resource_tree.get_children())
        self._display_resources = {resource.identifier: resource for resource in space.resources}
        needle = self.search.get().casefold().strip()
        resources = list(space.resources)
        if self.resource_sort != "manual":
            def key(resource: SpaceResource) -> str:
                values = {
                    "title": resource.title,
                    "details": resource.details,
                    "kind": resource.kind,
                    "date": resource.created_at,
                    "tags": ", ".join(resource.tags),
                    "account": resource.account_email,
                }
                return values.get(self.resource_sort, "").casefold()
            resources.sort(key=key, reverse=self.resource_sort_reverse)
        for resource in resources:
            haystack = f"{resource.title} {' '.join(resource.tags)} {resource.target}".casefold()
            if needle and needle not in haystack:
                continue
            label = next((name for name, kind in RESOURCE_KINDS.items() if kind == resource.kind), resource.kind)
            self.resource_tree.insert(
                "", "end", iid=resource.identifier, text=self._resource_display_title(resource),
                values=(
                    resource.details, label, self._display_date(resource.created_at), ", ".join(resource.tags),
                    resource.account_email, resource.target,
                ),
            )
        if space.drive_folder and space.account_email:
            folder_id = drive_folder_id(space.drive_folder)
            if not folder_id:
                self.status.configure(text="L’adresse du dossier Drive n’est pas reconnue.")
                return
            if refresh_drive:
                try:
                    drive_items = list_drive_folder(space.account_email, folder_id)
                    self._drive_items_by_space[space.identifier] = drive_items
                except (GoogleMailUnavailable, OSError, ValueError) as exc:
                    self.status.configure(text=str(exc))
                    return
                except Exception as exc:  # noqa: BLE001 - Drive wraps API failures dynamically.
                    self.status.configure(text=self._drive_error_message(exc))
                    return
            else:
                drive_items = self._drive_items_by_space.get(space.identifier, [])
            for item in drive_items:
                identifier = f"drive:{item.identifier}"
                kind = (
                    "google_drive_folder"
                    if item.mime_type == "application/vnd.google-apps.folder"
                    else "google_drive_document"
                )
                resource = SpaceResource(
                    identifier=identifier,
                    title=item.name,
                    kind=kind,
                    target=item.web_url,
                    account_email=space.account_email,
                )
                self._display_resources[identifier] = resource
                haystack = f"{resource.title} {resource.target}".casefold()
                if needle and needle not in haystack:
                    continue
                label = "Dossier Google Drive" if kind == "google_drive_folder" else "Document Google Drive"
                self.resource_tree.insert(
                    "", "end", iid=identifier, text=self._resource_display_title(resource),
                    values=("", label, "", "", resource.account_email, resource.target),
                )
            if refresh_drive:
                self.status.configure(text=f"Dossier Drive actualisé : {len(drive_items)} élément(s).")

    def _save(self) -> None:
        save_spaces(self.spaces)
        space = self._selected_space()
        self._sync_space_index_in_background(space)
        self._refresh_spaces(refresh_drive=False)

    def _account_changed(self, _event=None) -> None:
        if self.account.get():
            set_active_account(self.account.get())
            self._check_google_setup(offer_connection=False)

    @staticmethod
    def _default_space_group(space: CodiSpace) -> str:
        return "Personnel" if space.account_email.casefold().endswith("@gmail.com") else "Professionnel"

    @staticmethod
    def _resource_display_title(resource: SpaceResource) -> str:
        icons = {
            "ai_knowledge": "✦",
            "ai_chatgpt_knowledge": "[ChatGPT]",
            "ai_claude_knowledge": "[Claude]",
            "ai_gemini_knowledge": "[Gemini]",
            "ai_chatgpt_conversation": "[ChatGPT]",
            "ai_claude_conversation": "[Claude]",
            "ai_gemini_conversation": "[Gemini]",
            "google_photos_album": "📸",
            "gmail_message": "✉",
            "google_sheets": "▦",
            "google_docs": "▤",
            "google_slides": "▰",
            "google_drive_folder": "📁",
            "google_drive_document": "☁",
            "local_folder": "📁",
            "local_file": "📄",
            "web_link": "🔗",
        }
        return f"{icons.get(resource.kind, '•')}  {resource.title}"

    @staticmethod
    def _display_date(value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return value

    def _sort_resources(self, criterion: str) -> None:
        if self.resource_sort == criterion:
            self.resource_sort_reverse = not self.resource_sort_reverse
        else:
            self.resource_sort = criterion
            self.resource_sort_reverse = False
        self._refresh_resources(refresh_drive=False)

    def _move_resources(self, direction: int) -> None:
        selected = set(self.resource_tree.selection())
        if not selected or any(identifier.startswith("drive:") for identifier in selected):
            return
        resources = self._selected_space().resources
        indices = [index for index, resource in enumerate(resources) if resource.identifier in selected]
        if direction < 0:
            for index in indices:
                if index > 0 and resources[index - 1].identifier not in selected:
                    resources[index - 1], resources[index] = resources[index], resources[index - 1]
        else:
            for index in reversed(indices):
                if index < len(resources) - 1 and resources[index + 1].identifier not in selected:
                    resources[index], resources[index + 1] = resources[index + 1], resources[index]
        self.resource_sort = "manual"
        save_spaces(self.spaces)
        self._refresh_resources(refresh_drive=False)
        self._sync_space_index_in_background(self._selected_space())
        for identifier in selected:
            if self.resource_tree.exists(identifier):
                self.resource_tree.selection_add(identifier)

    def _start_resource_drag(self, event: tk.Event[tk.Misc]) -> None:
        identifier = self.resource_tree.identify_row(event.y)
        if not identifier:
            self._resource_drag_ids = ()
            return
        selection = self.resource_tree.selection()
        if identifier not in selection:
            self.resource_tree.selection_set(identifier)
            selection = (identifier,)
        self._resource_drag_ids = tuple(
            item for item in self.resource_tree.get_children()
            if item in selection and not item.startswith("drive:")
        )

    def _finish_resource_drag(self, event: tk.Event[tk.Misc]) -> None:
        moving = self._resource_drag_ids
        self._resource_drag_ids = ()
        target = self.resource_tree.identify_row(event.y)
        if not moving or not target or target in moving:
            return
        visible = list(self.resource_tree.get_children())
        remaining = [identifier for identifier in visible if identifier not in moving]
        target_index = remaining.index(target) if target in remaining else len(remaining)
        reordered = remaining[:target_index] + list(moving) + remaining[target_index:]
        for index, identifier in enumerate(reordered):
            self.resource_tree.move(identifier, "", index)
        space = self._selected_space()
        by_id = {resource.identifier: resource for resource in space.resources}
        local_order = [identifier for identifier in reordered if identifier in by_id]
        space.resources = [by_id[identifier] for identifier in local_order]
        self.resource_sort = "manual"
        save_spaces(self.spaces)
        self._sync_space_index_in_background(space)
        self.status.configure(text="Ordre manuel enregistré.")

    def _start_space_drag(self, event: tk.Event[tk.Misc]) -> None:
        identifier = self.space_tree.identify_row(event.y)
        self._space_drag_id = (
            identifier if identifier and identifier != "inbox" and not identifier.startswith("group:") else ""
        )

    def _finish_space_drag(self, event: tk.Event[tk.Misc]) -> None:
        source_id = self._space_drag_id
        self._space_drag_id = ""
        target_id = self.space_tree.identify_row(event.y)
        if not source_id or not target_id or source_id == target_id:
            return
        source = next((space for space in self.spaces if space.identifier == source_id), None)
        if source is None:
            return
        if target_id.startswith("group:"):
            source.parent_id = ""
            source.group = self.space_tree.item(target_id, "text")
            self.spaces.remove(source)
            children = self.space_tree.get_children(target_id)
            if children:
                last_id = children[-1]
                position = next(
                    (index + 1 for index, space in enumerate(self.spaces) if space.identifier == last_id),
                    len(self.spaces),
                )
                self.spaces.insert(position, source)
            else:
                self.spaces.append(source)
        else:
            target = next((space for space in self.spaces if space.identifier == target_id), None)
            if target is None or target.identifier == "inbox":
                return
            if space_is_descendant(self.spaces, target.identifier, source.identifier):
                messagebox.showinfo(
                    "Déplacement impossible",
                    "Un espace ne peut pas être rangé dans l’un de ses propres sous-espaces.",
                    parent=self,
                )
                return
            source.parent_id = target.identifier
            source.group = target.group or self._default_space_group(target)
        save_spaces(self.spaces)
        self.current_space_id = source.identifier
        self._refresh_spaces(refresh_drive=False)

    def _classify_space(self) -> None:
        space = self._selected_space()
        if space.identifier == "inbox":
            return
        current = space.group or self._default_space_group(space)
        group = ask_text(
            self,
            "Classer l’espace",
            "Nom du groupe (par exemple Personnel, Professionnel, Archives…) :",
            current,
        )
        if group:
            space.group = group
            space.parent_id = ""
            save_spaces(self.spaces)
            self._refresh_spaces(refresh_drive=False)

    def _select_space(self, _event=None) -> None:
        selection = self.space_tree.selection()
        if selection and not selection[0].startswith("group:"):
            self.current_space_id = selection[0]
            # Switching space must remain immediate. Network access is reserved for
            # the explicit “Actualiser Drive” command and cached items are reused.
            self._refresh_resources(refresh_drive=False)

    def _new_space(self) -> None:
        title = ask_text(self, "Nouvel espace", "Nom de l’espace :")
        if not title or not title.strip():
            return
        space = CodiSpace(new_identifier(), title.strip(), account_email=self.account.get())
        self.spaces.append(space)
        self.current_space_id = space.identifier
        self._save()

    def _new_subspace(self) -> None:
        parent = self._selected_space()
        if parent.identifier == "inbox":
            messagebox.showinfo(
                "Sous-espace",
                "Sélectionnez d’abord l’espace qui doit contenir le nouveau sous-espace.",
                parent=self,
            )
            return
        title = ask_text(
            self,
            "Nouveau sous-espace",
            f"Nom du sous-espace à créer dans « {parent.title} » :",
        )
        if not title or not title.strip():
            return
        space = CodiSpace(
            new_identifier(),
            title.strip(),
            account_email=parent.account_email or self.account.get(),
            group=parent.group or self._default_space_group(parent),
            parent_id=parent.identifier,
        )
        self.spaces.append(space)
        self.current_space_id = space.identifier
        self._save()

    def _delete_space(self) -> None:
        space = self._selected_space()
        if any(candidate.parent_id == space.identifier for candidate in self.spaces):
            messagebox.showinfo(
                "Suppression impossible",
                "Cet espace contient encore un ou plusieurs sous-espaces.",
                parent=self,
            )
            return
        blocker = space_deletion_blocker(space)
        if blocker:
            messagebox.showinfo("Suppression impossible", blocker, parent=self)
            return
        if not messagebox.askyesno(
            "Supprimer l’espace",
            f"Supprimer définitivement l’espace vide « {space.title} » ?\n\n"
            "Aucun fichier Google Drive ou local ne sera supprimé.",
            parent=self,
            default="no",
        ):
            return
        self.spaces.remove(space)
        self.current_space_id = "inbox"
        self._save()

    def _link_drive_folder(self) -> None:
        space = self._selected_space()
        value = ask_text(
            self, "Dossier Google Drive",
            "Collez l’adresse du dossier Drive à utiliser pour cet espace.",
            space.drive_folder,
        )
        if value is None:
            return
        value = value.strip()
        if value and not drive_folder_id(value):
            messagebox.showerror(
                "Adresse Drive incorrecte",
                "Cette adresse n’est pas celle d’un dossier Google Drive.\n\n"
                "Un album Google Photos doit être ajouté comme ressource ou par glisser-déposer.",
                parent=self,
            )
            return
        space.drive_folder = value
        space.account_email = self.account.get() or space.account_email
        self._save()

    def _open_linked_drive_folder(self) -> None:
        space = self._selected_space()
        url = drive_folder_url(space.drive_folder)
        if not url:
            messagebox.showinfo(
                "Dossier Drive",
                f"L’espace « {space.title} » n’a pas encore de dossier Google Drive lié.",
                parent=self,
            )
            return
        webbrowser.open(url)
        self.status.configure(text=f"Ouverture du dossier Drive lié à « {space.title} ».")

    def _add_resource(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Ajouter une ressource")
        dialog.geometry("660x330")
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        kind_name = tk.StringVar(value="Lien Internet ou vidéo")
        title = tk.StringVar()
        target = tk.StringVar()
        tags = tk.StringVar()
        for row, (label, variable) in enumerate((("Type", kind_name), ("Titre", title), ("Adresse ou chemin", target), ("Tags séparés par des virgules", tags))):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6)
            if row == 0:
                ttk.Combobox(frame, textvariable=variable, values=list(RESOURCE_KINDS), state="readonly").grid(row=row, column=1, sticky="ew", pady=6)
            elif row == 3:
                tag_box = ttk.Combobox(frame, textvariable=variable)
                tag_box.grid(row=row, column=1, sticky="ew", pady=6)
                self._configure_tag_combobox(tag_box, tags)
            else:
                ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)

        def browse() -> None:
            if kind_name.get() == "Fichier local":
                value = filedialog.askopenfilename(parent=dialog)
            else:
                value = str(choose_directory(dialog, Path.home()) or "")
            if value:
                target.set(value)
                if not title.get():
                    title.set(Path(value).name)

        ttk.Button(frame, text="Parcourir…", command=browse).grid(row=2, column=2, padx=6)

        def validate() -> None:
            if not target.get().strip():
                messagebox.showinfo("Ressource", "Indiquez une adresse ou un chemin.", parent=dialog)
                return
            resource = SpaceResource(
                identifier=new_identifier(),
                title=title.get().strip() or target.get().strip(),
                kind=RESOURCE_KINDS[kind_name.get()],
                target=target.get().strip(),
                tags=[tag.strip() for tag in tags.get().split(",") if tag.strip()],
                account_email=self.account.get(),
            )
            self._selected_space().resources.append(resource)
            self._save()
            dialog.destroy()

        frame.columnconfigure(1, weight=1)
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="left")
        ttk.Button(buttons, text="Ajouter", command=validate).pack(side="left", padx=6)

    def _selected_resource(self) -> SpaceResource | None:
        selection = self.resource_tree.selection()
        if not selection:
            return None
        identifier = selection[0]
        return self._display_resources.get(identifier)

    def _open_resource(self) -> None:
        resource = self._selected_resource()
        if resource is None:
            return
        if resource.kind.endswith("_knowledge") or resource.kind == "ai_knowledge":
            content = resource.details
            if not content and Path(resource.target).is_file():
                content = Path(resource.target).read_text(encoding="utf-8", errors="replace")
            self._show_text_resource(
                resource,
                content or "Cette fiche ne contient pas encore d’extrait.",
            )
            if resource.target.startswith(("http://", "https://")) and messagebox.askyesno(
                "Ouvrir la source",
                "Voulez-vous ouvrir la conversation d’origine ?",
                parent=self,
            ):
                webbrowser.open(resource.target)
        elif resource.identifier.startswith("drive:") and not Path(resource.title).suffix:
            try:
                payload = read_drive_file(
                    resource.account_email or self.account.get(),
                    resource.identifier.removeprefix("drive:"),
                )
                content = payload.decode("utf-8")
            except (UnicodeDecodeError, OSError, ValueError):
                webbrowser.open(resource.target)
            except Exception:  # noqa: BLE001 - fall back to Drive for provider/API errors.
                webbrowser.open(resource.target)
            else:
                self._show_text_resource(resource, content)
        elif resource.target.startswith(("http://", "https://")):
            webbrowser.open(resource.target)
        else:
            open_path(Path(resource.target).expanduser())

    def _edit_tags(self) -> None:
        resource = self._selected_resource()
        if resource is None:
            return
        if resource.identifier.startswith("drive:"):
            messagebox.showinfo(
                "Tags Drive",
                "Les tags des éléments synchronisés depuis Drive ne sont pas encore modifiables dans Lou Còdi Espace.",
                parent=self,
            )
            return
        value = self._ask_tags(resource.tags)
        if value is not None:
            resource.tags = value
            save_spaces(self.spaces)
            self._refresh_tag_catalog()
            self._refresh_resources(refresh_drive=False)
            self._sync_space_index_in_background(self._selected_space())

    def _rename_resource(self) -> None:
        resource = self._selected_resource()
        if resource is None:
            return
        if resource.identifier.startswith("drive:"):
            messagebox.showinfo(
                "Nom Drive",
                "Renommez ce fichier directement dans Google Drive.",
                parent=self,
            )
            return
        title = ask_text(self, "Renommer la ressource", "Titre affiché :", resource.title)
        if title and title.strip():
            resource.title = title.strip()
            self._save()

    def _refresh_resource_metadata(self) -> None:
        resource = self._selected_resource()
        if resource is None or resource.identifier.startswith("drive:"):
            return
        try:
            title, details = google_resource_metadata(
                resource.account_email or self.account.get(), resource.kind, resource.target,
            )
        except Exception as exc:  # noqa: BLE001 - browser Gmail ids differ from API ids.
            if resource.kind == "gmail_message":
                selected = self._choose_gmail_message(
                    resource.account_email or self.account.get(), resource.target,
                )
                if selected:
                    resource.title, resource.details = selected
                    self._save()
                    return
            messagebox.showinfo(
                "Informations indisponibles",
                f"Google n’a pas fourni les informations de cette ressource.\n\n{exc}",
                parent=self,
            )
            return
        if not title and not details:
            messagebox.showinfo(
                "Informations indisponibles",
                "Le service ne transmet pas le nom associé à ce lien. Vous pouvez utiliser « Renommer ».",
                parent=self,
            )
            return
        resource.title = title or resource.title
        resource.details = details
        self._save()

    def _choose_gmail_message(self, email: str, target: str) -> tuple[str, str] | None:
        dialog = tk.Toplevel(self)
        dialog.title("Rechercher et choisir le courriel")
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Gmail masque l’identifiant réel dans l’adresse du navigateur. "
            "Recherchez le message avec la syntaxe Gmail, puis choisissez-le.",
            wraplength=820,
        ).pack(anchor="w", pady=(0, 8))
        search_row = ttk.Frame(frame)
        search_row.pack(fill="x", pady=(0, 8))
        query = tk.StringVar(value=gmail_query_from_target(target))
        query_entry = ttk.Entry(search_row, textvariable=query)
        query_entry.pack(side="left", fill="x", expand=True)
        ttk.Label(
            frame,
            text="Exemples : label:Archives  •  from:adresse@domaine.fr  •  "
            "subject:convention  •  before:2020/01/01  •  in:anywhere",
            foreground="#597089",
        ).pack(anchor="w", pady=(0, 8))
        tree = ttk.Treeview(frame, columns=("correspondent", "date"), show="tree headings", height=14)
        tree.heading("#0", text="Objet")
        tree.heading("correspondent", text="Expéditeur / destinataire")
        tree.heading("date", text="Date")
        tree.column("#0", width=330)
        tree.column("correspondent", width=300)
        tree.column("date", width=180)
        tree.pack(fill="both", expand=True)
        choices = []
        result: tuple[str, str] | None = None

        def search() -> None:
            nonlocal choices
            tree.delete(*tree.get_children())
            try:
                choices = list_gmail_message_choices(email, target, query=query.get())
            except Exception as exc:  # noqa: BLE001 - provider error is actionable to the user.
                messagebox.showinfo(
                    "Gmail", f"Impossible de rechercher les messages.\n\n{exc}", parent=dialog,
                )
                return
            for index, choice in enumerate(choices):
                tree.insert(
                    "", "end", iid=str(index), text=choice.subject,
                    values=(choice.correspondent, choice.date),
                )
            if choices:
                tree.selection_set("0")

        def validate(_event=None) -> None:
            nonlocal result
            selection = tree.selection()
            if selection:
                choice = choices[int(selection[0])]
                result = choice.subject, choice.correspondent
                dialog.destroy()

        tree.bind("<Double-Button-1>", validate)
        query_entry.bind("<Return>", lambda _event: search())
        ttk.Button(search_row, text="Rechercher", command=search).pack(side="left", padx=(8, 0))
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="e", pady=(10, 0))
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="left")
        ttk.Button(buttons, text="Choisir", command=validate).pack(side="left", padx=(6, 0))
        dialog.geometry("950x560")
        search()
        dialog.wait_window()
        return result

    def _show_resource_menu(self, event: tk.Event[tk.Misc]) -> None:
        identifier = self.resource_tree.identify_row(event.y)
        if not identifier:
            return
        if identifier not in self.resource_tree.selection():
            self.resource_tree.selection_set(identifier)
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Ouvrir", command=self._open_resource)
        menu.add_command(label="Ouvrir le dossier Drive lié", command=self._open_linked_drive_folder)
        menu.add_command(label="Déplacer vers un autre espace…", command=self._move_resources_to_space)
        menu.add_command(label="Modifier les tags", command=self._edit_tags)
        menu.add_separator()
        menu.add_command(label="Retirer de l’espace", command=self._remove_resource)
        menu.tk_popup(event.x_root, event.y_root)

    def _populate_space_picker(
        self,
        tree: ttk.Treeview,
        *,
        excluded: set[str] | None = None,
    ) -> None:
        excluded = excluded or set()
        spaces = [
            space for space in self.spaces
            if space.identifier != "inbox" and space.identifier not in excluded
        ]
        by_id = {space.identifier: space for space in spaces}
        children: dict[str, list[CodiSpace]] = {}
        roots: list[CodiSpace] = []
        for space in spaces:
            if space.parent_id in by_id:
                children.setdefault(space.parent_id, []).append(space)
            else:
                roots.append(space)
        groups: dict[str, str] = {}

        def insert_branch(space: CodiSpace, parent: str, ancestry: set[str]) -> None:
            tree.insert(parent, "end", iid=space.identifier, text=space.title, open=True)
            if space.identifier in ancestry:
                return
            for child in children.get(space.identifier, []):
                insert_branch(child, space.identifier, {*ancestry, space.identifier})

        for space in roots:
            group = space.group.strip() or self._default_space_group(space)
            group_id = groups.get(group)
            if group_id is None:
                group_id = f"picker-group:{len(groups)}"
                groups[group] = group_id
                tree.insert("", "end", iid=group_id, text=group, open=True)
            insert_branch(space, group_id, set())

    def _move_resources_to_space(self) -> None:
        source = self._selected_space()
        identifiers = {
            identifier for identifier in self.resource_tree.selection()
            if not identifier.startswith("drive:")
        }
        if not identifiers:
            messagebox.showinfo(
                "Déplacer",
                "Sélectionnez une ou plusieurs ressources enregistrées dans cet espace.",
                parent=self,
            )
            return
        dialog = tk.Toplevel(self)
        dialog.title("Déplacer vers un autre espace")
        dialog.geometry("620x620")
        dialog.minsize(480, 420)
        dialog.transient(self)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"Choisissez la destination de {len(identifiers)} élément(s) :",
            font=("Sans", 13, "bold"),
        ).pack(anchor="w", pady=(0, 10))
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)
        self._populate_space_picker(tree, excluded={source.identifier})
        result: list[str] = []

        def validate(_event=None) -> None:
            selection = tree.selection()
            if not selection or selection[0].startswith("picker-group:"):
                return
            result.append(selection[0])
            dialog.destroy()

        tree.bind("<Double-Button-1>", validate)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Déplacer", command=validate).pack(side="right", padx=(0, 8))
        dialog.wait_window()
        if not result:
            return
        destination = next(
            (space for space in self.spaces if space.identifier == result[0]),
            None,
        )
        if destination is None:
            return
        moved = move_resources_between_spaces(
            self.spaces, source.identifier, destination.identifier, identifiers,
        )
        if not moved:
            return
        save_spaces(self.spaces)
        self._sync_space_index_in_background(source)
        self._sync_space_index_in_background(destination)
        self._refresh_tag_catalog()
        self._refresh_resources(refresh_drive=False)
        self.status.configure(
            text=f"{moved} élément(s) déplacé(s) vers « {destination.title} »."
        )

    def _remove_resource(self) -> None:
        identifiers = set(self.resource_tree.selection())
        if not identifiers:
            return
        drive_identifiers = {identifier for identifier in identifiers if identifier.startswith("drive:")}
        removable = identifiers - drive_identifiers
        if not removable:
            open_folder = messagebox.askyesno(
                "Élément Drive",
                "Ces éléments proviennent directement du dossier lié : ce ne sont pas de vieux "
                "doublons enregistrés dans Lou Còdi.\n\n"
                "Pour les supprimer ou les déplacer, il faut agir dans Google Drive.\n\n"
                "Ouvrir maintenant le dossier Drive lié ?",
                parent=self,
            )
            if open_folder:
                self._open_linked_drive_folder()
            return
        count = len(removable)
        if not messagebox.askyesno(
            "Retirer les ressources",
            f"Retirer {count} élément(s) de cet espace sans supprimer les originaux ?",
            parent=self,
        ):
            return
        space = self._selected_space()
        space.resources = [resource for resource in space.resources if resource.identifier not in removable]
        save_spaces(self.spaces)
        for identifier in removable:
            self._display_resources.pop(identifier, None)
            if self.resource_tree.exists(identifier):
                self.resource_tree.delete(identifier)
        self._refresh_tag_catalog()
        suffix = " Les éléments Drive sélectionnés sont restés en place." if drive_identifiers else ""
        self.status.configure(text=f"{count} élément(s) retiré(s). Synchronisation Drive en arrière-plan…{suffix}")
        self._sync_space_index_in_background(space)

    def _sync_space_index_in_background(self, space: CodiSpace) -> None:
        folder_id = drive_folder_id(space.drive_folder)
        if not folder_id or not space.account_email:
            self.status.configure(text="Modifications enregistrées.")
            return
        links = [
            asdict(resource)
            for resource in space.resources
            if resource.target.startswith(("http://", "https://"))
            and not resource.identifier.startswith("drive:")
        ]

        def synchronize() -> None:
            try:
                save_drive_link_index(
                    space.account_email, folder_id, space.title, space.identifier,
                    space.group, space.parent_id, links,
                )
            except Exception:  # noqa: BLE001 - background retry must never block local removal.
                # The local deletion is already safe. A later save or refresh can retry the Drive index.
                return

        threading.Thread(target=synchronize, daemon=True).start()
