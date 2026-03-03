import threading
from datetime import datetime

from ..config import load_config
from ..formatter import format_with_claude
from ..transcriber import (
    TranscriptResult,
    extract_speakers,
    format_raw_transcript,
    transcribe_audio,
)
from .storage import update_job


def run_job(job_id: str, audio_path: str, meeting_date: str, language: str | None = None):
    thread = threading.Thread(
        target=_process,
        args=(job_id, audio_path, meeting_date, language),
        daemon=True,
    )
    thread.start()


def _process(job_id: str, audio_path: str, meeting_date: str, language: str | None = None):
    try:
        config = load_config()
        config.language = language

        def on_stage(stage: str):
            update_job(job_id, stage=stage)

        update_job(job_id, status="processing", stage="transcribing")
        result = transcribe_audio(audio_path, config, on_stage=on_stage)

        speakers = extract_speakers(result)
        speaker_map = {s: s for s in speakers}
        raw_transcript = format_raw_transcript(result, speaker_map)

        update_job(
            job_id,
            stage="formatting",
            speakers=speakers,
            speaker_map=speaker_map,
            segments=[s for s in result.segments],
            raw_transcript=raw_transcript,
            language=result.language,
        )

        formatted_notes = format_with_claude(raw_transcript, meeting_date)

        update_job(
            job_id,
            status="completed",
            stage=None,
            formatted_notes=formatted_notes,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )

    except Exception as e:
        update_job(job_id, status="failed", stage=None, error=str(e))
