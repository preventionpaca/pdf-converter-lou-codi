from __future__ import annotations

import json
import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote

from ..code_lab_library import (
    LearningPath,
    LearningQuestion,
    build_generation_prompt,
    load_learning_paths,
    parse_learning_path,
    save_learning_path,
)
from ..paths import application_data_directory
from ..telemetry import track_event

NAVY = "#193B66"
BLUE = "#2368AF"
BACKGROUND = "#F0F4F9"
EDITOR_BG = "#FCFCFD"
LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
}


@dataclass
class Exercise:
    title: str
    language: str
    level: str
    code: str
    question: str
    choices: list[str]
    answer: int
    explanation: str


def load_exercises() -> list[Exercise]:
    source = Path(__file__).resolve().parents[1] / "assets" / "code_lab" / "exercises.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    return [
        Exercise(
            title=str(item["title"]),
            language=str(item["language"]),
            level=str(item.get("level", "Débutant")),
            code=str(item["code"]),
            question=str(item["question"]),
            choices=[str(choice) for choice in item["choices"]],
            answer=int(item["answer"]),
            explanation=str(item["explanation"]),
        )
        for item in data
    ]


class CodeEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, *, language: str = "text", path: Path | None = None) -> None:
        super().__init__(master)
        self.path = path
        self.language = language
        self.modified = False
        self._highlight_job: str | None = None
        self.lines = tk.Canvas(self, width=50, bg="#E8EDF3", highlightthickness=0)
        self.lines.pack(side="left", fill="y")
        self.scroll = ttk.Scrollbar(self, orient="vertical")
        self.scroll.pack(side="right", fill="y")
        self.text = tk.Text(
            self,
            wrap="none",
            undo=True,
            maxundo=-1,
            bg=EDITOR_BG,
            fg="#17202A",
            insertbackground="#17202A",
            selectbackground="#B9D8F5",
            font=("JetBrains Mono", 11),
            padx=10,
            pady=8,
            relief="flat",
        )
        self.text.pack(side="left", fill="both", expand=True)
        self.xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.xscroll.pack(side="bottom", fill="x")
        self.text.configure(
            yscrollcommand=self._on_scroll,
            xscrollcommand=self.xscroll.set,
        )
        self.scroll.configure(command=self._scroll_both)
        self.text.bind("<KeyRelease>", self._changed, add=True)
        self.text.bind("<MouseWheel>", lambda _event: self.after_idle(self.redraw_lines), add=True)
        self.text.bind("<Configure>", lambda _event: self.redraw_lines(), add=True)
        self.text.bind("<<Modified>>", self._modified, add=True)
        self._configure_tags()

    def _configure_tags(self) -> None:
        self.text.tag_configure("keyword", foreground="#7A1FA2")
        self.text.tag_configure("string", foreground="#A64200")
        self.text.tag_configure("comment", foreground="#5D7A62", font=("JetBrains Mono", 11, "italic"))
        self.text.tag_configure("number", foreground="#0066A1")
        self.text.tag_configure("tag", foreground="#005FB8")
        self.text.tag_configure("attribute", foreground="#9A4D00")
        self.text.tag_configure("selector", foreground="#7A1FA2")
        self.text.tag_configure("property", foreground="#005FB8")

    def _on_scroll(self, first: str, last: str) -> None:
        self.scroll.set(first, last)
        self.redraw_lines()

    def _scroll_both(self, *args: str) -> None:
        self.text.yview(*args)
        self.redraw_lines()

    def _modified(self, _event: tk.Event[tk.Misc]) -> None:
        if self.text.edit_modified():
            self.modified = True
            self.text.edit_modified(False)
            self.event_generate("<<EditorModified>>")

    def _changed(self, _event: tk.Event[tk.Misc]) -> None:
        self.redraw_lines()
        if self._highlight_job:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(180, self.highlight)

    def set_content(self, content: str, *, language: str | None = None, path: Path | None = None) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        if language:
            self.language = language
        self.path = path
        self.modified = False
        self.text.edit_modified(False)
        self.highlight()
        self.redraw_lines()

    def content(self) -> str:
        return self.text.get("1.0", "end-1c")

    def redraw_lines(self) -> None:
        self.lines.delete("all")
        index = self.text.index("@0,0")
        while True:
            info = self.text.dlineinfo(index)
            if info is None:
                break
            y = info[1]
            number = str(index).split(".")[0]
            self.lines.create_text(42, y, anchor="ne", text=number, fill="#66788A", font=("JetBrains Mono", 10))
            index = self.text.index(f"{index}+1line")

    def _apply_regex(self, tag: str, pattern: str, flags: int = 0) -> None:
        content = self.content()
        for match in re.finditer(pattern, content, flags):
            self.text.tag_add(tag, f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def highlight(self) -> None:
        self._highlight_job = None
        for tag in ("keyword", "string", "comment", "number", "tag", "attribute", "selector", "property"):
            self.text.tag_remove(tag, "1.0", "end")
        language = self.language
        if language == "python":
            words = "and|as|assert|async|await|break|class|continue|def|del|elif|else|except|False|finally|for|from|global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|try|while|with|yield"
            self._apply_regex("keyword", rf"\b(?:{words})\b")
            self._apply_regex("comment", r"#.*$")
        elif language == "javascript":
            words = "async|await|break|case|catch|class|const|continue|default|delete|do|else|export|extends|false|finally|for|from|function|if|import|in|instanceof|let|new|null|of|return|switch|this|throw|true|try|typeof|undefined|var|while"
            self._apply_regex("keyword", rf"\b(?:{words})\b")
            self._apply_regex("comment", r"//.*$|/\*[\s\S]*?\*/", re.MULTILINE)
        elif language == "html":
            self._apply_regex("comment", r"<!--[\s\S]*?-->")
            self._apply_regex("tag", r"</?[A-Za-z][^>]*>")
            self._apply_regex("attribute", r"\b[A-Za-z_:][-A-Za-z0-9_:.]*(?=\s*=)")
        elif language == "css":
            self._apply_regex("comment", r"/\*[\s\S]*?\*/")
            self._apply_regex("selector", r"(?:^|})\s*([^@{}][^{]+)(?=\{)", re.MULTILINE)
            self._apply_regex("property", r"\b[-A-Za-z]+(?=\s*:)")
        self._apply_regex("string", r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
        self._apply_regex("number", r"\b\d+(?:\.\d+)?\b")


class LearningPathWindow(tk.Toplevel):
    MODE_LABELS = {"assisted": "Assisté", "autonomous": "Autonome", "challenge": "Défi"}
    LABEL_MODES = {label: mode for mode, label in MODE_LABELS.items()}

    def __init__(self, master: tk.Misc, path: LearningPath) -> None:
        super().__init__(master, class_="Loucodiworkshop")
        self.path = path
        self.title(f"Parcours · {path.title}")
        self.geometry("1180x760")
        self.minsize(900, 620)
        self.configure(bg=BACKGROUND)
        self.mode = tk.StringVar(value="Assisté")
        self.question_index = 0
        self.answer_choice = tk.StringVar()
        self.free_answer: tk.Text | None = None
        self.progress_file = application_data_directory() / "code-lab" / "progress.json"
        self.progress = self._load_progress()
        self._build()
        self._show_question()

    def _load_progress(self) -> dict[str, list[str]]:
        try:
            value = json.loads(self.progress_file.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_progress(self) -> None:
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        self.progress_file.write_text(json.dumps(self.progress, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, padx=18, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=self.path.title, bg=NAVY, fg="white", font=("Sans", 18, "bold")).pack(side="left")
        concepts = " · ".join(self.path.concepts) or self.path.language
        tk.Label(header, text=concepts, bg=NAVY, fg="#CBDFF5", font=("Sans", 9)).pack(side="left", padx=18)
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=14)
        panel = ttk.Frame(body, padding=12)
        editor_panel = ttk.Frame(body)
        body.add(panel, weight=2)
        body.add(editor_panel, weight=3)
        ttk.Label(panel, text="Mode d’apprentissage", font=("Sans", 12, "bold"), foreground=NAVY).pack(anchor="w")
        mode_box = ttk.Combobox(panel, textvariable=self.mode, state="readonly", values=list(self.LABEL_MODES))
        mode_box.pack(fill="x", pady=(6, 10))
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._change_mode())
        mode_box.set("Assisté")
        self.mode_caption = tk.StringVar()
        ttk.Label(panel, textvariable=self.mode_caption, font=("Sans", 11, "bold"), foreground=BLUE, wraplength=360).pack(anchor="w", pady=4)
        self.objective = tk.StringVar()
        ttk.Label(panel, textvariable=self.objective, wraplength=360, justify="left").pack(anchor="w", pady=(0, 10))
        self.progress_caption = tk.StringVar()
        ttk.Label(panel, textvariable=self.progress_caption, foreground="#5C6F82").pack(anchor="w", pady=(0, 8))
        self.prompt = tk.StringVar()
        ttk.Label(panel, textvariable=self.prompt, wraplength=360, justify="left", font=("Sans", 11, "bold")).pack(anchor="w", pady=8)
        self.answer_frame = ttk.Frame(panel)
        self.answer_frame.pack(fill="both", expand=True)
        controls = ttk.Frame(panel)
        controls.pack(fill="x", pady=8)
        ttk.Button(controls, text="← Précédente", command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(controls, text="Suivante →", command=lambda: self._move(1)).pack(side="right")
        self.action_button = ttk.Button(panel, text="Vérifier", command=self._act)
        self.action_button.pack(fill="x", pady=4)
        self.hint_button = ttk.Button(panel, text="Afficher un indice", command=self._show_hint)
        self.hint_button.pack(fill="x", pady=4)
        self.feedback = tk.StringVar()
        ttk.Label(panel, textvariable=self.feedback, wraplength=360, justify="left", foreground="#176B3A").pack(anchor="w", pady=8)
        self.editor = CodeEditor(editor_panel, language=self.path.language)
        self.editor.pack(fill="both", expand=True)
        self.editor.set_content(self.path.code, language=self.path.language)

    def _stage(self):
        mode = self.LABEL_MODES.get(self.mode.get(), "assisted")
        return next((stage for stage in self.path.stages if stage.mode == mode), self.path.stages[0])

    def _question(self) -> LearningQuestion:
        stage = self._stage()
        self.question_index = min(self.question_index, len(stage.questions) - 1)
        return stage.questions[self.question_index]

    def _change_mode(self) -> None:
        self.question_index = 0
        self._show_question()

    def _show_question(self) -> None:
        stage = self._stage()
        question = self._question()
        self.mode_caption.set(f"{self.MODE_LABELS[stage.mode]} · {stage.title}")
        self.objective.set(stage.objective)
        completed = set(self.progress.get(self.path.identifier, []))
        key = f"{stage.mode}:{self.question_index}"
        marker = " · terminée ✓" if key in completed else ""
        self.progress_caption.set(f"Question {self.question_index + 1}/{len(stage.questions)}{marker}")
        self.prompt.set(question.prompt)
        self.feedback.set("")
        self.answer_choice.set("")
        for child in self.answer_frame.winfo_children():
            child.destroy()
        self.free_answer = None
        if question.kind == "qcm":
            for choice in question.choices:
                ttk.Radiobutton(self.answer_frame, text=choice, variable=self.answer_choice, value=choice).pack(anchor="w", pady=3)
            self.action_button.configure(text="Vérifier ma réponse")
        else:
            self.free_answer = tk.Text(self.answer_frame, height=6, wrap="word", font=("Sans", 10))
            self.free_answer.pack(fill="both", expand=True, pady=4)
            self.action_button.configure(text="Comparer avec la correction" if stage.mode == "autonomous" else "Valider mon défi")
        if stage.mode == "assisted" and question.hint:
            self.hint_button.pack(fill="x", pady=4)
        else:
            self.hint_button.pack_forget()

    def _move(self, delta: int) -> None:
        count = len(self._stage().questions)
        self.question_index = max(0, min(count - 1, self.question_index + delta))
        self._show_question()

    def _show_hint(self) -> None:
        self.feedback.set("Indice : " + (self._question().hint or "Relisez la partie concernée du script."))

    def _mark_complete(self) -> None:
        key = f"{self._stage().mode}:{self.question_index}"
        completed = self.progress.setdefault(self.path.identifier, [])
        if key not in completed:
            completed.append(key)
            self._save_progress()

    def _act(self) -> None:
        question = self._question()
        if question.kind == "qcm":
            if self.answer_choice.get().strip().casefold() != question.answer.strip().casefold():
                self.feedback.set("Pas encore. Observez le script et réessayez.")
                return
            self._mark_complete()
            self.feedback.set("Bonne réponse. " + question.explanation)
        else:
            response = self.free_answer.get("1.0", "end-1c").strip() if self.free_answer else ""
            if not response and self._stage().mode != "challenge":
                self.feedback.set("Écrivez d’abord votre réponse.")
                return
            label = "Critères de réussite" if self._stage().mode == "challenge" else "Réponse attendue"
            self._mark_complete()
            self.feedback.set(f"{label} : {question.answer}\n{question.explanation}".strip())
        self.progress_caption.set(self.progress_caption.get().split(" ·")[0] + " · terminée ✓")
        track_event("code_lab", "quiz", "ok", language=self.path.language)


class CodeLabWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, class_="Loucodiworkshop")
        self.title("Lou Còdi Code Lab")
        self.geometry("1280x820")
        self.minsize(980, 650)
        self.configure(bg=BACKGROUND)
        self.exercises = load_exercises()
        self.learning_paths = load_learning_paths()
        self.editors: dict[str, CodeEditor] = {}
        self._untitled = 0
        self._build()
        self.new_file()
        track_event("code_lab", "open")

    def _build(self) -> None:
        header = tk.Frame(self, bg=NAVY, padx=18, pady=13)
        header.pack(fill="x")
        tk.Label(header, text="Lou Còdi Code Lab", bg=NAVY, fg="white", font=("Sans", 20, "bold")).pack(side="left")
        tk.Label(header, text="COMPRENDRE · EXPÉRIMENTER · MODIFIER · CRÉER", bg=NAVY, fg="#CBDFF5", font=("Sans", 9)).pack(side="left", padx=18)
        for text, command in (("Nouveau", self.new_file), ("Ouvrir", self.open_file), ("Enregistrer", self.save_file), ("Enregistrer sous", lambda: self.save_file(save_as=True)), ("Fermer l’onglet", self.close_tab)):
            tk.Button(header, text=text, command=command, bg="#28507D", fg="white", relief="flat", padx=10, pady=7).pack(side="right", padx=3)
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=14)
        lessons = ttk.Frame(body, padding=12)
        workspace = ttk.Frame(body)
        body.add(lessons, weight=1)
        body.add(workspace, weight=4)
        ttk.Label(lessons, text="Exercices guidés", font=("Sans", 14, "bold"), foreground=NAVY).pack(anchor="w")
        self.exercise_list = tk.Listbox(lessons, exportselection=False, height=10)
        self.exercise_list.pack(fill="x", pady=(10, 12))
        for exercise in self.exercises:
            self.exercise_list.insert("end", f"{exercise.level} · {exercise.title}")
        self.exercise_list.bind("<<ListboxSelect>>", self._select_exercise)
        ttk.Label(lessons, text="Mes parcours", font=("Sans", 12, "bold"), foreground=NAVY).pack(anchor="w", pady=(2, 3))
        self.path_list = tk.Listbox(lessons, exportselection=False, height=4)
        self.path_list.pack(fill="x", pady=(0, 5))
        self.path_list.bind("<Double-Button-1>", self._open_learning_path)
        ttk.Button(lessons, text="Ouvrir le parcours sélectionné", command=self._open_learning_path).pack(fill="x", pady=2)
        self._refresh_path_list()
        ttk.Button(lessons, text="Générer un parcours avec ChatGPT", command=self.generate_learning_path).pack(fill="x", pady=(8, 2))
        ttk.Button(lessons, text="Importer la réponse", command=self.import_learning_path).pack(fill="x", pady=(2, 10))
        self.question = tk.StringVar(value="Choisissez un exercice.")
        ttk.Label(lessons, textvariable=self.question, wraplength=270, justify="left").pack(anchor="w", pady=(4, 8))
        self.answer = tk.IntVar(value=-1)
        self.choice_frame = ttk.Frame(lessons)
        self.choice_frame.pack(fill="x")
        ttk.Button(lessons, text="Vérifier ma réponse", command=self.check_answer).pack(fill="x", pady=(12, 5))
        ttk.Button(lessons, text="Expliquer avec ChatGPT", command=self.prepare_chatgpt).pack(fill="x", pady=5)
        self.feedback = tk.StringVar()
        ttk.Label(lessons, textvariable=self.feedback, wraplength=270, justify="left", foreground="#176B3A").pack(anchor="w", pady=10)
        ttk.Separator(lessons).pack(fill="x", pady=10)
        ttk.Label(lessons, text="Ressources libres", font=("Sans", 12, "bold"), foreground=NAVY).pack(anchor="w")
        for label, url in (("MDN Web Docs", "https://developer.mozilla.org/fr/"), ("Python — tutoriel officiel", "https://docs.python.org/fr/3/tutorial/"), ("JavaScript.info", "https://fr.javascript.info/")):
            ttk.Button(lessons, text=label, command=lambda target=url: webbrowser.open(target)).pack(fill="x", pady=3)
        self.notebook = ttk.Notebook(workspace)
        self.notebook.pack(fill="both", expand=True)
        self.status = tk.StringVar(value="Prêt")
        ttk.Label(workspace, textvariable=self.status, anchor="w").pack(fill="x", pady=(5, 0))
        self.bind("<Control-n>", lambda _event: self.new_file())
        self.bind("<Control-o>", lambda _event: self.open_file())
        self.bind("<Control-s>", lambda _event: self.save_file())

    def _current(self) -> CodeEditor | None:
        tab = self.notebook.select()
        return self.editors.get(tab)

    def _tab_title(self, editor: CodeEditor) -> str:
        name = editor.path.name if editor.path else f"Sans titre {getattr(editor, 'untitled_number', 1)}"
        return f"{name}{' •' if editor.modified else ''}"

    def _add_editor(self, *, content: str = "", language: str = "text", path: Path | None = None) -> CodeEditor:
        editor = CodeEditor(self.notebook, language=language, path=path)
        self._untitled += 1
        editor.untitled_number = self._untitled  # type: ignore[attr-defined]
        editor.set_content(content, language=language, path=path)
        self.notebook.add(editor, text=self._tab_title(editor))
        tab = str(editor)
        self.editors[tab] = editor
        editor.bind("<<EditorModified>>", lambda _event, item=editor: self.notebook.tab(item, text=self._tab_title(item)))
        self.notebook.select(editor)
        editor.text.focus_set()
        return editor

    def new_file(self) -> None:
        self._add_editor()
        self.status.set("Nouveau fichier")

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(parent=self, filetypes=[("Code", "*.py *.js *.mjs *.html *.htm *.css"), ("Tous les fichiers", "*")])
        if not filename:
            return
        path = Path(filename)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Ouverture impossible", str(exc), parent=self)
            return
        self._add_editor(content=content, language=LANGUAGES.get(path.suffix.lower(), "text"), path=path)
        self.status.set(str(path))

    def save_file(self, *, save_as: bool = False) -> None:
        editor = self._current()
        if editor is None:
            return
        path = editor.path
        if save_as or path is None:
            filename = filedialog.asksaveasfilename(parent=self, defaultextension=".py", filetypes=[("Python", "*.py"), ("JavaScript", "*.js"), ("HTML", "*.html"), ("CSS", "*.css"), ("Tous les fichiers", "*")])
            if not filename:
                return
            path = Path(filename)
        try:
            path.write_text(editor.content(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Enregistrement impossible", str(exc), parent=self)
            return
        editor.path = path
        editor.language = LANGUAGES.get(path.suffix.lower(), editor.language)
        editor.modified = False
        editor.highlight()
        self.notebook.tab(editor, text=self._tab_title(editor))
        self.status.set(f"Enregistré : {path}")

    def close_tab(self) -> None:
        editor = self._current()
        if editor is None:
            return
        if editor.modified and not messagebox.askyesno("Fermer l’onglet", "Les modifications ne sont pas enregistrées. Fermer quand même ?", parent=self):
            return
        self.editors.pop(str(editor), None)
        self.notebook.forget(editor)
        editor.destroy()
        if not self.notebook.tabs():
            self.new_file()

    def _select_exercise(self, _event: tk.Event[tk.Misc]) -> None:
        selection = self.exercise_list.curselection()
        if not selection:
            return
        exercise = self.exercises[selection[0]]
        self._add_editor(content=exercise.code, language=exercise.language)
        self.question.set(exercise.question)
        self.answer.set(-1)
        self.feedback.set("")
        for child in self.choice_frame.winfo_children():
            child.destroy()
        for index, choice in enumerate(exercise.choices):
            ttk.Radiobutton(self.choice_frame, text=choice, variable=self.answer, value=index).pack(anchor="w", pady=2)

    def check_answer(self) -> None:
        selection = self.exercise_list.curselection()
        if not selection:
            self.feedback.set("Choisissez d’abord un exercice.")
            return
        exercise = self.exercises[selection[0]]
        if self.answer.get() == exercise.answer:
            self.feedback.set("Bonne réponse ! " + exercise.explanation)
            track_event("code_lab", "quiz", "ok", language=exercise.language)
        else:
            self.feedback.set("Pas encore. Relisez le code ligne par ligne et réessayez.")
            track_event("code_lab", "quiz", "retry", language=exercise.language)

    def prepare_chatgpt(self) -> None:
        editor = self._current()
        if editor is None:
            return
        prompt = (
            "Tu es un animateur patient d’un club de programmation. Explique en français le script "
            f"{editor.language} ci-dessous, ligne par ligne, puis propose trois questions progressives "
            "sans donner immédiatement les réponses. Ne modifie pas le code.\n\n"
            "```\n" + editor.content() + "\n```"
        )
        self.clipboard_clear()
        self.clipboard_append(prompt)
        self.update()
        # ChatGPT accepts a pre-filled composer through the `q` query parameter.
        # Keep the clipboard copy as a reliable fallback for very long scripts or
        # browsers that strip the query while redirecting to the authenticated page.
        encoded = quote(prompt)
        target = "https://chatgpt.com/?q=" + encoded if len(encoded) <= 6000 else "https://chatgpt.com/"
        opened = webbrowser.open(target, new=2)
        if opened:
            self.status.set("Prompt envoyé à ChatGPT. Il reste aussi copié dans le presse-papiers.")
        else:
            messagebox.showinfo(
                "Expliquer avec ChatGPT",
                "Le navigateur n’a pas pu être ouvert. Le prompt est copié : ouvrez ChatGPT et collez-le avec Ctrl+V.",
                parent=self,
            )
            self.status.set("Prompt copié dans le presse-papiers.")

    def generate_learning_path(self) -> None:
        editor = self._current()
        if editor is None or not editor.content().strip():
            messagebox.showinfo("Créer un parcours", "Collez ou ouvrez d’abord un script dans l’éditeur.", parent=self)
            return
        prompt = build_generation_prompt(editor.content(), editor.language)
        self.clipboard_clear()
        self.clipboard_append(prompt)
        self.update()
        encoded = quote(prompt)
        target = "https://chatgpt.com/?q=" + encoded if len(encoded) <= 6000 else "https://chatgpt.com/"
        webbrowser.open(target, new=2)
        self.status.set("Demande de parcours ouverte dans ChatGPT. Copiez ensuite sa réponse JSON.")
        messagebox.showinfo(
            "Créer un parcours",
            "ChatGPT va produire un parcours progressif en trois modes.\n\n"
            "Quand la réponse est terminée, copiez tout le JSON puis revenez ici et cliquez sur « Importer la réponse ».",
            parent=self,
        )

    def import_learning_path(self) -> None:
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            messagebox.showerror("Importer la réponse", "Le presse-papiers ne contient pas de texte.", parent=self)
            return
        try:
            path = parse_learning_path(raw)
        except ValueError as exc:
            messagebox.showerror("Parcours non valide", str(exc), parent=self)
            return
        counts = {mode: sum(len(stage.questions) for stage in path.stages if stage.mode == mode) for mode in ("assisted", "autonomous", "challenge")}
        preview = (
            f"Titre : {path.title}\nLangage : {path.language}\nNiveau : {path.level}\n"
            f"Concepts : {', '.join(path.concepts) or 'non précisés'}\n\n"
            f"Questions assistées : {counts['assisted']}\n"
            f"Questions autonomes : {counts['autonomous']}\n"
            f"Défis : {counts['challenge']}\n\n"
            "Valider et enregistrer ce parcours dans la bibliothèque locale ?"
        )
        if not messagebox.askyesno("Validation humaine du parcours", preview, parent=self):
            self.status.set("Import annulé : rien n’a été enregistré.")
            return
        target = save_learning_path(path)
        self.learning_paths = load_learning_paths()
        self._refresh_path_list()
        self.status.set(f"Parcours validé et enregistré localement : {target.name}")
        track_event("code_lab", "quiz", "path_imported", language=path.language)
        LearningPathWindow(self, path)

    def _refresh_path_list(self) -> None:
        self.path_list.delete(0, "end")
        for path in self.learning_paths:
            self.path_list.insert("end", f"{path.level} · {path.title}")

    def _open_learning_path(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.path_list.curselection()
        if not selection:
            return
        LearningPathWindow(self, self.learning_paths[selection[0]])
