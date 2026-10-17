from __future__ import annotations

import importlib.util
import json
import queue
import threading
from ctypes import util as ctypes_util
from dataclasses import dataclass
from pathlib import Path

from ..paths import application_data_directory
from .office_runtime import runtime_root

FRENCH_MODEL_NAME = "vosk-model-small-fr-0.22"


@dataclass(frozen=True)
class SpeechStatus:
    engine_available: bool
    microphone_available: bool
    model_path: Path

    @property
    def ready(self) -> bool:
        return self.engine_available and self.microphone_available and self.model_path.is_dir()


def speech_model_directory() -> Path:
    bundled = runtime_root() / "speech-models" / FRENCH_MODEL_NAME
    if bundled.is_dir():
        return bundled
    return application_data_directory() / "speech-models" / FRENCH_MODEL_NAME


def _import_sounddevice():
    """Import sounddevice, also supporting a private Linux PortAudio runtime."""
    original_find_library = ctypes_util.find_library
    candidates = list((runtime_root() / "audio-runtime").glob("**/libportaudio.so.2"))
    candidates.extend(
        (application_data_directory(create=False) / "runtime").glob("**/libportaudio.so.2")
    )
    if candidates:
        ctypes_util.find_library = lambda name: (
            str(candidates[0]) if name == "portaudio" else original_find_library(name)
        )
    try:
        import sounddevice  # type: ignore[import-not-found]
    finally:
        ctypes_util.find_library = original_find_library
    return sounddevice


def speech_status(model_path: Path | None = None) -> SpeechStatus:
    """Inspect the optional offline speech pack and its native audio runtime."""
    microphone_available = importlib.util.find_spec("sounddevice") is not None
    if microphone_available:
        try:
            _import_sounddevice()
        except (ImportError, OSError):
            microphone_available = False
    return SpeechStatus(
        engine_available=importlib.util.find_spec("vosk") is not None,
        microphone_available=microphone_available,
        model_path=model_path or speech_model_directory(),
    )


def transcribe_microphone(
    stop_event: threading.Event,
    *,
    model_path: Path | None = None,
    sample_rate: int = 16_000,
) -> str:
    """Record the default microphone until stopped and transcribe it locally."""
    status = speech_status(model_path)
    if not status.ready:
        raise RuntimeError("Le moteur Vosk, le microphone ou le modèle français est absent.")
    if stop_event.is_set():
        return ""
    sounddevice = _import_sounddevice()
    import vosk  # type: ignore[import-not-found]

    audio: queue.Queue[bytes] = queue.Queue()

    def callback(indata: object, _frames: int, _time: object, status_info: object) -> None:
        if status_info:
            return
        audio.put(bytes(indata))

    model = vosk.Model(str(status.model_path))
    if stop_event.is_set():
        return ""
    recognizer = vosk.KaldiRecognizer(model, sample_rate)
    phrases: list[str] = []
    with sounddevice.RawInputStream(
        samplerate=sample_rate,
        blocksize=8_000,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        while not stop_event.is_set():
            try:
                data = audio.get(timeout=0.15)
            except queue.Empty:
                continue
            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get("text", "").strip()
                if text:
                    phrases.append(text)
    final_text = json.loads(recognizer.FinalResult()).get("text", "").strip()
    if final_text:
        phrases.append(final_text)
    return " ".join(phrases).strip()
