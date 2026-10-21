import bisect
import dataclasses

import numpy as np

from .audio import SAMPLE_RATE

WINDOW_SECONDS = 30.0
MAX_CHUNK_SPEECH_SECONDS = 90.0
SPACER_SECONDS = 0.3
MERGE_GAP_SECONDS = 0.3

Span = tuple[float, float]


@dataclasses.dataclass
class Chunk:
    spans: list[Span]
    language: str
    candidates: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        if not self.candidates:
            self.candidates = [self.language]

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1

    @property
    def speech_seconds(self) -> float:
        return sum(end - start for start, end in self.spans)


class TimeMap:
    def __init__(self, spans: list[Span], spacer: float = SPACER_SECONDS):
        self.local_starts: list[float] = []
        self.spans = spans
        position = 0.0
        for start, end in spans:
            self.local_starts.append(position)
            position += (end - start) + spacer
        self.length = max(0.0, position - spacer)

    def to_source(self, t: float) -> float:
        if not self.spans:
            return t
        i = max(0, bisect.bisect_right(self.local_starts, t) - 1)
        start, end = self.spans[i]
        return min(start + max(0.0, t - self.local_starts[i]), end)


def merge_spans(spans: list[Span], gap: float = MERGE_GAP_SECONDS) -> list[Span]:
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def split_long_spans(spans: list[Span], max_seconds: float = WINDOW_SECONDS) -> list[Span]:
    result = []
    for start, end in spans:
        while end - start > max_seconds:
            result.append((start, start + max_seconds))
            start += max_seconds
        result.append((start, end))
    return result


def build_windows(spans: list[Span], target: float = WINDOW_SECONDS) -> list[list[Span]]:
    windows: list[list[Span]] = []
    current: list[Span] = []
    length = 0.0
    for span in split_long_spans(spans, target):
        span_len = span[1] - span[0]
        if current and length + span_len > target:
            windows.append(current)
            current, length = [], 0.0
        current.append(span)
        length += span_len
    if current:
        windows.append(current)
    return windows


def group_chunks(windows: list[list[Span]], choices: list, max_speech: float = MAX_CHUNK_SPEECH_SECONDS) -> list[Chunk]:
    chunks: list[Chunk] = []
    for spans, choice in zip(windows, choices):
        speech = sum(e - s for s, e in spans)
        last = chunks[-1] if chunks else None
        mergeable = (
            last is not None
            and not last.ambiguous
            and not choice.ambiguous
            and last.language == choice.language
            and last.speech_seconds + speech <= max_speech
        )
        if mergeable:
            last.spans.extend(spans)
        else:
            chunks.append(Chunk(spans=list(spans), language=choice.language, candidates=list(choice.candidates)))
    return chunks


def render(samples: np.ndarray, spans: list[Span], spacer: float = SPACER_SECONDS) -> tuple[np.ndarray, TimeMap]:
    gap = np.zeros(int(spacer * SAMPLE_RATE), dtype=np.float32)
    parts = []
    for i, (start, end) in enumerate(spans):
        if i:
            parts.append(gap)
        parts.append(samples[int(start * SAMPLE_RATE): int(end * SAMPLE_RATE)])
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return audio, TimeMap(spans, spacer)
