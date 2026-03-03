import json
import shutil
from pathlib import Path

DATA_DIR = Path("data")
JOBS_DIR = DATA_DIR / "jobs"
UPLOADS_DIR = DATA_DIR / "uploads"


def _ensure_dirs():
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def create_job(job_id: str, data: dict) -> dict:
    _ensure_dirs()
    path = JOBS_DIR / f"{job_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def read_job(job_id: str) -> dict | None:
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_job(job_id: str, **fields) -> dict | None:
    data = read_job(job_id)
    if data is None:
        return None
    data.update(fields)
    path = JOBS_DIR / f"{job_id}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def list_jobs() -> list[dict]:
    _ensure_dirs()
    jobs = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            jobs.append({
                "job_id": data["job_id"],
                "status": data["status"],
                "title": data["title"],
                "meeting_date": data["meeting_date"],
                "language": data.get("language"),
                "created_at": data["created_at"],
            })
        except (json.JSONDecodeError, KeyError):
            continue
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jobs


def delete_job(job_id: str) -> bool:
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        return False
    path.unlink()
    upload_dir = UPLOADS_DIR / job_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    return True
