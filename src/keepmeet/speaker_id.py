import json
import logging
import re

from .formatter import FormatterError, _run_claude

logger = logging.getLogger(__name__)

STRONG_VOICE = 0.80
RESULT_RE = re.compile(r"<speakers>\s*(.*?)\s*</speakers>", re.S)

PROMPT = (
    "You identify who is speaking in a team meeting transcript. Labels like SPEAKER_01 come from "
    "automatic voice clustering; each label is one voice, but which person it is is unknown.\n\n"
    "Decide the person behind each label using conversational evidence, strongest first:\n"
    "1. Someone is called by name and the next label answers (\"Саш, что у тебя?\" followed by SPEAKER_01 "
    "giving an update means SPEAKER_01 is Alexander).\n"
    "2. A speaker introduces themselves or says their own name.\n"
    "3. Others refer to what this speaker just said by name.\n"
    "A speaker addressing someone by name is NOT that person. Short and familiar forms map to the full "
    "names on the list (for example Саша/Саш = Alexander, Маша = Maria, Bob = Robert).\n\n"
    "Team members you may see (use these spellings; another name is fine only if the transcript clearly "
    "shows a person not on the list): {roster}\n"
    "{self_line}"
    "Voice similarity to saved voice profiles, for reference only (0-1, higher is more similar; "
    "below {strong} is weak): \n{hints}\n\n"
    "Each person maps to at most one label. If the evidence is weak or conflicting, use null.\n"
    "Answer with only this block, one entry per label:\n"
    "<speakers>\n"
    "{{\"SPEAKER_01\": {{\"name\": \"Alexander\", \"confidence\": \"high\", \"evidence\": \"Maria asks 'Саш, что у тебя?' and SPEAKER_01 answers\"}}, "
    "\"SPEAKER_04\": {{\"name\": null, \"confidence\": \"low\", \"evidence\": \"never addressed\"}}}}\n"
    "</speakers>\n"
    "confidence is high, medium or low.\n\n---\n\n"
)


def _hints(voice_scores: dict[str, dict[str, float]]) -> str:
    lines = []
    for sid, scores in voice_scores.items():
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
        lines.append(f"- {sid}: " + ", ".join(f"{name} {score:.2f}" for name, score in top) if top else f"- {sid}: no profiles")
    return "\n".join(lines) or "- none"


def parse_identification(output: str, labels: set[str]) -> dict[str, dict]:
    match = RESULT_RE.search(output or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    result = {}
    for sid, info in (data.items() if isinstance(data, dict) else []):
        if sid not in labels or not isinstance(info, dict):
            continue
        name = (info.get("name") or "").strip()
        confidence = str(info.get("confidence") or "low").lower()
        if name and confidence in ("high", "medium"):
            result[sid] = {"name": name, "confidence": confidence, "evidence": str(info.get("evidence") or "")[:300]}
    return result


def identify_from_conversation(
    transcript: str,
    labels: list[str],
    roster: list[str],
    voice_scores: dict[str, dict[str, float]],
    self_name: str | None,
) -> dict[str, dict]:
    if not labels:
        return {}
    prompt = PROMPT.format(
        roster=", ".join(roster) or "unknown",
        self_line=f"The recording owner is {self_name}; lines labeled {self_name} are certainly them.\n" if self_name else "",
        strong=STRONG_VOICE,
        hints=_hints({sid: voice_scores.get(sid, {}) for sid in labels}),
    )
    try:
        output = _run_claude(prompt + transcript)
    except FormatterError:
        logger.exception("Conversation-based speaker identification failed")
        return {}
    result = parse_identification(output, set(labels))
    logger.info("Identified from conversation: %s", {k: v["name"] for k, v in result.items()})
    return result


def combine(
    speakers: list[str],
    voice: dict[str, dict],
    conversation: dict[str, dict],
    same_voice: dict[tuple[str, str], float],
    same_voice_threshold: float = 0.7,
) -> dict[str, dict]:
    decided: dict[str, dict] = {}
    for sid in speakers:
        v = voice.get(sid)
        c = conversation.get(sid)
        if v and not v.get("merged") and v["confidence"] >= STRONG_VOICE:
            decided[sid] = {**v, "source": "voice"}
        elif c:
            agrees = v is not None and v["name"].lower() == c["name"].lower()
            decided[sid] = {
                **(v if agrees else {}),
                "name": c["name"],
                "confidence": v["confidence"] if agrees else None,
                "source": "voice+conversation" if agrees else "conversation",
                "evidence": c["evidence"],
                "merged": False,
            }
        elif v and not v.get("merged"):
            decided[sid] = {**v, "source": "voice"}

    by_name: dict[str, list[str]] = {}
    for sid, info in decided.items():
        by_name.setdefault(info["name"].lower(), []).append(sid)
    for sids in by_name.values():
        if len(sids) < 2:
            continue
        rank = {"voice": 3, "voice+conversation": 4, "conversation": 2}
        sids.sort(key=lambda s: (rank.get(decided[s]["source"], 0), decided[s].get("confidence") or 0), reverse=True)
        keeper = sids[0]
        for other in sids[1:]:
            pair = tuple(sorted((keeper, other)))
            if same_voice.get(pair, 0.0) < same_voice_threshold:
                decided.pop(other)
            else:
                decided[other] = {**decided[other], "merged": True}
    return decided
