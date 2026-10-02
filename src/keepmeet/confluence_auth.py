import base64
import ctypes
import json
import os
import re
from ctypes import wintypes
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

AUTH_PATH = Path("data") / "confluence_auth.json"
TARGET_RE = re.compile(r"/wiki/spaces/(?P<space>[^/]+)(?:/(?:folder|pages)/(?P<parent>\d+))?")


class ConfluenceAuthError(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        return data
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise ConfluenceAuthError("Could not decrypt the saved Confluence token")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def parse_target(url: str) -> dict:
    url = (url or "").strip()
    if not url:
        return {}
    parsed = urlparse(url)
    match = TARGET_RE.search(parsed.path)
    if not parsed.scheme or not parsed.netloc or not match:
        raise ConfluenceAuthError(
            "Paste a Confluence folder or page link, e.g. https://site.atlassian.net/wiki/spaces/KEY/folder/123/Name"
        )
    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return {
        "base_url": f"{parsed.scheme}://{parsed.netloc}",
        "space_key": unquote(match.group("space")),
        "parent_id": match.group("parent"),
        "parent_name": unquote(name.replace("+", " ")) if match.group("parent") else None,
    }


def save_credentials(email: str, token: str):
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    secret = base64.b64encode(_dpapi(token.encode("utf-8"), protect=True)).decode("ascii")
    AUTH_PATH.write_text(json.dumps({"email": email.strip(), "token": secret}), encoding="utf-8")


def clear_credentials():
    AUTH_PATH.unlink(missing_ok=True)


def load_credentials(config=None) -> tuple[str, str] | None:
    if AUTH_PATH.exists():
        data = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
        token = _dpapi(base64.b64decode(data["token"]), protect=False).decode("utf-8")
        return data["email"], token
    if config is not None and config.confluence_email and config.confluence_api_token:
        return config.confluence_email, config.confluence_api_token
    return None


def auth_headers(email: str, token: str) -> dict[str, str]:
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def current_user(base_url: str, email: str, token: str) -> dict:
    try:
        resp = requests.get(
            f"{base_url}/wiki/rest/api/user/current",
            headers=auth_headers(email, token),
            timeout=20,
        )
    except requests.RequestException as e:
        raise ConfluenceAuthError(f"Could not reach Confluence: {e}") from e
    if resp.status_code in (401, 403):
        raise ConfluenceAuthError("Confluence rejected the email or API token")
    if resp.status_code >= 400:
        raise ConfluenceAuthError(f"Confluence error {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("type") == "anonymous":
        raise ConfluenceAuthError("Confluence rejected the email or API token")
    return {"name": data.get("displayName"), "email": data.get("email") or email}
