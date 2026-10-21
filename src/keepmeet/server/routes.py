import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from .. import msgraph
from ..config import load_config
from ..formatter import unnamed_labels
from ..confluence_auth import (
    ConfluenceAuthError,
    clear_credentials,
    current_user,
    load_credentials,
    save_credentials,
)
from ..publisher import PublishError, publish_to_confluence, resolve_target
from ..settings import load_settings, save_settings
from ..self_voice import SELF_SPEAKER
from ..speaker_profiles import (
    delete_profile,
    extract_speaker_embedding,
    extract_voice_sample,
    learn_from_job,
    list_profiles,
    load_profile,
    save_profile,
    update_profile,
)
from ..transcriber import TranscriptResult, format_raw_transcript
from .ingest import parse_recording_filename, start_job_from_drive_item
from .jobs import build_notes, publish_meta, run_job
from .models import (
    ConfigResponse,
    ConfluenceAuthRequest,
    JobDetail,
    JobFromLinkRequest,
    JobSummary,
    NotesUpdateRequest,
    PublishRequest,
    ReformatRequest,
    Settings,
    SettingsUpdateRequest,
    SpeakerProfileCreateRequest,
    SpeakerProfileResponse,
    SpeakerProfileUpdateRequest,
    SpeakerUpdateRequest,
)
from .storage import UPLOADS_DIR, create_job, delete_job, list_jobs, read_job, update_job

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)


def _profile_response(p, config) -> SpeakerProfileResponse:
    profile_dir = Path(config.speaker_profiles_dir) / p.slug
    return SpeakerProfileResponse(
        slug=p.slug,
        name=p.name,
        role=p.role,
        description=p.description,
        has_embedding=p.embedding is not None,
        has_voice_sample=(profile_dir / "voice_sample.wav").exists(),
    )


@router.post("/jobs")
async def create_new_job(
    file: UploadFile = File(...),
    title: str = Form(""),
    meeting_date: str = Form(""),
    language: str = Form(""),
    num_speakers: int | None = Form(None),
    min_speakers: int | None = Form(None),
    max_speakers: int | None = Form(None),
):
    now = datetime.now()
    short_id = uuid.uuid4().hex[:6]
    job_id = now.strftime("%Y%m%d-%H%M%S") + f"-{short_id}"

    if not meeting_date:
        meeting_date = now.strftime("%Y-%m-%d")
    if not title:
        title = f"Daily Standup - {meeting_date}"

    upload_dir = UPLOADS_DIR / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = file.filename or "recording.m4a"
    audio_path = upload_dir / filename
    content = await file.read()
    audio_path.write_bytes(content)

    job_data = {
        "job_id": job_id,
        "status": "pending",
        "stage": None,
        "error": None,
        "title": title,
        "meeting_date": meeting_date,
        "language": language or None,
        "created_at": now.isoformat(timespec="seconds"),
        "completed_at": None,
        "audio_filename": filename,
        "audio_path": str(audio_path),
        "speakers": [],
        "speaker_map": {},
        "segments": [],
        "raw_transcript": None,
        "formatted_notes": None,
        "confluence_url": None,
        "matched_profiles": {},
    }

    create_job(job_id, job_data)
    run_job(job_id, str(audio_path), meeting_date,
            num_speakers=num_speakers, min_speakers=min_speakers, max_speakers=max_speakers)

    return {"job_id": job_id}


@router.post("/jobs/from-link")
def create_job_from_link(body: JobFromLinkRequest):
    try:
        config = load_config()
        token = msgraph.acquire_token(config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not signed in to Microsoft Graph. Run: keepmeet teams login",
        )

    try:
        item = msgraph.resolve_share_link(token, body.url)
    except msgraph.GraphError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if "file" not in item:
        raise HTTPException(status_code=400, detail="Link does not point to a file")

    filename = item.get("name") or "recording.mp4"
    parsed_title, parsed_date = parse_recording_filename(filename)
    job_id = start_job_from_drive_item(
        token,
        item["parentReference"]["driveId"],
        item["id"],
        filename,
        body.title or parsed_title,
        body.meeting_date or parsed_date,
        language=body.language,
        source="teams-link",
    )
    return {"job_id": job_id}


