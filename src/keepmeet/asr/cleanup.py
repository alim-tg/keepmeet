import re
from collections import Counter

HALLUCINATION_RE = re.compile(
    r"(редактор субтитров|корректор\s+[а-яё]\.|субтитры (создавал|сделал|подготовил)|"
    r"продолжение следует|спасибо за просмотр|подписывайтесь на (канал|наш)|"
    r"dimatorzok|amara\.org|thanks for watching|subtitles by|please subscribe)",
    re.IGNORECASE,
)
WORDLIKE_RE = re.compile(r"\w", re.UNICODE)
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0


def is_repetitive(text: str) -> bool:
    words = text.split()
    if len(words) < 6:
        return False
    for size in range(2, 6):
        ngrams = [" ".join(words[i:i + size]) for i in range(len(words) - size + 1)]
        if not ngrams:
            continue
        count = Counter(ngrams).most_common(1)[0][1]
        if count >= 4 and (count / len(ngrams) > 0.3 or count >= 8):
            return True
    return False


def repetition_cutoff(text: str) -> int:
    words = text.split()
    for size in range(2, 6):
        ngrams = [" ".join(words[i:i + size]) for i in range(len(words) - size + 1)]
        if not ngrams:
            continue
        repeated, count = Counter(ngrams).most_common(1)[0]
        if count >= 4:
            first = ngrams.index(repeated)
            return first + size
    return len(words)


def _segment_is_noise(seg: dict) -> bool:
    text = (seg.get("text") or "").strip()
    if not text:
        return True
    if HALLUCINATION_RE.search(text):
        return True
    no_speech = seg.get("no_speech_prob") or 0.0
    logprob = seg.get("avg_logprob")
    return no_speech > NO_SPEECH_PROB and logprob is not None and logprob < LOW_LOGPROB


def _words_in(words: list[dict], start: float, end: float) -> list[dict]:
    return [w for w in words if start - 0.05 <= (w["start"] + w["end"]) / 2 <= end + 0.05]


def clean_words(segments: list[dict], words: list[dict]) -> list[dict]:
    words = _drop_phrases([w for w in words if WORDLIKE_RE.search(w["word"])])
    if not segments:
        return words
    drop: set[int] = set()
    for seg in segments:
        seg_words = _words_in(words, seg.get("start", 0.0), seg.get("end", 0.0))
        if _segment_is_noise(seg):
            drop.update(id(w) for w in seg_words)
        elif is_repetitive(seg.get("text") or ""):
            keep = repetition_cutoff(seg["text"])
            drop.update(id(w) for w in seg_words[keep:])
    return [w for w in words if id(w) not in drop]


def _drop_phrases(words: list[dict]) -> list[dict]:
    offsets = []
    text = ""
    for w in words:
        start = len(text) + (1 if text else 0)
        text = f"{text} {w['word']}" if text else w["word"]
        offsets.append((start, len(text)))
    covered = set()
    for match in HALLUCINATION_RE.finditer(text):
        covered.update(i for i, (a, b) in enumerate(offsets) if a < match.end() and b > match.start())
    return [w for i, w in enumerate(words) if i not in covered]
