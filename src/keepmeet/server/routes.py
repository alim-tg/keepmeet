import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from .. import msgraph
from ..config import load_config
from ..formatter import format_with_claude
from ..publisher import publish_to_confluence
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
from .jobs import run_job
from .models import (
    ConfigResponse,
    JobDetail,
    JobFromLinkRequest,
    JobSummary,
    PublishRequest,
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

    update_job(job_id, speaker_map=body.speaker_map, raw_transcript=raw_transcript)
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
async def reformat_job(job_id: str):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    raw_transcript = job.get("raw_transcript")
    if not raw_transcript:
        raise HTTPException(status_code=400, detail="No transcript available")

    update_job(job_id, status="reformatting")
    try:
        matched_profiles = job.get("matched_profiles", {})
        formatted_notes = format_with_claude(
            raw_transcript, job["meeting_date"], matched_profiles
        )
        update_job(job_id, status="completed", formatted_notes=formatted_notes)
        return {"ok": True, "formatted_notes": formatted_notes}
    except Exception as e:
        update_job(job_id, status="completed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/publish")
async def publish_job(job_id: str, body: PublishRequest):
    job = read_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    formatted_notes = job.get("formatted_notes")
    if not formatted_notes:
        raise HTTPException(status_code=400, detail="No formatted notes available")

    try:
        config = load_config()
        if body.space_key:
            config.confluence_space_key = body.space_key
        if body.parent_page_id:
            config.confluence_parent_page_id = body.parent_page_id

        url = publish_to_confluence(job["title"], formatted_notes, config)
        update_job(job_id, confluence_url=url, publish_status="published", publish_error=None)
        return {"ok": True, "confluence_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
