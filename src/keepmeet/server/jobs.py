import logging
import os
import threading
from datetime import datetime

from ..config import load_config
from ..formatter import format_with_claude
from ..notifier import job_url, notify
from ..publisher import publish_to_confluence
from ..settings import load_settings
from ..self_voice import SELF_SPEAKER
from ..speaker_profiles import find_profile_by_name, match_speakers
from ..transcriber import (
    TranscriptResult,
    extract_speakers,
    format_raw_transcript,
    load_waveform,
    transcribe_audio,
)
from .storage import list_jobs, read_job, update_job

AUTO_SOURCES = ("teams-auto", "teams-chat", "teams-shared", "local-recorder")

logger = logging.getLogger(__name__)


def _minus_self(count: int | None) -> int | None:
    return None if count is None else max(1, count - 1)


def run_job(job_id: str, audio_path: str, meeting_date: str,
            num_speakers: int | None = None,
            min_speakers: int | None = None,
            max_speakers: int | None = None):
    thread = threading.Thread(
        target=_process,
        args=(job_id, audio_path, meeting_date),
        kwargs={"num_speakers": num_speakers, "min_speakers": min_speakers, "max_speakers": max_speakers},
        daemon=True,
    )
    thread.start()


def _process(job_id: str, audio_path: str, meeting_date: str,
             num_speakers: int | None = None,
             min_speakers: int | None = None,
             max_speakers: int | None = None):
    try:
        config = load_config()
        settings = load_settings(config)
        job = read_job(job_id) or {}
        tracks = {
            k: v for k, v in (job.get("tracks") or {}).items() if v and os.path.exists(v)
        }
        system_track, mic_track = tracks.get("system"), tracks.get("mic")
        if system_track and mic_track:
            num_speakers = _minus_self(num_speakers)
            min_speakers = _minus_self(min_speakers)
            max_speakers = _minus_self(max_speakers)

        def on_stage(stage: str):
            update_job(job_id, stage=stage)

        update_job(job_id, status="processing", stage="transcribing")
        result = transcribe_audio(
            audio_path, config, on_stage=on_stage,
            num_speakers=num_speakers, min_speakers=min_speakers, max_speakers=max_speakers,
            system_track=system_track, mic_track=mic_track,
        )

        speakers = extract_speakers(result)
        speaker_map = {s: s for s in speakers}

        update_job(job_id, stage="matching_speakers")
        matched_profiles = {}
        speaker_embeddings = {}
        try:
            match_result = match_speakers(
                result.segments, speakers, config,
                audio=load_waveform(system_track or audio_path),
                self_audio=load_waveform(mic_track) if mic_track else None,
            )
            speaker_map = match_result["speaker_map"]
            matched_profiles = match_result["matched_profiles"]
            speaker_embeddings = match_result["speaker_embeddings"]
        except Exception:
            logger.exception("Speaker matching failed")

        if SELF_SPEAKER in speaker_map:
            my_name = settings["my_name"] or "Me"
            speaker_map[SELF_SPEAKER] = my_name
            me = find_profile_by_name(config, my_name)
            matched_profiles[SELF_SPEAKER] = {
                "slug": me.slug if me else None,
                "name": my_name,
                "role": me.role if me else "",
                "description": me.description if me else "",
                "confidence": 1.0,
                "merged": False,
                "self": True,
            }

        raw_transcript = format_raw_transcript(result, speaker_map)

        update_job(
            job_id,
            stage="formatting",
            speakers=speakers,
            speaker_map=speaker_map,
            segments=[s for s in result.segments],
            raw_transcript=raw_transcript,
            language=result.language,
            matched_profiles=matched_profiles,
            speaker_embeddings=speaker_embeddings,
        )

        formatted_notes = format_with_claude(
            raw_transcript, meeting_date, matched_profiles
        )

        job = update_job(
            job_id,
            status="completed",
            stage=None,
            formatted_notes=formatted_notes,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )
        _after_completion(job, config, speakers, matched_profiles)

    except Exception as e:
        job = update_job(job_id, status="failed", stage=None, error=str(e))
        title = job["title"] if job else job_id
        notify("Meeting processing failed", f"{title}: {e}", job_url(job_id))


def _should_auto_publish(job: dict, settings: dict, speakers: list[str], matched_profiles: dict) -> bool:
    if job.get("source") not in AUTO_SOURCES:
        return False
    mode = settings["publish_mode"]
    if mode == "auto":
        return True
    if mode == "auto_if_matched":
        return bool(speakers) and all(s in matched_profiles for s in speakers)
    return False


def _after_completion(job: dict, config, speakers: list[str], matched_profiles: dict):
    job_id = job["job_id"]
    settings = load_settings(config)

    if not _should_auto_publish(job, settings, speakers, matched_profiles):
        if job.get("source") in AUTO_SOURCES:
            update_job(job_id, publish_status="awaiting_review")
        notify("Meeting notes ready", f"{job['title']} is ready for review", job_url(job_id))
        return

    try:
        url = publish_to_confluence(job["title"], job["formatted_notes"], config)
        update_job(job_id, confluence_url=url, publish_status="published", publish_error=None)
        notify("Meeting notes published", f"{job['title']} is on Confluence", url)
    except Exception as e:
        update_job(job_id, publish_status="publish_failed", publish_error=str(e))
        notify("Auto-publish failed", f"{job['title']}: {e}", job_url(job_id))


def resume_interrupted_jobs():
    for summary in list_jobs():
        if summary["status"] not in ("pending", "processing"):
            continue
        job = read_job(summary["job_id"])
        if not job:
            continue
        audio = job.get("audio_path")
        if job.get("stage") == "downloading" or not audio or not os.path.exists(audio):
            update_job(job["job_id"], status="failed", stage=None, error="Interrupted: keepmeet was closed before this finished")
            continue
        update_job(job["job_id"], status="pending", stage=None)
        run_job(job["job_id"], audio, job["meeting_date"])
