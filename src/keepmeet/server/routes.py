import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from ..config import load_config
from ..formatter import format_with_claude
from ..publisher import publish_to_confluence
from ..speaker_profiles import (
    delete_profile,
    extract_speaker_embedding,
    extract_voice_sample,
    list_profiles,
    load_profile,
    save_profile,
    update_profile,
)
from ..transcriber import TranscriptResult, format_raw_transcript
from .jobs import run_job
from .models import (
    ConfigResponse,
    JobDetail,
    JobSummary,
    PublishRequest,
    SpeakerProfileCreateRequest,
    SpeakerProfileResponse,
    SpeakerProfileUpdateRequest,
    SpeakerUpdateRequest,
)
from .storage import UPLOADS_DIR, create_job, delete_job, list_jobs, read_job, update_job

router = APIRouter(prefix="/api")


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
    run_job(job_id, str(audio_path), meeting_date)

    return {"job_id": job_id}


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
    return {"ok": True, "raw_transcript": raw_transcript}


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
        update_job(job_id, confluence_url=url)
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
    embedding = None
    try:
        embedding = extract_speaker_embedding(
            audio_path, segments, speaker_id, config.hf_token
        )
    except Exception:
        pass

    profile = save_profile(config, body.name, body.role, body.description, embedding)

    try:
        profile_dir = Path(config.speaker_profiles_dir) / profile.slug
        extract_voice_sample(audio_path, segments, speaker_id, profile_dir)
    except Exception:
        pass

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
