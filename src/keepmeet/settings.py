import copy
import json
import threading
from pathlib import Path

SETTINGS_PATH = Path("data") / "settings.json"

PUBLISH_MODES = ("manual", "auto", "auto_if_matched")
TRANSCRIPTION_MODELS = ("whisper-large-v3", "whisper-large-v3-turbo")
SOURCES = ("onedrive", "meeting_chats", "shared_with_me")

DEFAULTS = {
    "watcher_enabled": True,
    "poll_interval_seconds": 300,
    "recordings_folder": "Recordings",
    "sources": {
        "onedrive": True,
        "meeting_chats": True,
        "shared_with_me": False,
    },
    "meeting_filter": "",
    "publish_mode": "manual",
    "notifications": True,
    "my_name": "",
    "confluence": {
        "target_url": "",
    },
    "knowledge": {
        "path": "",
        "lookups": True,
    },
    "transcription": {
        "model": "whisper-large-v3",
        "languages": ["ru", "en"],
        "vocabulary": "",
    },
    "local_recorder": {
        "enabled": False,
        "include_mic": True,
        "auto_stop": True,
        "min_duration_seconds": 60,
    },
}

_lock = threading.Lock()


def _read_file() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key not in out:
            continue
        if isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _defaults_from_config(config) -> dict:
    base = copy.deepcopy(DEFAULTS)
    if config is not None:
        base["watcher_enabled"] = config.teams_enabled
        base["poll_interval_seconds"] = config.teams_poll_interval
        base["recordings_folder"] = config.teams_recordings_folder
    return base


def _validate(settings: dict) -> dict:
    if settings["publish_mode"] not in PUBLISH_MODES:
        raise ValueError(f"publish_mode must be one of {', '.join(PUBLISH_MODES)}")
    settings["poll_interval_seconds"] = max(30, int(settings["poll_interval_seconds"]))
    settings["meeting_filter"] = str(settings["meeting_filter"] or "").strip()
    settings["recordings_folder"] = str(settings["recordings_folder"] or "Recordings").strip()
    settings["sources"] = {k: bool(settings["sources"].get(k)) for k in SOURCES}
    settings["my_name"] = str(settings["my_name"] or "").strip()
    settings["confluence"]["target_url"] = str(settings["confluence"]["target_url"] or "").strip()
    settings["knowledge"]["path"] = str(settings["knowledge"]["path"] or "").strip()
    settings["knowledge"]["lookups"] = bool(settings["knowledge"]["lookups"])
    transcription = settings["transcription"]
    if transcription["model"] not in TRANSCRIPTION_MODELS:
        raise ValueError(f"transcription.model must be one of {', '.join(TRANSCRIPTION_MODELS)}")
    languages = [str(lang).strip().lower() for lang in transcription["languages"] or [] if str(lang).strip()]
    transcription["languages"] = list(dict.fromkeys(languages)) or ["ru", "en"]
    transcription["vocabulary"] = str(transcription["vocabulary"] or "").strip()
    recorder = settings["local_recorder"]
    recorder["enabled"] = bool(recorder["enabled"])
    recorder["include_mic"] = bool(recorder["include_mic"])
    recorder["auto_stop"] = bool(recorder["auto_stop"])
    recorder["min_duration_seconds"] = max(0, int(recorder["min_duration_seconds"]))
    return settings


def load_settings(config=None) -> dict:
    with _lock:
        return _validate(_merge(_defaults_from_config(config), _read_file()))


def save_settings(patch: dict, config=None) -> dict:
    with _lock:
        current = _merge(_defaults_from_config(config), _read_file())
        updated = _validate(_merge(current, patch))
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return updated


def matches_filter(settings: dict, *texts: str | None) -> bool:
    needle = settings.get("meeting_filter", "").lower()
    if not needle:
        return True
    return any(needle in (t or "").lower() for t in texts)
