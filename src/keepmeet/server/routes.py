import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from ..config import load_config
from ..formatter import format_with_claude
from ..publisher import publish_to_confluence
from ..transcriber import TranscriptResult, format_raw_transcript
from .jobs import run_job
from .models import (
    ConfigResponse,
    JobDetail,
    JobSummary,
    PublishRequest,
    SpeakerUpdateRequest,
)
from .storage import UPLOADS_DIR, create_job, delete_job, list_jobs, read_job, update_job

router = APIRouter(prefix="/api")


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
    }

    create_job(job_id, job_data)
    run_job(job_id, str(audio_path), meeting_date, language=job_data["language"])

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
        formatted_notes = format_with_claude(raw_transcript, job["meeting_date"])
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
