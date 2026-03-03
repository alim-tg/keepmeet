import dataclasses
from datetime import date
from pathlib import Path

import click

from .config import Config
from .formatter import FormatterError, format_with_claude
from .publisher import PublishError, publish_to_confluence
from .speakers import load_speaker_map, prompt_speaker_mapping, save_speaker_map
from .transcriber import (
    TranscriptResult,
    extract_speakers,
    format_raw_transcript,
    transcribe_audio,
)


@dataclasses.dataclass
class PipelineOptions:
    meeting_date: str
    speaker_profile: str
    output_dir: str
    skip_diarization: bool = False
    skip_format: bool = False
    skip_publish: bool = False
    skip_speaker_prompt: bool = False


@dataclasses.dataclass
class PipelineResult:
    raw_transcript: str
    formatted_notes: str | None
    confluence_url: str | None


def process_meeting(
    audio_path: str, config: Config, options: PipelineOptions
) -> PipelineResult:
    click.echo(f"Processing: {audio_path}")

    click.echo("Transcribing audio (this may take a few minutes)...")
    transcript_result = transcribe_audio(audio_path, config)
    click.echo(f"Transcription complete. Language: {transcript_result.language}, "
               f"Segments: {len(transcript_result.segments)}")

    speaker_map: dict[str, str] = {}
    if not options.skip_diarization:
        speaker_map = load_speaker_map(options.speaker_profile)
        unknown = [
            s for s in extract_speakers(transcript_result) if s not in speaker_map
        ]
        if unknown and not options.skip_speaker_prompt:
            speaker_map = prompt_speaker_mapping(
                transcript_result.segments, speaker_map
            )
            save_speaker_map(options.speaker_profile, speaker_map)

    raw_transcript = format_raw_transcript(transcript_result, speaker_map)

    out_dir = Path(options.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = out_dir / f"transcript-{options.meeting_date}.txt"
    transcript_path.write_text(raw_transcript, encoding="utf-8")
    click.echo(f"Raw transcript saved: {transcript_path}")

    formatted_notes = None
    if not options.skip_format:
        click.echo("Formatting with Claude...")
        try:
            formatted_notes = format_with_claude(raw_transcript, options.meeting_date)
            notes_path = out_dir / f"notes-{options.meeting_date}.md"
            notes_path.write_text(formatted_notes, encoding="utf-8")
            click.echo(f"Meeting notes saved: {notes_path}")
        except FormatterError as e:
            click.echo(f"Warning: Formatting failed: {e}", err=True)
            click.echo("Raw transcript is still available.", err=True)

    confluence_url = None
    if not options.skip_publish and formatted_notes:
        click.echo("Publishing to Confluence...")
        try:
            title = f"Daily Standup - {options.meeting_date}"
            confluence_url = publish_to_confluence(title, formatted_notes, config)
            click.echo(f"Published: {confluence_url}")
        except PublishError as e:
            click.echo(f"Warning: Publishing failed: {e}", err=True)
            click.echo("Meeting notes are saved locally.", err=True)

    return PipelineResult(
        raw_transcript=raw_transcript,
        formatted_notes=formatted_notes,
        confluence_url=confluence_url,
    )
