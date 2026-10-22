import json

import pytest

from lou_codi_pdf_converter.code_lab_library import (
    build_generation_prompt,
    load_learning_paths,
    parse_learning_path,
    save_learning_path,
)


def sample_path():
    return {
        "title": "Comprendre une boucle",
        "language": "python",
        "level": "Progressif",
        "code": "for item in range(3):\n    print(item)",
        "concepts": ["boucle", "fonction"],
        "stages": [
            {
                "title": "Observer",
                "mode": "assisted",
                "objective": "Repérer la boucle",
                "questions": [{"prompt": "Combien de passages ?", "type": "qcm", "choices": ["2", "3"], "answer": "3", "hint": "Regardez range", "explanation": "range(3) produit trois valeurs."}],
            },
            {
                "title": "Expliquer",
                "mode": "autonomous",
                "objective": "Formuler sans aide",
                "questions": [{"prompt": "Décrivez le résultat.", "type": "open", "choices": [], "answer": "0, 1 puis 2", "hint": "", "explanation": "La borne finale est exclue."}],
            },
            {
                "title": "Transformer",
                "mode": "challenge",
                "objective": "Modifier le code",
                "questions": [{"prompt": "Affichez cinq valeurs.", "type": "code", "choices": [], "answer": "Utiliser range(5)", "hint": "", "explanation": "La boucle produit alors 0 à 4."}],
            },
        ],
    }


def test_learning_path_round_trip_in_local_library(tmp_path) -> None:
    path = parse_learning_path(sample_path())
    target = save_learning_path(path, tmp_path)
    assert target.is_file()
    loaded = load_learning_paths(tmp_path)
    assert len(loaded) == 1
    assert loaded[0] == path


def test_parser_accepts_json_fence_and_requires_all_three_modes() -> None:
    raw = "```json\n" + json.dumps(sample_path()) + "\n```"
    assert parse_learning_path(raw).title == "Comprendre une boucle"
    invalid = sample_path()
    invalid["stages"] = invalid["stages"][:2]
    with pytest.raises(ValueError, match="assisté, autonome et défi"):
        parse_learning_path(invalid)


def test_generation_prompt_contains_script_schema_and_progressive_modes() -> None:
    prompt = build_generation_prompt("print('bonjour')", "python")
    assert "print('bonjour')" in prompt
    assert '"mode": "assisted"' in prompt
    assert '"mode": "autonomous"' in prompt
    assert '"mode": "challenge"' in prompt
    assert "UNIQUEMENT un objet JSON valide" in prompt
