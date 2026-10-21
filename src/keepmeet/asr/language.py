import dataclasses
import logging

import numpy as np

from .audio import free_gpu_memory

logger = logging.getLogger(__name__)

DETECTION_MODEL = "medium"
CERTAIN = 0.9
CANDIDATE = 0.1


@dataclasses.dataclass
class LanguageChoice:
    language: str
    candidates: list[str]

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


class LanguageDetector:
    def __init__(self, allowed: list[str]):
        self.allowed = allowed
        self._model = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._model = None
        free_gpu_memory()

    def _load(self):
        if self._model is None:
            import torch
            from faster_whisper import WhisperModel

            cuda = torch.cuda.is_available()
            self._model = WhisperModel(
                DETECTION_MODEL,
                device="cuda" if cuda else "cpu",
                compute_type="int8_float16" if cuda else "int8",
            )
        return self._model

    def probabilities(self, audio: np.ndarray) -> dict[str, float]:
        _, _, all_probs = self._load().detect_language(audio)
        scores = {lang: prob for lang, prob in all_probs if lang in self.allowed}
        total = sum(scores.values())
        if total <= 0:
            return {lang: 1.0 / len(self.allowed) for lang in self.allowed}
        return {lang: prob / total for lang, prob in scores.items()}


def classify(probs: dict[str, float], default: str) -> LanguageChoice:
    if not probs:
        return LanguageChoice(default, [default])
    ranked = sorted(probs, key=probs.get, reverse=True)
    best = ranked[0]
    if probs[best] >= CERTAIN:
        return LanguageChoice(best, [best])
    candidates = [lang for lang in ranked if probs[lang] >= CANDIDATE][:2]
    return LanguageChoice(best, candidates)


def detect_window_languages(windows_audio: list[np.ndarray], allowed: list[str]) -> list[LanguageChoice]:
    if len(allowed) == 1 or not windows_audio:
        return [LanguageChoice(allowed[0], [allowed[0]]) for _ in windows_audio]
    try:
        with LanguageDetector(allowed) as detector:
            probabilities = [detector.probabilities(audio) for audio in windows_audio]
    except Exception:
        logger.exception("Language detection failed, arbitrating every window")
        return [LanguageChoice(allowed[0], allowed[:2]) for _ in windows_audio]
    choices = [classify(p, allowed[0]) for p in probabilities]
    logger.info(
        "Window languages: %s",
        " ".join(c.language + ("?" if c.ambiguous else "") for c in choices),
    )
    return choices
