from __future__ import annotations

import json
import re
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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


class CodeLabWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, class_="Loucodiworkshop")
        self.title("Lou Còdi Code Lab")
        self.geometry("1280x820")
        self.minsize(980, 650)
        self.configure(bg=BACKGROUND)
        self.exercises = load_exercises()
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
        webbrowser.open("https://chatgpt.com/")
        self.status.set("Prompt copié : collez-le dans ChatGPT.")
