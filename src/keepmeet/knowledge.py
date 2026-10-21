import dataclasses
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_DIGEST_CHARS = 30_000
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.S)
GLOSSARY_TERM_RE = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*([^|]*)\|", re.M)


@dataclasses.dataclass
class Knowledge:
    root: Path
    digest: str
    terms: list[str]


def _read(path: Path) -> str:
    try:
        return FRONTMATTER_RE.sub("", path.read_text(encoding="utf-8")).strip()
    except OSError:
        return ""


def _glossary_terms(glossary: str) -> list[str]:
    terms: list[str] = []
    for names, meaning in GLOSSARY_TERM_RE.findall(glossary):
        for name in re.split(r"\s*/\s*", names):
            name = name.strip(" `")
            if name and len(name) <= 30:
                terms.append(name)
        full = meaning.split("—")[0].split(" - ")[0].strip(" `")
        if 3 < len(full) <= 40 and full[:1].isupper() and " " in full and "(" not in full:
            terms.append(full)
    return list(dict.fromkeys(t for t in terms if not t.startswith("`") and t[0].isalnum()))


def _find(folders: list[Path], name: str) -> Path | None:
    for folder in folders:
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if child.is_file() and child.name.lower() == name:
                return child
    return None


def _strip_title(text: str) -> str:
    return re.sub(r"\A#\s+[^\n]*\n", "", text).strip()


def load(path: str | None) -> Knowledge | None:
    if not path:
        return None
    root = Path(path)
    folders = [root, root / "memory", root / "docs"]
    glossary_file = _find(folders, "glossary.md")
    index_file = _find(folders, "index.md")
    if glossary_file is None and index_file is None:
        logger.warning("Knowledge path %s has no glossary.md or index.md, ignoring it", root)
        return None
    glossary = _read(glossary_file) if glossary_file else ""
    index = _read(index_file) if index_file else ""
    parts = []
    if glossary:
        parts.append("## Glossary (what people say -> what it is)\n" + _strip_title(glossary))
    if index:
        parts.append("## Systems index (one line per repo or service)\n" + _strip_title(index))
    digest = "\n\n".join(parts)[:MAX_DIGEST_CHARS]
    return Knowledge(root=root, digest=digest, terms=_glossary_terms(glossary))
