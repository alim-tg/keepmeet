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

PROMPT_TEMPLATE = (
    "You are writing the official notes of a daily standup meeting from its transcript. "
    "Readers skim these notes in Confluence, so lead with what matters.\n\n"
    "Use exactly this markdown structure and section names (omit a section only if it would be empty):\n\n"
    "## Summary\n"
    "- 3 to 6 bullets with the most important outcomes of the meeting: major progress, problems found, "
    "risks, and anything the team or a manager needs to know. Each bullet is one clear sentence that "
    "names the people involved. Draw conclusions; do not just list topics.\n\n"
    "## Decisions\n"
    "- Agreements reached during the meeting (what was decided and, if said, why).\n\n"
    "## Action items\n"
    "- [ ] **Owner**: concrete next step (add the deadline or dependency if mentioned)\n\n"
    "## Blockers & risks\n"
    "- **Person**: what is blocking them or what could go wrong, and who can help if mentioned.\n\n"
    "## Updates\n"
    "### <Person name>\n"
    "- **Yesterday**\n"
    "  - one bullet per piece of work, with sub-bullets (indented 2 more spaces) for important details\n"
    "- **Today**\n"
    "  - planned work\n"
    "- **Blockers**\n"
    "  - only if they have any\n\n"
    "## Open questions\n"
    "- Questions raised but not answered.\n\n"
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
    "Meeting date: {meeting_date}\n"
    "{speaker_context}"
    "{extra_context}"
    "\nAfter the notes, output exactly one block listing the unidentified labels whose names you "
    "determined, as JSON, for example:\n"
    "<speaker_names>\n{{\"SPEAKER_02\": \"Alex\"}}\n</speaker_names>\n"
    "Output <speaker_names>{{}}</speaker_names> if you identified none. Do not put anything after this block.\n"
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


def _run_claude(input_text: str, attempts: int = 3) -> str:
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
                [exe, "-p", "--output-format", "text"],
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
                env=env,
            )
        except FileNotFoundError:
            if attempt < attempts - 1:
                time.sleep(15)
                continue
            raise FormatterError("claude CLI disappeared while starting (it may be updating). Retry in a minute.")
        except subprocess.TimeoutExpired:
            raise FormatterError("Claude CLI timed out after 300 seconds")

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
) -> tuple[str, dict[str, str]]:
    prompt = PROMPT_TEMPLATE.format(
        meeting_date=meeting_date,
        speaker_context=_build_speaker_context(matched_profiles or {}),
        extra_context=_build_extra_context(extra_context),
    )
    return _split_names(_run_claude(f"{prompt}{raw_transcript}"))


def format_with_claude(
    raw_transcript: str,
    meeting_date: str,
    matched_profiles: dict | None = None,
    extra_context: str | None = None,
) -> str:
    return generate_notes(raw_transcript, meeting_date, matched_profiles, extra_context)[0]
