import base64
import logging
import os
import subprocess
import threading
from pathlib import Path
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

SCRIPT = """
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:KEEPMEET_TOAST_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:KEEPMEET_TOAST_APP).Show($toast)
"""

_ATTR_ENTITIES = {'"': "&quot;"}


def app_url() -> str:
    if Path("frontend/dist").exists():
        return "http://localhost:6070"
    return "http://localhost:5670"


def job_url(job_id: str) -> str:
    return f"{app_url()}/jobs/{job_id}"


def _build_xml(title: str, body: str, url: str | None) -> str:
    launch = f' activationType="protocol" launch="{escape(url, _ATTR_ENTITIES)}"' if url else ""
    return (
        f"<toast{launch}><visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(title)}</text><text>{escape(body)}</text>"
        f"</binding></visual></toast>"
    )


def _show(title: str, body: str, url: str | None):
    env = os.environ.copy()
    env["KEEPMEET_TOAST_XML"] = _build_xml(title, body, url)
    env["KEEPMEET_TOAST_APP"] = APP_ID
    encoded = base64.b64encode(SCRIPT.encode("utf-16-le")).decode("ascii")
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            env=env,
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


def notify(title: str, body: str, url: str | None = None):
    if os.name != "nt":
        logger.info(f"{title}: {body}")
        return
    from .settings import load_settings

    try:
        if not load_settings().get("notifications", True):
            return
    except Exception:
        pass
    threading.Thread(target=_show, args=(title, body, url), daemon=True).start()
