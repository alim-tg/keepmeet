import json
import re
from collections import Counter
from pathlib import Path

LATIN_TERM_RE = re.compile(r"\b[A-Z][A-Za-z0-9.+#-]*(?:\s+[A-Z][A-Za-z0-9.+#-]*)?\b")
MIN_CYRILLIC_SHARE = 0.35
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "is", "it", "ok", "okay", "yes", "no",
    "so", "i", "you", "we", "be", "do", "go", "hi", "hello", "mm", "hmm", "uh", "um",
}
MAX_TERMS = 30
MIN_COUNT = 2
RECENT_JOBS = 30
MAX_PROMPT_CHARS = 600

INTROS = {
    "ru": "Рабочая встреча команды разработки.",
    "en": "Engineering team meeting.",
}


def split_terms(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\n;]", text or "") if t.strip()]


def _cyrillic_share(text: str) -> float:
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return cyrillic / (cyrillic + latin) if cyrillic + latin else 0.0


def harvest_terms(jobs_dir: Path, exclude: set[str]) -> list[str]:
    counts: Counter = Counter()
    files = sorted(jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:RECENT_JOBS]
    for path in files:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if job.get("language") != "ru":
            continue
        for seg in job.get("segments") or []:
            text = seg.get("text") or ""
            if _cyrillic_share(text) < MIN_CYRILLIC_SHARE:
                continue
            for match in LATIN_TERM_RE.findall(text):
                term = match.strip(" .-")
                if len(term) < 2 or term.lower() in STOPWORDS or term.lower() in exclude:
                    continue
                counts[term] += 1
    return [term for term, n in counts.most_common() if n >= MIN_COUNT][:MAX_TERMS]


def build_prompt(names: list[str], terms: list[str], language: str) -> str | None:
    names = list(dict.fromkeys(n for n in names if n))
    terms = list(dict.fromkeys(t for t in terms if t))
    if not names and not terms:
        return None
    intro = INTROS.get(language, "")
    while True:
        parts = [intro, ", ".join(names) + "." if names else "", ", ".join(terms) + "." if terms else ""]
        prompt = " ".join(p for p in parts if p)
        if len(prompt) <= MAX_PROMPT_CHARS or not terms:
            return prompt[:MAX_PROMPT_CHARS]
        terms = terms[:-1]
