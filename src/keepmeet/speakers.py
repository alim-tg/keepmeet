import json
from pathlib import Path

import click


class SpeakerProfileError(Exception):
    pass


def load_speaker_map(profile_path: str) -> dict[str, str]:
    p = Path(profile_path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError) as e:
        raise SpeakerProfileError(f"Failed to load speaker profile {p}: {e}") from e


def save_speaker_map(profile_path: str, mapping: dict[str, str]) -> None:
    p = Path(profile_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise SpeakerProfileError(f"Failed to save speaker profile {p}: {e}") from e


def prompt_speaker_mapping(
    segments: list[dict],
    existing_map: dict[str, str],
) -> dict[str, str]:
    mapping = dict(existing_map)
    samples = _collect_samples(segments)

    unknown = [s for s in samples if s not in mapping]
    if not unknown:
        return mapping

    click.echo("\nUnknown speakers detected. Please assign names:")
    click.echo("(press Enter to keep the default label)\n")

    for speaker_id in unknown:
        sample_text = samples.get(speaker_id, "")
        click.echo(f"  {speaker_id} said: \"{sample_text[:120]}...\"" if len(sample_text) > 120 else f"  {speaker_id} said: \"{sample_text}\"")
        name = click.prompt(f"  Name for {speaker_id}", default=speaker_id)
        mapping[speaker_id] = name
        click.echo()

    return mapping


def _collect_samples(segments: list[dict]) -> dict[str, str]:
    samples: dict[str, str] = {}
    for seg in segments:
        speaker = seg.get("speaker", "UNKNOWN")
        if speaker not in samples:
            text = seg.get("text", "").strip()
            if text:
                samples[speaker] = text
    return samples
