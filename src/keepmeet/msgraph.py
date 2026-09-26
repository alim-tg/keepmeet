import base64
import threading
import urllib.parse
from pathlib import Path

import msal
import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["Files.Read.All", "User.Read"]
CHAT_SCOPES = ["Chat.Read"]
LOGIN_SCOPES = SCOPES + CHAT_SCOPES
RECORDING_EVENT = "#microsoft.graph.callRecordingEventMessageDetail"
CACHE_PATH = Path("data") / "graph_token_cache.json"


class GraphError(Exception):
    pass


_cache_lock = threading.Lock()


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def _build_app(config, cache: msal.SerializableTokenCache | None = None) -> msal.PublicClientApplication:
    if not config.graph_client_id or not config.graph_tenant_id:
        raise GraphError("GRAPH_CLIENT_ID and GRAPH_TENANT_ID must be set in .env")
    return msal.PublicClientApplication(
        config.graph_client_id,
        authority=f"https://login.microsoftonline.com/{config.graph_tenant_id}",
        token_cache=cache,
    )


def get_account(config) -> dict | None:
    cache = _load_cache()
    app = _build_app(config, cache)
    accounts = app.get_accounts()
    return accounts[0] if accounts else None


def acquire_token(config, scopes: list[str] | None = None) -> str | None:
    with _cache_lock:
        cache = _load_cache()
        app = _build_app(config, cache)
        accounts = app.get_accounts()
        if not accounts:
            return None
        result = app.acquire_token_silent(scopes or SCOPES, account=accounts[0])
        _save_cache(cache)
    if result and "access_token" in result:
        return result["access_token"]
    return None


def initiate_device_login(config):
    cache = _load_cache()
    app = _build_app(config, cache)
    flow = app.initiate_device_flow(scopes=LOGIN_SCOPES)
    if "user_code" not in flow:
        raise GraphError(f"Could not start device login: {flow.get('error_description', flow)}")

    def complete() -> dict:
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise GraphError(result.get("error_description", "Login failed"))
        with _cache_lock:
            _save_cache(cache)
        return result

    return flow, complete


def device_login(config, echo=print) -> dict:
    flow, complete = initiate_device_login(config)
    echo(flow["message"])
    return complete()


def _get(token: str, url: str, params: dict | None = None) -> dict:
    resp = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=60
    )
    if resp.status_code >= 400:
        raise GraphError(f"Graph API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def get_me(token: str) -> dict:
    return _get(token, f"{GRAPH_BASE}/me")


def list_recordings(token: str, folder: str = "Recordings") -> list[dict]:
    folder_enc = urllib.parse.quote(folder)
    url = f"{GRAPH_BASE}/me/drive/root:/{folder_enc}:/children"
    params = {
        "$top": "200",
        "$select": "id,name,size,file,createdDateTime,lastModifiedDateTime,parentReference",
    }
    items: list[dict] = []
    while url:
        resp = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=60
        )
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise GraphError(f"Graph API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        params = None
        items.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return items


def download_item(token: str, drive_id: str, item_id: str, dest: Path):
    url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
    with requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=600
    ) as resp:
        if resp.status_code >= 400:
            raise GraphError(f"Download failed {resp.status_code}: {resp.text[:500]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)


def _extract_file_url(url: str) -> str:
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    if "teams.microsoft.com" in parsed.netloc:
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ("sitePath", "fileUrl"):
            if key in qs and qs[key][0]:
                return qs[key][0]
        raise GraphError("Teams link does not contain a recording file URL")
    return url


def _encode_share_url(url: str) -> str:
    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"u!{encoded}"


def resolve_share_link(token: str, url: str) -> dict:
    file_url = _extract_file_url(url)
    share_id = _encode_share_url(file_url)
    return _get(token, f"{GRAPH_BASE}/shares/{share_id}/driveItem")


def list_meeting_chats(token: str) -> list[dict]:
    url = f"{GRAPH_BASE}/me/chats"
    base = {
        "$expand": "lastMessagePreview",
        "$orderby": "lastMessagePreview/createdDateTime desc",
        "$top": "50",
    }
    try:
        data = _get(token, url, {**base, "$filter": "chatType eq 'meeting'"})
    except GraphError:
        data = _get(token, url, base)
    return [c for c in data.get("value", []) if c.get("chatType") == "meeting"]


def list_chat_recordings(token: str, chat_id: str) -> list[dict]:
    data = _get(
        token,
        f"{GRAPH_BASE}/chats/{chat_id}/messages",
        {"$top": "50", "$orderby": "createdDateTime desc"},
    )
    recordings = []
    for msg in data.get("value", []):
        detail = msg.get("eventDetail") or {}
        if detail.get("@odata.type") != RECORDING_EVENT:
            continue
        recordings.append({
            "message_id": msg.get("id"),
            "created": msg.get("createdDateTime"),
            "url": detail.get("callRecordingUrl"),
            "status": detail.get("callRecordingStatus"),
            "name": detail.get("callRecordingDisplayName"),
        })
    return recordings


def list_shared_with_me(token: str) -> list[dict]:
    data = _get(token, f"{GRAPH_BASE}/me/drive/sharedWithMe", {"$top": "200"})
    items = []
    for entry in data.get("value", []):
        remote = entry.get("remoteItem") or {}
        if "file" not in remote:
            continue
        drive_id = (remote.get("parentReference") or {}).get("driveId")
        if not drive_id:
            continue
        items.append({
            "id": remote["id"],
            "name": remote.get("name") or entry.get("name", ""),
            "drive_id": drive_id,
            "lastModifiedDateTime": remote.get("lastModifiedDateTime"),
        })
    return items
