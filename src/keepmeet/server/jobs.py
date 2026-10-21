import logging
import os
import threading
from datetime import datetime

from ..config import load_config
from ..formatter import generate_notes, unnamed_labels
from ..notifier import job_url, notify
from ..publisher import publish_to_confluence
from ..settings import load_settings
from ..self_voice import SELF_SPEAKER
from ..speaker_id import combine, identify_from_conversation
from ..speaker_profiles import find_profile_by_name, match_speakers, reinforce_profiles
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


class JobDeleted(Exception):
    pass


def _minus_self(count: int | None) -> int | None:
    return None if count is None else max(1, count - 1)


def _roster(config, my_name: str) -> list[str]:
    from ..formatter import SPEAKER_LABEL_RE
    from ..speaker_profiles import list_profiles

    names = [my_name] + [p.name for p in list_profiles(config)]
    for summary in list_jobs()[:30]:
        job = read_job(summary["job_id"]) or {}
        names += [n for n in (job.get("speaker_map") or {}).values() if n and not SPEAKER_LABEL_RE.fullmatch(n)]
    return list(dict.fromkeys(n for n in names if n and n != "Me"))


def identify_speakers(job_id, result, speakers, config, my_name, audio, self_audio):
    speaker_map = {s: s for s in speakers}
    embeddings: dict = {}
    voice: dict = {}
    voice_scores: dict = {}
    same_voice: dict = {}
    try:
        match = match_speakers(result.segments, speakers, config, audio=audio, self_audio=self_audio)
        embeddings = match["speaker_embeddings"]
        voice = {k: v for k, v in match["matched_profiles"].items() if k != SELF_SPEAKER}
        voice_scores = match["voice_scores"]
        same_voice = match["same_voice"]
    except Exception:
        logger.exception("Voice matching failed")

    labels = [s for s in speakers if s != SELF_SPEAKER]
    transcript = format_raw_transcript(result, {SELF_SPEAKER: my_name})
    conversation = identify_from_conversation(transcript, labels, _roster(config, my_name), voice_scores, my_name)
    decided = combine(labels, voice, conversation, same_voice)

    if SELF_SPEAKER in speakers:
        me = find_profile_by_name(config, my_name)
        decided[SELF_SPEAKER] = {
            "slug": me.slug if me else None,
            "name": my_name,
            "role": me.role if me else "",
            "description": me.description if me else "",
            "confidence": 1.0,
            "merged": False,
            "self": True,
            "source": "microphone",
        }
    for sid, info in decided.items():
        speaker_map[sid] = info["name"]
    try:
        reinforced = reinforce_profiles(config, job_id, decided, embeddings)
        if reinforced:
            logger.info("Reinforced voice profiles: %s", reinforced)
    except Exception:
        logger.exception("Could not reinforce voice profiles")
    return speaker_map, decided, embeddings


def build_notes(job: dict) -> dict:
    from .. import knowledge

    settings = load_settings(load_config())
    kb = knowledge.load(settings["knowledge"]["path"])
    notes, names, used_format = generate_notes(
        job["raw_transcript"],
        job["meeting_date"],
        job.get("matched_profiles") or {},
        job.get("notes_context"),
        title=job.get("title"),
        format_key=job.get("note_format_override"),
        knowledge=kb,
        lookups=settings["knowledge"]["lookups"],
    )
    speaker_map = job.get("speaker_map") or {}
    suggestions = {
        sid: name for sid, name in names.items()
        if sid in speaker_map and speaker_map[sid] == sid
    }
    return {
        "formatted_notes": notes,
        "name_suggestions": suggestions,
        "notes_edited": False,
        "note_format": used_format,
    }


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
            if update_job(job_id, stage=stage) is None:
                raise JobDeleted()

        update_job(job_id, status="processing", stage="transcribing")
        result = transcribe_audio(
            audio_path, config, on_stage=on_stage,
            num_speakers=num_speakers, min_speakers=min_speakers, max_speakers=max_speakers,
            system_track=system_track, mic_track=mic_track,
        )

        speakers = extract_speakers(result)
        speaker_map = {s: s for s in speakers}

        update_job(job_id, stage="matching_speakers")
        my_name = settings["my_name"] or "Me"
        speaker_map, matched_profiles, speaker_embeddings = identify_speakers(
            job_id, result, speakers, config, my_name,
            audio=load_waveform(system_track or audio_path),
            self_audio=load_waveform(mic_track) if mic_track else None,
        )

        raw_transcript = format_raw_transcript(result, speaker_map)

        update_job(
            job_id,
            stage="formatting",
            speakers=speakers,
            speaker_map=speaker_map,
            segments=[s for s in result.segments],
            raw_transcript=raw_transcript,
            language=result.language,
            languages=result.languages,
            matched_profiles=matched_profiles,
            speaker_embeddings=speaker_embeddings,
        )

        current = read_job(job_id)
        if current is None:
            raise JobDeleted()
        notes_update = build_notes(current)

        job = update_job(
            job_id,
            status="completed",
            stage=None,
            completed_at=datetime.now().isoformat(timespec="seconds"),
            **notes_update,
        )
        if job is None:
            raise JobDeleted()
        _after_completion(job, config, speakers, matched_profiles)

    except JobDeleted:
        logger.info(f"Job {job_id} was deleted during processing, stopped")
    except Exception as e:
        if read_job(job_id) is None:
            logger.info(f"Job {job_id} was deleted during processing, stopped")
            return
        logger.exception(f"Job {job_id} failed")
        job = update_job(job_id, status="failed", stage=None, error=str(e))
        notify("Meeting processing failed", f"{job['title']}: {e}", job_url(job_id))


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

    leftover = unnamed_labels(job.get("formatted_notes"))
    if leftover and job.get("source") in AUTO_SOURCES and settings["publish_mode"] != "manual":
        update_job(job_id, publish_status="awaiting_review", publish_error=f"Unnamed speakers in notes: {', '.join(leftover)}")
        notify("Meeting notes need a name check", f"{job['title']}: name {', '.join(leftover)} before publishing", job_url(job_id))
        return

    if not _should_auto_publish(job, settings, speakers, matched_profiles):
        if job.get("source") in AUTO_SOURCES:
            update_job(job_id, publish_status="awaiting_review")
        notify("Meeting notes ready", f"{job['title']} is ready for review", job_url(job_id))
        return

    try:
        title = job.get("publish_title") or job["title"]
        url = publish_to_confluence(title, job["formatted_notes"], config, publish_meta(job))
        update_job(job_id, confluence_url=url, publish_title=title, publish_status="published", publish_error=None)
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


def publish_meta(job: dict) -> dict:
    from ..formatter import SPEAKER_LABEL_RE

    names = []
    for sid in job.get("speakers") or []:
        name = (job.get("speaker_map") or {}).get(sid, sid)
        if name and not SPEAKER_LABEL_RE.fullmatch(name) and name not in names:
            names.append(name)
    ends = [s.get("end", 0) for s in job.get("segments") or []]
    minutes = round(max(ends) / 60) if ends else 0
    return {
        "date": job.get("meeting_date"),
        "participants": names,
        "duration": f"{minutes} min" if minutes else None,
    }
