import dataclasses
import re

AUTO = "auto"


@dataclasses.dataclass(frozen=True)
class NoteFormat:
    key: str
    label: str
    when: str
    structure: str


SUMMARY = (
    "## Summary\n"
    "- 3 to 6 bullets with the most important outcomes: conclusions, problems found, risks and anything a "
    "manager needs to know. Each bullet is one clear sentence that names the people involved. Draw "
    "conclusions; do not just list topics.\n\n"
)
DECISIONS = "## Decisions\n- What was agreed and, if said, why.\n\n"
ACTIONS = "## Action items\n- [ ] **Owner**: concrete next step (add the deadline or dependency if mentioned)\n\n"
QUESTIONS = "## Open questions\n- Questions raised but not answered, and who should answer them.\n\n"

FORMATS: dict[str, NoteFormat] = {f.key: f for f in [
    NoteFormat(
        "daily", "Daily standup",
        "a status round where people take turns telling what they did, what they will do and what blocks them",
        SUMMARY + DECISIONS + ACTIONS
        + "## Blockers & risks\n- **Person**: what blocks them or what could go wrong, and who can help.\n\n"
        "## Updates\n### <Person name>\n- **Yesterday**\n  - one bullet per piece of work, sub-bullets for details\n"
        "- **Today**\n  - planned work\n- **Blockers**\n  - only if they have any\n\n" + QUESTIONS,
    ),
    NoteFormat(
        "planning", "Planning",
        "sprint or release planning: choosing scope, estimating, assigning owners, sequencing work",
        SUMMARY
        + "## Goals\n- What this sprint/release/period should achieve.\n\n"
        "## Committed scope\n| Item | Owner | Estimate | Notes |\n|---|---|---|---|\n"
        "| ticket or task | person | if said | dependencies, risks |\n\n"
        "## Deferred or out of scope\n- What was explicitly postponed and why.\n\n"
        + DECISIONS
        + "## Risks & dependencies\n- Cross-team or cross-service dependencies, capacity and timing risks.\n\n"
        + ACTIONS + QUESTIONS,
    ),
    NoteFormat(
        "technical", "Technical discussion",
        "a technical or design discussion about a problem, an architecture, a bug or an integration",
        SUMMARY
        + "## Context\n- The problem or goal being discussed and the relevant current behavior.\n\n"
        "## Options considered\n### <Option name>\n- How it works\n- **Pros:** ...\n- **Cons:** ...\n\n"
        "## Decisions\n- The chosen approach and the reasoning behind it.\n\n"
        "## Affected systems\n- Services, queues, databases or contracts touched, and how.\n\n"
        "## Risks & dependencies\n- Migration, data, rollout or ownership risks.\n\n" + ACTIONS + QUESTIONS,
    ),
    NoteFormat(
        "retro", "Retrospective",
        "a retrospective about how the team worked: what went well, what did not, what to change",
        SUMMARY
        + "## What went well\n- ...\n\n## What to improve\n- Problem and its impact.\n\n"
        "## Ideas & experiments\n- Proposals the team wants to try.\n\n" + DECISIONS + ACTIONS,
    ),
    NoteFormat(
        "review", "Demo / review",
        "a demo or sprint review where work is shown and stakeholders give feedback",
        SUMMARY
        + "## Demonstrated\n### <Feature or ticket>\n- What was shown, by whom, and its state\n- Feedback received\n\n"
        + DECISIONS + ACTIONS + "## Follow-ups\n- Bugs or changes requested during the demo.\n\n",
    ),
    NoteFormat(
        "one_on_one", "1:1",
        "a conversation between two people about work, feedback, growth or personal topics",
        SUMMARY
        + "## Topics\n### <Topic>\n- Key points\n\n## Feedback\n- Feedback given in either direction.\n\n"
        "## Agreements\n- What both sides agreed on.\n\n" + ACTIONS,
    ),
    NoteFormat(
        "general", "General discussion",
        "any other meeting: syncs, alignment calls, ad-hoc discussions",
        SUMMARY
        + "## Discussion\n### <Topic>\n- Key points, with sub-bullets for details and who said what\n\n"
        + DECISIONS + ACTIONS + QUESTIONS,
    ),
]}

TITLE_HINTS = [
    (re.compile(r"\b(daily|stand-?up|дейли|стендап)\b", re.I), "daily"),
    (re.compile(r"\b(retro|retrospective|ретро)\b", re.I), "retro"),
    (re.compile(r"\b(planning|grooming|refinement|планирование)\b", re.I), "planning"),
    (re.compile(r"\b(demo|review|демо)\b", re.I), "review"),
    (re.compile(r"\b(1[:x]1|one[- ]on[- ]one|1-on-1)\b", re.I), "one_on_one"),
]


def format_from_title(title: str | None) -> str | None:
    for pattern, key in TITLE_HINTS:
        if title and pattern.search(title):
            return key
    return None


def resolve(requested: str | None, title: str | None) -> str:
    if requested and requested in FORMATS:
        return requested
    return format_from_title(title) or AUTO


def describe_choices() -> str:
    lines = []
    for f in FORMATS.values():
        lines.append(f"### {f.key}: {f.label} (use for {f.when})\n{f.structure.strip()}\n")
    return "\n".join(lines)


def options() -> list[dict]:
    return [{"key": f.key, "label": f.label, "when": f.when} for f in FORMATS.values()]
