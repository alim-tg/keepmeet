import os
import subprocess


class FormatterError(Exception):
    pass


PROMPT_TEMPLATE = (
    "Format the following daily standup meeting transcript into structured meeting notes.\n"
    "For each speaker, extract: what they did yesterday, what they plan today, and any blockers.\n"
    "Use markdown formatting with ## for speaker names and bullet lists for their updates.\n"
    "Keep it concise. Do not add information that is not in the transcript.\n"
    "Meeting date: {meeting_date}\n"
    "\n---\n\n"
)


def format_with_claude(raw_transcript: str, meeting_date: str) -> str:
    prompt = PROMPT_TEMPLATE.format(meeting_date=meeting_date)
    input_text = f"{prompt}{raw_transcript}"

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "text"],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env=env,
        )
    except FileNotFoundError:
        raise FormatterError(
            "claude CLI not found. Install Claude Code: https://claude.ai/code"
        )
    except subprocess.TimeoutExpired:
        raise FormatterError("Claude CLI timed out after 120 seconds")

    if proc.returncode != 0:
        raise FormatterError(
            f"Claude CLI exited with code {proc.returncode}: {proc.stderr}"
        )

    return proc.stdout.strip()
