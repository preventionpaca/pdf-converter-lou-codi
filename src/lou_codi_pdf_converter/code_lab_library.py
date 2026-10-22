from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import application_data_directory


MODES = ("assisted", "autonomous", "challenge")


@dataclass(frozen=True)
class LearningQuestion:
    prompt: str
    kind: str
    choices: tuple[str, ...]
    answer: str
    hint: str
    explanation: str


@dataclass(frozen=True)
class LearningStage:
    title: str
    mode: str
    objective: str
    questions: tuple[LearningQuestion, ...]


@dataclass(frozen=True)
class LearningPath:
    identifier: str
    title: str
    language: str
    level: str
    code: str
    concepts: tuple[str, ...]
    stages: tuple[LearningStage, ...]


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"Le champ « {label} » est obligatoire.")
    return result


def parse_learning_path(raw: str | dict[str, Any]) -> LearningPath:
    """Validate a generated path. Untrusted ChatGPT output never reaches the UI unchecked."""
    if isinstance(raw, str):
        cleaned = raw.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"La réponse n’est pas un JSON valide (ligne {exc.lineno}).") from exc
    else:
        data = raw
    if not isinstance(data, dict):
        raise ValueError("Le parcours doit être un objet JSON.")

    title = _text(data.get("title"), "title")
    language = _text(data.get("language"), "language").lower()
    level = _text(data.get("level", "Progressif"), "level")
    code = _text(data.get("code"), "code")
    concepts_value = data.get("concepts", [])
    if not isinstance(concepts_value, list):
        raise ValueError("« concepts » doit être une liste.")
    concepts = tuple(str(item).strip() for item in concepts_value if str(item).strip())

    stages_value = data.get("stages")
    if not isinstance(stages_value, list) or not stages_value:
        raise ValueError("Le parcours doit contenir des étapes.")
    stages: list[LearningStage] = []
    seen_modes: set[str] = set()
    for stage_index, stage_value in enumerate(stages_value, 1):
        if not isinstance(stage_value, dict):
            raise ValueError(f"L’étape {stage_index} est invalide.")
        mode = _text(stage_value.get("mode"), "mode").lower()
        if mode not in MODES:
            raise ValueError(f"Mode inconnu à l’étape {stage_index} : {mode}.")
        questions_value = stage_value.get("questions")
        if not isinstance(questions_value, list) or not questions_value:
            raise ValueError(f"L’étape {stage_index} doit contenir des questions.")
        questions: list[LearningQuestion] = []
        for question_index, question_value in enumerate(questions_value, 1):
            if not isinstance(question_value, dict):
                raise ValueError(f"Question {question_index} de l’étape {stage_index} invalide.")
            kind = str(question_value.get("type", "open")).strip().lower()
            if kind not in {"qcm", "open", "code"}:
                raise ValueError(f"Type de question inconnu : {kind}.")
            choices_value = question_value.get("choices", [])
            if not isinstance(choices_value, list):
                raise ValueError("« choices » doit être une liste.")
            choices = tuple(str(choice).strip() for choice in choices_value if str(choice).strip())
            if kind == "qcm" and len(choices) < 2:
                raise ValueError("Une question QCM doit proposer au moins deux choix.")
            questions.append(
                LearningQuestion(
                    prompt=_text(question_value.get("prompt"), "prompt"),
                    kind=kind,
                    choices=choices,
                    answer=_text(question_value.get("answer"), "answer"),
                    hint=str(question_value.get("hint", "")).strip(),
                    explanation=str(question_value.get("explanation", "")).strip(),
                )
            )
        stages.append(
            LearningStage(
                title=_text(stage_value.get("title"), "stage.title"),
                mode=mode,
                objective=_text(stage_value.get("objective"), "stage.objective"),
                questions=tuple(questions),
            )
        )
        seen_modes.add(mode)
    missing = set(MODES) - seen_modes
    if missing:
        raise ValueError("Le parcours doit couvrir les modes assisté, autonome et défi.")

    canonical_data = dict(data)
    canonical_data.pop("id", None)
    canonical = json.dumps(canonical_data, ensure_ascii=False, sort_keys=True)
    identifier = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return LearningPath(identifier, title, language, level, code, concepts, tuple(stages))


def learning_path_to_dict(path: LearningPath) -> dict[str, Any]:
    return {
        "id": path.identifier,
        "title": path.title,
        "language": path.language,
        "level": path.level,
        "code": path.code,
        "concepts": list(path.concepts),
        "stages": [
            {
                "title": stage.title,
                "mode": stage.mode,
                "objective": stage.objective,
                "questions": [
                    {
                        "prompt": question.prompt,
                        "type": question.kind,
                        "choices": list(question.choices),
                        "answer": question.answer,
                        "hint": question.hint,
                        "explanation": question.explanation,
                    }
                    for question in stage.questions
                ],
            }
            for stage in path.stages
        ],
    }


def library_directory(root: Path | None = None) -> Path:
    directory = (root or application_data_directory()) / "code-lab" / "library"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_learning_path(path: LearningPath, root: Path | None = None) -> Path:
    target = library_directory(root) / f"{path.identifier}.json"
    target.write_text(json.dumps(learning_path_to_dict(path), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_learning_paths(root: Path | None = None) -> list[LearningPath]:
    paths: list[LearningPath] = []
    for source in sorted(library_directory(root).glob("*.json")):
        try:
            paths.append(parse_learning_path(source.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return paths


def build_generation_prompt(code: str, language: str) -> str:
    schema = {
        "title": "Titre du parcours",
        "language": language,
        "level": "Progressif",
        "code": code,
        "concepts": ["concept 1", "concept 2"],
        "stages": [
            {
                "title": "Étape 1",
                "mode": "assisted",
                "objective": "Objectif précis",
                "questions": [{"prompt": "Question", "type": "qcm", "choices": ["A", "B", "C"], "answer": "A", "hint": "Indice", "explanation": "Pourquoi"}],
            },
            {
                "title": "Étape autonome",
                "mode": "autonomous",
                "objective": "Comprendre sans indice",
                "questions": [{"prompt": "Question ouverte", "type": "open", "choices": [], "answer": "Réponse attendue", "hint": "", "explanation": "Correction"}],
            },
            {
                "title": "Défi final",
                "mode": "challenge",
                "objective": "Modifier ou compléter le code",
                "questions": [{"prompt": "Consigne de code", "type": "code", "choices": [], "answer": "Critères de réussite", "hint": "", "explanation": "Solution expliquée"}],
            },
        ],
    }
    return (
        "Tu es un pédagogue expert en programmation. À partir du script fourni, crée un parcours "
        "progressif qui conduit à la compréhension de l’ensemble. Couvre obligatoirement trois modes : "
        "assisted (indices et QCM), autonomous (questions brutes sans indice visible) et challenge "
        "(modification ou création de code). Répartis plusieurs questions en étapes graduelles, cite les "
        "parties importantes du script et adapte la difficulté. Retourne UNIQUEMENT un objet JSON valide, "
        "sans balises Markdown ni commentaire extérieur, conforme exactement à cette structure :\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )
