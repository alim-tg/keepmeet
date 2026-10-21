import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path


class FormatterError(Exception):
    pass


SPEAKER_LABEL_RE = re.compile(r"\b(?:SPEAKER_\d+|SELF)\b")
NAMES_BLOCK_RE = re.compile(r"<speaker_names>\s*(.*?)\s*</speaker_names>", re.S)

FORMAT_BLOCK_RE = re.compile(r"<meeting_type>\s*(\w+)\s*</meeting_type>")
CLAUDE_TIMEOUT = 300
CLAUDE_TIMEOUT_WITH_TOOLS = 600

INTRO = (
    "You are writing the official notes of a team meeting from its transcript. "
    "Readers skim these notes in Confluence, so lead with what matters.\n\n"
)

FIXED_FORMAT = (
    "This meeting is a {label}. Use exactly this markdown structure and section names "
    "(omit a section only if it would be empty):\n\n{structure}\n"
)

AUTO_FORMAT = (
    "First decide which kind of meeting this is from the title and the conversation, then use exactly "
    "that format's markdown structure and section names (omit a section only if it would be empty). "
    "Do not include the '### key: ...' line itself.\n\n{choices}\n"
)

RULES = (
    "Rules:\n"
    "- Use nested bullets (2-space indentation) instead of long run-on bullets.\n"
    "- Be concise and specific: keep ticket IDs, service names, environments, numbers and dates.\n"
    "- Do not add information that is not in the transcript. Do not include a top-level # title.\n"
    "- Always write the notes in English, even when the transcript is in Russian or another language: "
    "translate the content, keep people's names as they are, and keep technical terms, "
    "product names and ticket IDs unchanged.\n"
    "- Speakers labeled like SPEAKER_00 have not been identified yet. Never write such labels in the notes. "
    "If the transcript or the context below reveals who that speaker is (they are addressed by name, "
    "introduce themselves, or the context says so), use only the person's name, for example 'Alex', "
    "without the label and without phrases like 'addressed as'. "
    "If a speaker cannot be identified, call them 'Unknown speaker' (add a number if there are several).\n"
)

KNOWLEDGE = (
    "\nSystem knowledge. The transcript comes from speech recognition, so service and product names "
    "are often misheard or spelled phonetically (Cyrillic, split words). Use this knowledge to write the "
    "correct official names and acronyms when the match is clear, and to make technical points precise. "
    "Never invent facts that were not said in the meeting.\n"
    "<system_knowledge>\n{digest}\n</system_knowledge>\n"
)

LOOKUPS = (
    "\nYou can read the knowledge base at {root} with Read, Grep and Glob (read-only). Use Glob and Grep to "
    "find the document about a service. Look things up only when the meeting "
    "goes into detail about a specific service and the summary above is not enough, at most a few files. "
    "Reply with only the notes and the final blocks, not with a description of what you looked up.\n"
)

TAIL = (
    "Meeting title: {title}\n"
    "Meeting date: {meeting_date}\n"
    "{speaker_context}"
    "{extra_context}"
    "\nAfter the notes, output exactly these blocks and nothing after them:\n"
    "<meeting_type>{type_hint}</meeting_type>\n"
    "<speaker_names>\n{{\"SPEAKER_02\": \"Alex\"}}\n</speaker_names>\n"
    "In the first block, KEY is the format key you used ({keys}). The second lists the unidentified labels whose names you "
    "determined, as JSON; use <speaker_names>{{}}</speaker_names> if none.\n"
    "\n---\n\n"
)


def _build_speaker_context(matched_profiles: dict) -> str:
    if not matched_profiles:
        return ""
    lines = ["\nSpeaker context:"]
    for info in matched_profiles.values():
        parts = [info["name"]]
        if info.get("role"):
            parts[0] += f" (Role: {info['role']})"
        if info.get("description"):
            parts.append(f"-- {info['description']}")
        lines.append(f"- {' '.join(parts)}")
    return "\n".join(lines) + "\n"


def _build_extra_context(extra_context: str | None) -> str:
    text = (extra_context or "").strip()
    if not text:
        return ""
    return (
        "\nAdditional context from the meeting owner. It is accurate and takes priority "
        "over your own guesses (it may name speakers, give roles, or ask for emphasis):\n"
        f"{text}\n"
    )


def _split_names(output: str) -> tuple[str, dict[str, str]]:
    match = NAMES_BLOCK_RE.search(output)
    if not match:
        return output.strip(), {}
    notes = (output[: match.start()] + output[match.end():]).strip()
    try:
        data = json.loads(match.group(1) or "{}")
    except json.JSONDecodeError:
        return notes, {}
    names = {
        str(k): str(v).strip()
        for k, v in data.items()
        if SPEAKER_LABEL_RE.fullmatch(str(k)) and str(v).strip()
    } if isinstance(data, dict) else {}
    return notes, names


def _split_format(output: str) -> tuple[str, str | None]:
    match = FORMAT_BLOCK_RE.search(output)
    if not match:
        return output, None
    return output[: match.start()] + output[match.end():], match.group(1).strip().lower()


def build_prompt(
    meeting_date: str,
    title: str | None,
    format_key: str,
    matched_profiles: dict | None = None,
    extra_context: str | None = None,
    knowledge=None,
    lookups: bool = False,
) -> str:
    from . import note_formats

    if format_key in note_formats.FORMATS:
        fmt = note_formats.FORMATS[format_key]
        layout = FIXED_FORMAT.format(label=fmt.label, structure=fmt.structure)
        type_hint = fmt.key
        keys = fmt.key
    else:
        layout = AUTO_FORMAT.format(choices=note_formats.describe_choices())
        type_hint = "KEY"
        keys = ", ".join(note_formats.FORMATS)
    parts = [INTRO, layout, RULES]
    if knowledge is not None and knowledge.digest:
        parts.append(KNOWLEDGE.format(digest=knowledge.digest))
        if lookups:
            parts.append(LOOKUPS.format(root=knowledge.root))
    parts.append(TAIL.format(
        title=title or "unknown",
        meeting_date=meeting_date,
        speaker_context=_build_speaker_context(matched_profiles or {}),
        extra_context=_build_extra_context(extra_context),
        type_hint=type_hint,
        keys=keys,
    ))
    return "".join(parts)


def unnamed_labels(notes: str | None) -> list[str]:
    return sorted(set(SPEAKER_LABEL_RE.findall(notes or "")))


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude.exe",
        home / ".local" / "bin" / "claude",
        Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        home / ".claude" / "local" / "claude.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _run_claude(input_text: str, attempts: int = 3, extra_args: list[str] | None = None, timeout: int = CLAUDE_TIMEOUT) -> str:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    for attempt in range(attempts):
        exe = find_claude()
        if exe is None:
            if attempt < attempts - 1:
                time.sleep(15)
                continue
            raise FormatterError(
                "claude CLI not found (it may be updating). Install Claude Code: https://claude.ai/code"
            )
        try:
            proc = subprocess.run(
                [exe, "-p", "--output-format", "text", *(extra_args or [])],
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError:
            if attempt < attempts - 1:
                time.sleep(15)
                continue
            raise FormatterError("claude CLI disappeared while starting (it may be updating). Retry in a minute.")
        except subprocess.TimeoutExpired:
            raise FormatterError(f"Claude CLI timed out after {timeout} seconds")

        if proc.returncode != 0:
            raise FormatterError(
                f"Claude CLI exited with code {proc.returncode}: {proc.stderr}"
            )
        return proc.stdout
    raise FormatterError("Claude CLI could not be started")


def generate_notes(
    raw_transcript: str,
    meeting_date: str,
    matched_profiles: dict | None = None,
    extra_context: str | None = None,
    title: str | None = None,
    format_key: str | None = None,
    knowledge=None,
    lookups: bool = False,
) -> tuple[str, dict[str, str], str | None]:
    from . import note_formats

    resolved = note_formats.resolve(format_key, title)
    prompt = build_prompt(meeting_date, title, resolved, matched_profiles, extra_context, knowledge, lookups)
    extra_args, timeout = None, CLAUDE_TIMEOUT
    if lookups and knowledge is not None:
        extra_args = ["--add-dir", str(knowledge.root), "--allowedTools", "Read", "Grep", "Glob"]
        timeout = CLAUDE_TIMEOUT_WITH_TOOLS
    output = _run_claude(f"{prompt}{raw_transcript}", extra_args=extra_args, timeout=timeout)
    output, used = _split_format(output)
    notes, names = _split_names(output)
    if used not in note_formats.FORMATS:
        used = resolved if resolved in note_formats.FORMATS else None
    return notes, names, used


def format_with_claude(
    raw_transcript: str,
    meeting_date: str,
    matched_profiles: dict | None = None,
    extra_context: str | None = None,
) -> str:
    return generate_notes(raw_transcript, meeting_date, matched_profiles, extra_context)[0]
