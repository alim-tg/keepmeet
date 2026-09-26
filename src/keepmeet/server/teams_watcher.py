import json
import threading
from datetime import datetime, timezone

from .. import msgraph
from ..config import load_config
from ..notifier import job_url, notify
from ..settings import load_settings, matches_filter
from .ingest import FILENAME_RE, parse_recording_filename, start_job_from_drive_item
from .storage import DATA_DIR

STATE_PATH = DATA_DIR / "teams_ingest.json"
MEDIA_EXTENSIONS = (".mp4", ".m4a", ".mp3", ".wav", ".webm", ".mkv")
SETTLE_SECONDS = 120
MAX_RESOLVE_ATTEMPTS = 3

status: dict = {
    "running": False,
    "signed_in": False,
    "chat_access": None,
    "last_poll_at": None,
    "last_error": None,
    "ingested_count": 0,
    "sources": {},
    "login": {"state": "idle"},
}

_lock = threading.Lock()
_poll_lock = threading.Lock()
_wake = threading.Event()
_started = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_state() -> dict:
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    state.setdefault("processed", {})
    state.setdefault("chat_urls", {})
    if "initialized" in state:
        state.setdefault("onedrive_initialized", state.pop("initialized"))
    return state


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_settled(modified: str | None) -> bool:
    ts = _parse_ts(modified)
    if ts is None:
        return True
    return (datetime.now(timezone.utc) - ts).total_seconds() > SETTLE_SECONDS


def _is_media(name: str) -> bool:
    return name.lower().endswith(MEDIA_EXTENSIONS)


def _ingest(token, state, settings, drive_id, item_id, name, source, hint=None) -> bool:
    if item_id in state["processed"]:
        return False
    title, meeting_date = parse_recording_filename(name)
    if not matches_filter(settings, title, name, hint):
        state["processed"][item_id] = {"name": name, "job_id": None, "skipped": "filter"}
        return True
    if not FILENAME_RE.match(name) and hint:
        title = f"{hint} - {meeting_date}"
    job_id = start_job_from_drive_item(
        token, drive_id, item_id, name, title, meeting_date, source=source,
    )
    state["processed"][item_id] = {
        "name": name,
        "job_id": job_id,
        "source": source,
        "ingested_at": datetime.now().isoformat(timespec="seconds"),
    }
    status["ingested_count"] += 1
    notify("New meeting recording", f"Processing: {title}", job_url(job_id))
    return True


def _poll_onedrive(token, state, settings) -> bool:
    items = msgraph.list_recordings(token, settings["recordings_folder"])
    if not state.get("onedrive_initialized"):
        state["onedrive_initialized"] = True
        for i in items:
            state["processed"].setdefault(i["id"], {"name": i.get("name"), "job_id": None})
        return True

    changed = False
    for item in items:
        name = item.get("name", "")
        if "file" not in item or not _is_media(name):
            continue
        if item["id"] in state["processed"] or not _is_settled(item.get("lastModifiedDateTime")):
            continue
        changed |= _ingest(
            token, state, settings,
            item["parentReference"]["driveId"], item["id"], name, "teams-auto",
        )
    return changed


