import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .. import msgraph
from .jobs import run_job
from .storage import UPLOADS_DIR, create_job, update_job

FILENAME_RE = re.compile(r"^(?P<title>.+?)-(?P<date>\d{8})_\d{6}-")


def parse_recording_filename(name: str) -> tuple[str, str]:
    m = FILENAME_RE.match(name)
    if m:
        d = m.group("date")
        meeting_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return f"{m.group('title').strip()} - {meeting_date}", meeting_date
    return Path(name).stem, datetime.now().strftime("%Y-%m-%d")


def new_job_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:6]}"


def _job_record(job_id, title, meeting_date, filename, dest, language, source, stage) -> dict:
    return {
        "job_id": job_id,
        "status": "pending",
        "stage": stage,
        "error": None,
        "title": title,
        "meeting_date": meeting_date,
        "language": language or None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "completed_at": None,
        "audio_filename": filename,
        "audio_path": str(dest),
        "speakers": [],
        "speaker_map": {},
        "segments": [],
        "raw_transcript": None,
        "formatted_notes": None,
        "confluence_url": None,
        "matched_profiles": {},
        "source": source,
    }


def start_job_from_drive_item(
    token: str,
    drive_id: str,
    item_id: str,
    filename: str,
    title: str,
    meeting_date: str,
    language: str | None = None,
    source: str | None = None,
) -> str:
    job_id = new_job_id()
    dest = UPLOADS_DIR / job_id / filename
    create_job(job_id, _job_record(
        job_id, title, meeting_date, filename, dest, language, source, "downloading",
    ))

    def _download_and_run():
        try:
            msgraph.download_item(token, drive_id, item_id, dest)
        except Exception as e:
            update_job(job_id, status="failed", stage=None, error=f"Download failed: {e}")
            return
        update_job(job_id, stage=None)
        run_job(job_id, str(dest), meeting_date)

    threading.Thread(target=_download_and_run, daemon=True).start()
    return job_id


def start_job_from_file(
    path: Path,
    title: str,
    meeting_date: str,
    source: str,
    run: bool = True,
    tracks: dict[str, Path] | None = None,
) -> str:
    job_id = new_job_id()
    dest = UPLOADS_DIR / job_id / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest)
    record = _job_record(job_id, title, meeting_date, path.name, dest, None, source, None)
    if tracks:
        record["tracks"] = {}
        for name, track in tracks.items():
            track_dest = dest.parent / track.name
            shutil.move(str(track), track_dest)
            record["tracks"][name] = str(track_dest)
    create_job(job_id, record)
    if run:
        run_job(job_id, str(dest), meeting_date)
    return job_id
