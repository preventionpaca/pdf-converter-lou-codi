from __future__ import annotations

import webbrowser
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from ..services.google_mail import (
    GoogleMailUnavailable,
    active_account,
    list_accounts,
    list_drive_folder,
    set_active_account,
)
from ..space_library import (
    CodiSpace,
    SpaceResource,
    load_spaces,
    new_identifier,
    save_spaces,
    space_deletion_blocker,
)
from ..system import open_path
from .windowing import maximize_window

NAVY = "#193B66"
BLUE = "#2368AF"
BACKGROUND = "#F0F4F9"

RESOURCE_KINDS = {
    "Fichier local": "local_file",
    "Dossier local": "local_folder",
    "Dossier Google Drive": "google_drive_folder",
    "Document Google Drive": "google_drive_document",
    "Album Google Photos": "google_photos_album",
    "Courriel Gmail": "gmail_message",
    "Lien Internet ou vidéo": "web_link",
}


def drive_folder_id(value: str) -> str:
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    return value.strip() if re.fullmatch(r"[A-Za-z0-9_-]{10,}", value.strip()) else ""


class CodiSpaceWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, class_="Loucodiworkshop")
        self.title("Còdi Espace — Lou Còdi Workshop")
        self.geometry("1220x780")
        self.minsize(980, 620)
        self.configure(bg=BACKGROUND)
        self.spaces = load_spaces()
        self.current_space_id = "inbox"
        self.account = tk.StringVar(value=active_account())
        self.search = tk.StringVar()
        self._display_resources: dict[str, SpaceResource] = {}
        self._build()
        self._refresh_spaces()
        maximize_window(self)

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, padx=22, pady=15)
        header.pack(fill="x")
        tk.Label(header, text="Còdi Espace", bg=NAVY, fg="white", font=("Sans", 22, "bold")).pack(side="left")
        tk.Label(
            header,
            text="RELIER DOCUMENTS, DRIVE, COURRIELS, LIENS ET ALBUMS PHOTOS",
            bg=NAVY,
            fg="#CBDFF5",
            font=("Sans", 9),
        ).pack(side="left", padx=18)
        accounts = [account.email for account in list_accounts()]
        account_box = ttk.Combobox(header, textvariable=self.account, values=accounts, state="readonly", width=34)
        account_box.pack(side="right")
        account_box.bind("<<ComboboxSelected>>", self._account_changed)
        tk.Label(header, text="Compte Google", bg=NAVY, fg="white").pack(side="right", padx=8)

        toolbar = ttk.Frame(self, padding=(14, 10))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="+ Nouvel espace", command=self._new_space).pack(side="left")
        ttk.Button(toolbar, text="Supprimer l’espace", command=self._delete_space).pack(side="left", padx=6)
        ttk.Button(toolbar, text="+ Ajouter une ressource", command=self._add_resource).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Lier un dossier Drive", command=self._link_drive_folder).pack(side="left")
        ttk.Button(toolbar, text="Actualiser Drive", command=self._refresh_resources).pack(side="left", padx=6)
        ttk.Entry(toolbar, textvariable=self.search, width=34).pack(side="right")
        ttk.Label(toolbar, text="Rechercher").pack(side="right", padx=6)
        self.search.trace_add("write", lambda *_args: self._refresh_resources())

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        left = ttk.Frame(panes, padding=10)
        right = ttk.Frame(panes, padding=10)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        ttk.Label(left, text="Mes espaces", font=("Sans", 15, "bold")).pack(anchor="w", pady=(0, 8))
        self.space_tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.space_tree.pack(fill="both", expand=True)
        self.space_tree.bind("<<TreeviewSelect>>", self._select_space)

        self.space_title = tk.StringVar(value="À classer")
        ttk.Label(right, textvariable=self.space_title, font=("Sans", 17, "bold")).pack(anchor="w")
        self.space_detail = tk.StringVar()
        ttk.Label(right, textvariable=self.space_detail, foreground="#597089").pack(anchor="w", pady=(2, 10))
        columns = ("kind", "tags", "account", "target")
        self.resource_tree = ttk.Treeview(right, columns=columns, show="tree headings", selectmode="browse")
        self.resource_tree.heading("#0", text="Titre")
        self.resource_tree.heading("kind", text="Type")
        self.resource_tree.heading("tags", text="Tags")
        self.resource_tree.heading("account", text="Compte")
        self.resource_tree.heading("target", text="Emplacement")
        self.resource_tree.column("#0", width=220)
        self.resource_tree.column("kind", width=145)
        self.resource_tree.column("tags", width=150)
        self.resource_tree.column("account", width=210)
        self.resource_tree.column("target", width=360)
        self.resource_tree.pack(fill="both", expand=True)
        self.resource_tree.bind("<Double-Button-1>", lambda _event: self._open_resource())
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Ouvrir", command=self._open_resource).pack(side="left")
        ttk.Button(actions, text="Modifier les tags", command=self._edit_tags).pack(side="left", padx=6)
        ttk.Button(actions, text="Retirer de l’espace", command=self._remove_resource).pack(side="left")
        self.status = ttk.Label(actions, text="Les éléments restent à leur emplacement d’origine.")
        self.status.pack(side="right")

    def _selected_space(self) -> CodiSpace:
        return next((space for space in self.spaces if space.identifier == self.current_space_id), self.spaces[0])

    def _refresh_spaces(self) -> None:
        self.space_tree.delete(*self.space_tree.get_children())
        for space in self.spaces:
            self.space_tree.insert("", "end", iid=space.identifier, text=space.title)
        if self.space_tree.exists(self.current_space_id):
            self.space_tree.selection_set(self.current_space_id)
        self._refresh_resources()

    def _refresh_resources(self) -> None:
        space = self._selected_space()
        self.space_title.set(space.title)
        details = [f"Compte : {space.account_email or 'non défini'}"]
        if space.drive_folder:
            details.append("dossier Drive lié")
        self.space_detail.set("  •  ".join(details))
        self.resource_tree.delete(*self.resource_tree.get_children())
        self._display_resources = {resource.identifier: resource for resource in space.resources}
        needle = self.search.get().casefold().strip()
        for resource in space.resources:
            haystack = f"{resource.title} {' '.join(resource.tags)} {resource.target}".casefold()
            if needle and needle not in haystack:
                continue
            label = next((name for name, kind in RESOURCE_KINDS.items() if kind == resource.kind), resource.kind)
            self.resource_tree.insert(
                "", "end", iid=resource.identifier, text=resource.title,
                values=(label, ", ".join(resource.tags), resource.account_email, resource.target),
            )
        if space.drive_folder and space.account_email:
            folder_id = drive_folder_id(space.drive_folder)
            if not folder_id:
                self.status.configure(text="L’adresse du dossier Drive n’est pas reconnue.")
                return
            try:
                drive_items = list_drive_folder(space.account_email, folder_id)
            except (GoogleMailUnavailable, OSError, ValueError) as exc:
                self.status.configure(text=str(exc))
                return
            except Exception as exc:
                message = str(exc)
                if "SERVICE_DISABLED" in message or "accessNotConfigured" in message:
                    message = "Activez Google Drive API dans le projet loucodi-workshop, puis réessayez."
                self.status.configure(text=message)
                return
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
                    "", "end", iid=identifier, text=resource.title,
                    values=(label, "", resource.account_email, resource.target),
                )
            self.status.configure(text=f"Dossier Drive actualisé : {len(drive_items)} élément(s).")

    def _save(self) -> None:
        save_spaces(self.spaces)
        self._refresh_spaces()

    def _account_changed(self, _event=None) -> None:
        if self.account.get():
            set_active_account(self.account.get())

    def _select_space(self, _event=None) -> None:
        selection = self.space_tree.selection()
        if selection:
            self.current_space_id = selection[0]
            self._refresh_resources()

    def _new_space(self) -> None:
        title = simpledialog.askstring("Nouvel espace", "Nom de l’espace", parent=self)
        if not title or not title.strip():
            return
        space = CodiSpace(new_identifier(), title.strip(), account_email=self.account.get())
        self.spaces.append(space)
        self.current_space_id = space.identifier
        self._save()

    def _delete_space(self) -> None:
        space = self._selected_space()
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
        value = simpledialog.askstring(
            "Dossier Google Drive",
            "Collez l’adresse du dossier Drive à utiliser pour cet espace.",
            initialvalue=space.drive_folder,
            parent=self,
        )
        if value is None:
            return
        space.drive_folder = value.strip()
        space.account_email = self.account.get() or space.account_email
        self._save()

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
            else:
                ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)

        def browse() -> None:
            if kind_name.get() == "Fichier local":
                value = filedialog.askopenfilename(parent=dialog)
            else:
                value = filedialog.askdirectory(parent=dialog)
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
        if resource.target.startswith(("http://", "https://")):
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
                "Les tags des éléments synchronisés depuis Drive ne sont pas encore modifiables dans Còdi Espace.",
                parent=self,
            )
            return
        value = simpledialog.askstring(
            "Tags", "Tags séparés par des virgules", initialvalue=", ".join(resource.tags), parent=self
        )
        if value is not None:
            resource.tags = [tag.strip() for tag in value.split(",") if tag.strip()]
            self._save()

    def _remove_resource(self) -> None:
        resource = self._selected_resource()
        if resource is None:
            return
        if resource.identifier.startswith("drive:"):
            messagebox.showinfo(
                "Élément Drive",
                "Cet élément provient directement du dossier lié. Retirez-le depuis Google Drive.",
                parent=self,
            )
            return
        if messagebox.askyesno("Retirer la ressource", "La retirer de cet espace sans supprimer l’original ?", parent=self):
            self._selected_space().resources.remove(resource)
            self._save()