def _poll_meeting_chats(token, config, state, settings) -> bool:
    chat_token = msgraph.acquire_token(config, msgraph.CHAT_SCOPES)
    status["chat_access"] = chat_token is not None
    if not chat_token:
        raise msgraph.GraphError(
            "No Chat.Read access. Sign in again from Settings (or run: keepmeet teams login)"
        )

    if not state.get("chats_since"):
        state["chats_since"] = _now_iso()
        return True
    since = _parse_ts(state["chats_since"])

    checked = state.setdefault("chat_checked", {})
    changed = False
    for chat in msgraph.list_meeting_chats(chat_token):
        preview = chat.get("lastMessagePreview") or {}
        preview_ts = preview.get("createdDateTime")
        last_activity = _parse_ts(preview_ts)
        if last_activity and since and last_activity < since:
            continue
        if preview_ts and checked.get(chat["id"]) == preview_ts:
            continue
        topic = chat.get("topic") or ""
        pending = False
        for rec in msgraph.list_chat_recordings(chat_token, chat["id"]):
            created = _parse_ts(rec.get("created"))
            if created and since and created < since:
                continue
            url = rec.get("url")
            if not url or rec.get("status") != "success":
                pending = True
                continue
            seen = state["chat_urls"].get(url, {})
            if seen.get("item_id") or seen.get("attempts", 0) >= MAX_RESOLVE_ATTEMPTS:
                continue
            try:
                item = msgraph.resolve_share_link(token, url)
            except msgraph.GraphError as e:
                attempts = seen.get("attempts", 0) + 1
                state["chat_urls"][url] = {"topic": topic, "attempts": attempts, "error": str(e)[:300]}
                pending |= attempts < MAX_RESOLVE_ATTEMPTS
                changed = True
                continue
            if not _is_settled(item.get("lastModifiedDateTime")):
                pending = True
                continue
            state["chat_urls"][url] = {"topic": topic, "item_id": item["id"]}
            changed = True
            name = item.get("name") or rec.get("name") or "recording.mp4"
            _ingest(
                token, state, settings,
                item["parentReference"]["driveId"], item["id"], name, "teams-chat", hint=topic,
            )
        if preview_ts and not pending:
            checked[chat["id"]] = preview_ts
            changed = True
    return changed


def _poll_shared(token, state, settings) -> bool:
    items = [
        i for i in msgraph.list_shared_with_me(token)
        if _is_media(i["name"]) and FILENAME_RE.match(i["name"])
    ]
    if not state.get("shared_initialized"):
        state["shared_initialized"] = True
        for i in items:
            state["processed"].setdefault(i["id"], {"name": i["name"], "job_id": None})
        return True

    changed = False
    for item in items:
        if item["id"] in state["processed"] or not _is_settled(item.get("lastModifiedDateTime")):
            continue
        changed |= _ingest(
            token, state, settings, item["drive_id"], item["id"], item["name"], "teams-shared",
        )
    return changed


def poll_once():
    with _poll_lock:
        config = load_config()
        settings = load_settings(config)
        status["running"] = settings["watcher_enabled"]
        if not settings["watcher_enabled"]:
            return

        token = msgraph.acquire_token(config)
        status["signed_in"] = token is not None
        if not token:
            status["last_error"] = "Not signed in to Microsoft. Sign in from Settings (or run: keepmeet teams login)"
            return

        state = _load_state()
        pollers = {
            "onedrive": lambda: _poll_onedrive(token, state, settings),
            "meeting_chats": lambda: _poll_meeting_chats(token, config, state, settings),
            "shared_with_me": lambda: _poll_shared(token, state, settings),
        }
        errors = []
        for name, poll in pollers.items():
            if not settings["sources"].get(name):
                status["sources"].pop(name, None)
                continue
            source_status = {"last_poll_at": datetime.now().isoformat(timespec="seconds"), "last_error": None}
            try:
                if poll():
                    _save_state(state)
            except Exception as e:
                source_status["last_error"] = str(e)
                errors.append(f"{name}: {e}")
            status["sources"][name] = source_status

        status["last_error"] = "; ".join(errors) or None


def trigger_poll():
    _wake.set()


def _loop():
    while True:
        interval = 300
        try:
            poll_once()
            interval = load_settings(load_config())["poll_interval_seconds"]
        except Exception as e:
            status["last_error"] = str(e)
        status["last_poll_at"] = datetime.now().isoformat(timespec="seconds")
        _wake.wait(timeout=max(interval, 30))
        _wake.clear()


def start_login(config) -> dict:
    flow, complete = msgraph.initiate_device_login(config)
    status["login"] = {
        "state": "pending",
        "user_code": flow["user_code"],
        "verification_uri": flow["verification_uri"],
        "message": flow["message"],
    }

    def _wait():
        try:
            result = complete()
            username = result.get("id_token_claims", {}).get("preferred_username")
            status["login"] = {"state": "success", "account": username}
            trigger_poll()
        except Exception as e:
            status["login"] = {"state": "failed", "error": str(e)}

    threading.Thread(target=_wait, daemon=True, name="graph-login").start()
    return status["login"]


def start_watcher():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="teams-watcher").start()
