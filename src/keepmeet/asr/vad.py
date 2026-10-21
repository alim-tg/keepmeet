import numpy as np

from .audio import SAMPLE_RATE
from .chunking import Span, merge_spans

MIN_SILENCE_MS = 500
SPEECH_PAD_MS = 200
MIN_SPEECH_MS = 250


def speech_regions(samples: np.ndarray) -> list[Span]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(
        min_silence_duration_ms=MIN_SILENCE_MS,
        speech_pad_ms=SPEECH_PAD_MS,
        min_speech_duration_ms=MIN_SPEECH_MS,
    )
    stamps = get_speech_timestamps(samples, options)
    return merge_spans([(s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in stamps])
