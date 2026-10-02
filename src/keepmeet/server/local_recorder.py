import json
import logging
import os
import shutil
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..notifier import job_url, notify
from ..recorder import (
    AudioRecorder,
    meeting_name_from_title,
    mix_tracks,
    pick_meeting_name,
    teams_using_mic,
    teams_window_titles,
    track_duration,
)
from ..settings import load_settings
from .ingest import start_job_from_file
from .storage import DATA_DIR

logger = logging.getLogger(__name__)

RECORDINGS_DIR = DATA_DIR / "recordings"
SESSION_FILE = "session.json"
TRACK_NAMES = ("system.wav", "mic.wav")
CHECK_SECONDS = 3
SOUND_RECENT_SECONDS = 2
END_QUIET_SECONDS = 60
MIC_MEMORY_SECONDS = 30 * 60
SOURCE = "local-recorder"

status: dict = {
    "available": os.name == "nt",
    "enabled": False,
    "teams_in_call": False,
    "recording": False,
    "mode": None,
    "started_at": None,
    "meeting_name": None,
    "mic_error": None,
    "last_error": None,
    "last_job_id": None,
    "quiet_seconds": 0,
}

_lock = threading.RLock()
_started = False
_recorder: AudioRecorder | None = None
_session: dict = {}


def _save_session():
    meta = {
        "started": _session["started"].isoformat(timespec="seconds"),
        "last_active": _session["last_active"].isoformat(timespec="seconds"),
        "mode": status["mode"],
        "meeting_name": pick_meeting_name(_session["names"]),
    }
    (_session["dir"] / SESSION_FILE).write_text(json.dumps(meta), encoding="utf-8")


def _start(mode: str):
    global _recorder, _session
    started = datetime.now()
    work_dir = RECORDINGS_DIR / started.strftime("%Y%m%d-%H%M%S")
    settings = load_settings()["local_recorder"]
    recorder = AudioRecorder(work_dir, include_mic=settings["include_mic"])
    recorder.start()
    _recorder = recorder
    now = time.monotonic()
    _session = {
        "dir": work_dir, "started": started, "last_active": started,
        "names": Counter(), "last_signal": now, "last_mic": now, "window_seen": False,
    }
    status.update(
        recording=True, mode=mode, started_at=started.isoformat(timespec="seconds"),
        meeting_name=None, mic_error=recorder.mic_error, last_error=None,
    )
    _collect_name()
    _save_session()
    logger.info(f"Recording started ({mode})")
    notify("Recording Teams call", "keepmeet is recording this call's audio")


def _collect_name() -> bool:
    found = False
    try:
        for title in teams_window_titles():
            name = meeting_name_from_title(title)
            if name:
                _session["names"][name] += 1
                found = True
        status["meeting_name"] = pick_meeting_name(_session["names"])
    except Exception:
        logger.exception("Could not read Teams window titles")
    return found


def _finalize(work_dir: Path, started: datetime, duration: float, meeting_name: str | None) -> str | None:
    min_duration = load_settings()["local_recorder"]["min_duration_seconds"]
    if duration < min_duration:
        status["last_error"] = f"Discarded a {int(duration)}s call (shorter than {min_duration}s)"
        shutil.rmtree(work_dir, ignore_errors=True)
        return None

    dest = work_dir / f"teams-call-{started.strftime('%Y%m%d-%H%M%S')}.m4a"
    try:
        outputs = mix_tracks([work_dir / name for name in TRACK_NAMES], dest)
    except Exception as e:
        status["last_error"] = str(e)
        notify("Recording failed", str(e))
        shutil.rmtree(work_dir, ignore_errors=True)
        return None

    meeting_date = started.strftime("%Y-%m-%d")
    if meeting_name:
        title = f"{meeting_name} - {meeting_date}"
    else:
        title = f"Teams call - {started.strftime('%Y-%m-%d %H:%M')}"
    extra = {name: path for name, path in outputs.items() if name != "mix"}
    job_id = start_job_from_file(dest, title, meeting_date, SOURCE, tracks=extra)
    shutil.rmtree(work_dir, ignore_errors=True)
    status["last_job_id"] = job_id
    notify("Call recorded", f"Processing: {title}", job_url(job_id))
    return job_id


def _finish() -> str | None:
    global _recorder, _session
    recorder, session = _recorder, _session
    mode = status["mode"]
    _recorder, _session = None, {}
    status.update(recording=False, mode=None, started_at=None)
    if recorder is None:
        return None

    recorder.close()
    logger.info(f"Recording stopped ({mode})")
    started: datetime = session["started"]
    ended = session["last_active"] if mode == "auto" else datetime.now()
    return _finalize(
        session["dir"], started, (ended - started).total_seconds(),
        pick_meeting_name(session["names"]),
    )


def _tick():
    settings = load_settings()["local_recorder"]
    status["enabled"] = settings["enabled"]
    in_call = teams_using_mic()
    if in_call != status["teams_in_call"]:
        logger.info(f"Teams microphone {'in use' if in_call else 'released'}")
    status["teams_in_call"] = in_call

    with _lock:
        if _recorder is None:
            if settings["enabled"] and in_call:
                _start("auto")
            return

        now = time.monotonic()
        meeting_window = _collect_name()
        if in_call:
            _session["last_mic"] = now
        sound = now - _recorder.last_sound < SOUND_RECENT_SECONDS
        mic_recent = now - _session["last_mic"] < MIC_MEMORY_SECONDS
        alive = in_call or (sound and (meeting_window or mic_recent))
        if alive:
            _session["last_signal"] = now
            _session["last_active"] = datetime.now()
        quiet = now - _session["last_signal"]
        status["quiet_seconds"] = int(quiet)

        if status["mode"] == "auto" and settings["auto_stop"] and quiet >= END_QUIET_SECONDS:
            logger.info(f"Call looks finished: mic released and {int(quiet)}s without call audio")
            _finish()
            return
        if status["mode"] != "auto":
            _session["last_active"] = datetime.now()
        _save_session()


def _loop():
    while True:
        try:
            _tick()
        except Exception as e:
            status["last_error"] = str(e)
            logger.exception("Local recorder error")
        time.sleep(CHECK_SECONDS)


def start_manual():
    with _lock:
        if _recorder is not None:
            status["mode"] = "manual"
            logger.info("Auto recording switched to manual")
            return
        _start("manual")


def stop_manual() -> str | None:
    with _lock:
        return _finish()


def _recover_sessions():
    if not RECORDINGS_DIR.exists():
        return
    for work_dir in sorted(RECORDINGS_DIR.iterdir()):
        meta_path = work_dir / SESSION_FILE
        if not work_dir.is_dir() or not meta_path.exists() or work_dir == _session.get("dir"):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(meta["started"])
            duration = max(track_duration(work_dir / name) for name in TRACK_NAMES)
            _finalize(work_dir, started, duration, meta.get("meeting_name"))
        except Exception as e:
            status["last_error"] = f"Could not recover {work_dir.name}: {e}"
            logger.exception("Recording recovery failed")


def _startup_recovery():
    with _lock:
        _recover_sessions()


def start_local_recorder():
    global _started
    if os.name != "nt":
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_startup_recovery, daemon=True, name="recorder-recovery").start()
    threading.Thread(target=_loop, daemon=True, name="local-recorder").start()


def shutdown_local_recorder():
    global _recorder, _session
    with _lock:
        if _recorder is None:
            return
        _recorder.close()
        _save_session()
        _recorder, _session = None, {}
        status.update(recording=False, mode=None, started_at=None)
