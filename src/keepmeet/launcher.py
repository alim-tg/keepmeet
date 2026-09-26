import ctypes
import os
import signal
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DIST_INDEX = FRONTEND_DIR / "dist" / "index.html"
ICON_PATH = PROJECT_ROOT / "data" / "keepmeet.ico"
HOST = "127.0.0.1"
PORT = 6070
APP_URL = f"http://localhost:{PORT}"


def _port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def _newest_source_mtime() -> float:
    newest = 0.0
    for folder in (FRONTEND_DIR / "src", FRONTEND_DIR / "public"):
        if folder.exists():
            for f in folder.rglob("*"):
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
    for name in ("index.html", "package.json", "vite.config.ts"):
        f = FRONTEND_DIR / name
        if f.exists():
            newest = max(newest, f.stat().st_mtime)
    return newest


def _ensure_frontend_built(echo):
    if DIST_INDEX.exists() and DIST_INDEX.stat().st_mtime >= _newest_source_mtime():
        return
    echo("Building the web UI (first run or after changes)...")
    try:
        subprocess.run("npm run build", cwd=FRONTEND_DIR, shell=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        if not DIST_INDEX.exists():
            raise RuntimeError(f"Could not build the web UI: {e}") from e
        echo(f"Warning: UI rebuild failed ({e}), using the previous build")


def _open_when_ready(server):
    for _ in range(120):
        if server.started:
            webbrowser.open(APP_URL)
            return
        time.sleep(0.5)


def run_app(echo=print, open_browser: bool = True):
    os.chdir(PROJECT_ROOT)
    if os.name == "nt":
        ctypes.windll.kernel32.SetConsoleTitleW("keepmeet")

    if _port_in_use():
        echo(f"keepmeet is already running, opening {APP_URL}")
        if open_browser:
            webbrowser.open(APP_URL)
        return

    _ensure_frontend_built(echo)

    import uvicorn

    from .server.app import app

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))

    def _request_exit(*_):
        server.should_exit = True

    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _request_exit)

    if open_browser:
        threading.Thread(target=_open_when_ready, args=(server,), daemon=True).start()

    echo(f"keepmeet is running at {APP_URL}")
    echo("Keep this window open. Close it (or press Ctrl+C) to stop keepmeet.")
    server.run()


def _make_icon() -> str | None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=(99, 102, 241, 255))
    draw.rounded_rectangle((98, 48, 158, 150), radius=30, fill=(255, 255, 255, 255))
    draw.arc((72, 92, 184, 178), start=0, end=180, fill=(255, 255, 255, 255), width=14)
    draw.line((128, 178, 128, 208), fill=(255, 255, 255, 255), width=14)
    draw.line((96, 208, 160, 208), fill=(255, 255, 255, 255), width=14)
    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(ICON_PATH, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    return str(ICON_PATH)


SHORTCUT_SCRIPT = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $link = $shell.CreateShortcut((Join-Path $folder 'keepmeet.lnk'))
    $link.TargetPath = $env:KM_TARGET
    $link.Arguments = '-m keepmeet app'
    $link.WorkingDirectory = $env:KM_ROOT
    $link.WindowStyle = 7
    $link.Description = 'Start keepmeet: records Teams calls and turns them into notes'
    if ($env:KM_ICON) { $link.IconLocation = $env:KM_ICON }
    $link.Save()
    Write-Output (Join-Path $folder 'keepmeet.lnk')
}
"""


def install_shortcuts() -> list[str]:
    if os.name != "nt":
        raise RuntimeError("Shortcuts are only supported on Windows")
    python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise RuntimeError(f"Virtual environment not found at {python}")
    env = os.environ.copy()
    env["KM_TARGET"] = str(python)
    env["KM_ROOT"] = str(PROJECT_ROOT)
    env["KM_ICON"] = _make_icon() or ""
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SHORTCUT_SCRIPT],
        env=env, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Could not create shortcuts")
    return [line for line in proc.stdout.splitlines() if line.strip().endswith(".lnk")]