@router.get("/teams/status")
def teams_status():
    from .teams_watcher import status as watcher_status

    info = dict(watcher_status)
    try:
        config = load_config()
        settings = load_settings(config)
        info["enabled"] = settings["watcher_enabled"]
        info["configured"] = bool(config.graph_client_id and config.graph_tenant_id)
        account = msgraph.get_account(config) if info["configured"] else None
        info["signed_in"] = account is not None
        info["account"] = account.get("username") if account else None
        info["recordings_folder"] = settings["recordings_folder"]
        info["poll_interval_seconds"] = settings["poll_interval_seconds"]
    except Exception as e:
        info.update(enabled=False, configured=False, account=None, last_error=str(e))
    return info


@router.post("/teams/poll")
def teams_poll():
    from .teams_watcher import trigger_poll

    trigger_poll()
    return {"ok": True}


@router.post("/teams/login")
def teams_login():
    from .teams_watcher import start_login

    try:
        return start_login(load_config())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/recorder/status")
def recorder_status():
    from .local_recorder import status as recorder_state

    return dict(recorder_state)


@router.post("/recorder/start")
def recorder_start():
    from .local_recorder import start_manual, status as recorder_state

    try:
        start_manual()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return dict(recorder_state)


@router.post("/recorder/stop")
def recorder_stop():
    from .local_recorder import stop_manual

    try:
        job_id = stop_manual()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "job_id": job_id}


@router.get("/note-formats")
def get_note_formats():
    from ..note_formats import options

    return {"formats": options()}


@router.get("/knowledge/status")
def knowledge_status():
    from .. import knowledge

    path = load_settings(load_config())["knowledge"]["path"]
    if not path:
        return {"configured": False, "loaded": False}
    kb = knowledge.load(path)
    if kb is None:
        return {"configured": True, "loaded": False, "error": "No glossary.md or index.md found in that folder"}
    return {"configured": True, "loaded": True, "digest_chars": len(kb.digest), "terms": len(kb.terms)}


@router.get("/transcription/suggested-terms")
def get_suggested_terms():
    from ..transcriber import suggested_terms

    try:
        return {"terms": suggested_terms(load_config())}
    except Exception as e:
        logger.exception("Could not collect suggested terms")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings", response_model=Settings)
def get_settings():
    try:
        config = load_config()
    except Exception:
        config = None
    return load_settings(config)


@router.put("/settings", response_model=Settings)
def put_settings(body: SettingsUpdateRequest):
    from .teams_watcher import trigger_poll

    try:
        config = load_config()
    except Exception:
        config = None
    try:
        updated = save_settings(body.model_dump(exclude_none=True), config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    trigger_poll()
    return updated


@router.get("/jobs", response_model=list[JobSummary])
async def get_jobs():
    return list_jobs()


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def get_job(job_id: str):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/jobs/{job_id}")
async def remove_job(job_id: str):
    if not delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


@router.patch("/jobs/{job_id}/speakers")
async def update_speakers(job_id: str, body: SpeakerUpdateRequest):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    segments = job.get("segments", [])
    if not segments:
        raise HTTPException(status_code=400, detail="No segments available")

    result = TranscriptResult(segments=segments, language=job.get("language", ""))
    raw_transcript = format_raw_transcript(result, body.speaker_map)

    suggestions = {
        sid: name for sid, name in (job.get("name_suggestions") or {}).items()
        if body.speaker_map.get(sid, sid) == sid
    }
    update_job(job_id, speaker_map=body.speaker_map, raw_transcript=raw_transcript, name_suggestions=suggestions)
    job = read_job(job_id)
    threading.Thread(target=_learn_voices, args=(job, body.speaker_map), daemon=True).start()
    return {"ok": True, "raw_transcript": raw_transcript}


def _learn_voices(job: dict, speaker_map: dict[str, str]):
    try:
        learned = learn_from_job(load_config(), job, speaker_map)
        update_job(job["job_id"], learned_voices=learned)
    except Exception:
        logger.exception("Learning voices failed")


def _speaker_audio_path(job: dict, speaker_id: str) -> str:
    tracks = job.get("tracks") or {}
    if speaker_id == SELF_SPEAKER and tracks.get("mic"):
        return tracks["mic"]
    return tracks.get("system") or job["audio_path"]


@router.post("/jobs/{job_id}/reformat")
def reformat_job(job_id: str, body: ReformatRequest | None = None):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.get("raw_transcript"):
        raise HTTPException(status_code=400, detail="No transcript available")

    if body is not None and body.context is not None:
        job = update_job(job_id, notes_context=body.context.strip())
    if body is not None and body.note_format is not None:
        from ..note_formats import AUTO, FORMATS

        if body.note_format not in FORMATS and body.note_format != AUTO:
            raise HTTPException(status_code=400, detail=f"Unknown note format {body.note_format}")
        job = update_job(job_id, note_format_override=None if body.note_format == AUTO else body.note_format)
    update_job(job_id, status="reformatting")
    try:
        notes_update = build_notes(job)
    except Exception as e:
        update_job(job_id, status="completed")
        raise HTTPException(status_code=500, detail=str(e))
    update_job(job_id, status="completed", **notes_update)
    return {"ok": True, **notes_update}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")

    if job.get("raw_transcript") and job.get("segments"):
        update_job(job_id, status="processing", stage="formatting", error=None)
        threading.Thread(target=_retry_notes, args=(job_id,), daemon=True).start()
        return {"ok": True, "mode": "notes"}

    audio = job.get("audio_path")
    if not audio or not Path(audio).exists():
        raise HTTPException(status_code=400, detail="The recording file is missing, so this job can't be retried")
    update_job(job_id, status="pending", stage=None, error=None)
    run_job(job_id, audio, job["meeting_date"])
    return {"ok": True, "mode": "full"}


BUSY_STATUSES = ("pending", "processing", "reformatting")


@router.post("/jobs/{job_id}/retranscribe")
def retranscribe_job(job_id: str):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in BUSY_STATUSES:
        raise HTTPException(status_code=409, detail="This meeting is already being processed")
    audio = job.get("audio_path")
    if not audio or not Path(audio).exists():
        raise HTTPException(status_code=400, detail="The recording file is missing, so it can't be transcribed again")

    update_job(
        job_id,
        status="pending", stage=None, error=None, completed_at=None,
        speakers=[], speaker_map={}, segments=[], raw_transcript=None,
        formatted_notes=None, matched_profiles={}, speaker_embeddings={},
        name_suggestions={}, notes_edited=False, learned_voices=[],
        publish_status=None, publish_error=None,
    )
    run_job(job_id, audio, job["meeting_date"])
    return {"ok": True}


def _retry_notes(job_id: str):
    try:
        notes_update = build_notes(read_job(job_id))
        update_job(
            job_id, status="completed", stage=None,
            completed_at=datetime.now().isoformat(timespec="seconds"), **notes_update,
        )
    except Exception as e:
        logger.exception("Retrying notes failed")
        update_job(job_id, status="failed", stage=None, error=str(e))


@router.put("/jobs/{job_id}/notes")
def save_notes(job_id: str, body: NotesUpdateRequest):
    if not read_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    update_job(job_id, formatted_notes=body.formatted_notes.strip(), notes_edited=True)
    return {"ok": True, "unnamed": unnamed_labels(body.formatted_notes)}


@router.post("/jobs/{job_id}/publish")
async def publish_job(job_id: str, body: PublishRequest):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    formatted_notes = job.get("formatted_notes")
    if not formatted_notes:
        raise HTTPException(status_code=400, detail="No formatted notes available")

    title = (body.title or job.get("publish_title") or job["title"]).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Page title is required")
    leftover = unnamed_labels(formatted_notes)
    if leftover:
        raise HTTPException(
            status_code=400,
            detail=f"Notes still mention unnamed speakers ({', '.join(leftover)}). Name them in the Speakers tab and regenerate, or edit the notes.",
        )
    try:
        url = publish_to_confluence(title, formatted_notes, load_config(), publish_meta(job))
    except PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    update_job(
        job_id, confluence_url=url, publish_title=title,
        publish_status="published", publish_error=None,
    )
    return {"ok": True, "confluence_url": url, "title": title}


def _confluence_status() -> dict:
    info = {"connected": False, "user": None, "error": None, "target": None}
    try:
        config = load_config()
        target = resolve_target(config)
        info["target"] = target if target.get("base_url") else None
        creds = load_credentials(config)
        if creds and target.get("base_url"):
            info["user"] = current_user(target["base_url"], *creds)
            info["connected"] = True
        elif creds:
            info["error"] = "Set the Confluence folder link first"
    except Exception as e:
        info["error"] = str(e)
    return info


@router.get("/confluence/status")
def confluence_status():
    return _confluence_status()


@router.post("/confluence/auth")
def confluence_connect(body: ConfluenceAuthRequest):
    email, token = body.email.strip(), body.token.strip()
    if not email or not token:
        raise HTTPException(status_code=400, detail="Email and API token are required")
    try:
        target = resolve_target(load_config())
        if not target.get("base_url"):
            raise HTTPException(status_code=400, detail="Set the Confluence folder link first")
        current_user(target["base_url"], email, token)
    except (ConfluenceAuthError, PublishError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    save_credentials(email, token)
    return _confluence_status()


@router.delete("/confluence/auth")
def confluence_disconnect():
    clear_credentials()
    return _confluence_status()


@router.get("/jobs/{job_id}/audio")
async def get_audio(job_id: str):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    audio_path = Path(job["audio_path"])
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    ext = audio_path.suffix.lower()
    media_types = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}
    return FileResponse(audio_path, media_type=media_types.get(ext, "audio/mpeg"))


@router.get("/profiles", response_model=list[SpeakerProfileResponse])
async def get_profiles():
    config = load_config()
    profiles = list_profiles(config)
    return [_profile_response(p, config) for p in profiles]


@router.get("/profiles/{slug}", response_model=SpeakerProfileResponse)
async def get_profile(slug: str):
    config = load_config()
    profile_dir = Path(config.speaker_profiles_dir) / slug
    if not profile_dir.exists() or not (profile_dir / "profile.json").exists():
        raise HTTPException(status_code=404, detail="Profile not found")
    p = load_profile(profile_dir)
    return _profile_response(p, config)


@router.post("/profiles/from-job/{job_id}/{speaker_id}", response_model=SpeakerProfileResponse)
async def create_profile_from_job(
    job_id: str, speaker_id: str, body: SpeakerProfileCreateRequest
):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    segments = job.get("segments", [])
    audio_path = job.get("audio_path", "")
    if not segments or not audio_path:
        raise HTTPException(status_code=400, detail="Job has no segments or audio")

    config = load_config()
    speaker_audio = _speaker_audio_path(job, speaker_id)
    embedding = None
    try:
        embedding = extract_speaker_embedding(speaker_audio, segments, speaker_id)
    except Exception:
        logger.exception("Could not extract speaker embedding")

    profile = save_profile(
        config, body.name, body.role, body.description, embedding,
        source={"job": job_id, "speaker": speaker_id},
    )

    try:
        profile_dir = Path(config.speaker_profiles_dir) / profile.slug
        extract_voice_sample(speaker_audio, segments, speaker_id, profile_dir)
    except Exception:
        logger.exception("Could not extract voice sample")

    return _profile_response(profile, config)


@router.patch("/profiles/{slug}", response_model=SpeakerProfileResponse)
async def patch_profile(slug: str, body: SpeakerProfileUpdateRequest):
    config = load_config()
    profile = update_profile(config, slug, name=body.name, role=body.role, description=body.description)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(profile, config)


@router.delete("/profiles/{slug}")
async def remove_profile(slug: str):
    config = load_config()
    if not delete_profile(config, slug):
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"ok": True}


@router.get("/profiles/{slug}/voice-sample")
async def get_voice_sample(slug: str):
    config = load_config()
    wav_path = Path(config.speaker_profiles_dir) / slug / "voice_sample.wav"
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="Voice sample not found")
    return FileResponse(wav_path, media_type="audio/wav")


@router.get("/config", response_model=ConfigResponse)
async def get_config():
    try:
        config = load_config()
        return ConfigResponse(
            confluence_base_url=config.confluence_base_url,
            confluence_space_key=config.confluence_space_key,
            confluence_parent_page_id=config.confluence_parent_page_id,
        )
    except Exception:
        return ConfigResponse(
            confluence_base_url="",
            confluence_space_key="",
            confluence_parent_page_id=None,
        )
