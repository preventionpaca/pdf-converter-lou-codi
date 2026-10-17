from __future__ import annotations

import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


MODEL_NAME = "vosk-model-small-fr-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_SHA256 = "cabf6180e177eb9b3a9a9d43a437bd5e549f3a7d09525e5d69a3fed787be12ad"


def main() -> None:
    project = Path(__file__).resolve().parents[2]
    destination = project / "packaging" / "runtime" / "speech-models"
    model = destination / MODEL_NAME
    if (model / "am" / "final.mdl").is_file():
        print(f"Modèle Vosk déjà présent : {model}")
        return

    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lou-codi-vosk-") as temporary:
        archive = Path(temporary) / f"{MODEL_NAME}.zip"
        print(f"Téléchargement du modèle officiel : {MODEL_URL}")
        urllib.request.urlretrieve(MODEL_URL, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise RuntimeError(
                f"Somme SHA-256 incorrecte pour le modèle Vosk : {digest}"
            )
        with zipfile.ZipFile(archive) as source:
            source.extractall(destination)

    if not (model / "am" / "final.mdl").is_file():
        shutil.rmtree(model, ignore_errors=True)
        raise RuntimeError("Le modèle Vosk téléchargé est incomplet.")
    print(f"Modèle Vosk vérifié : {model}")


if __name__ == "__main__":
    main()
