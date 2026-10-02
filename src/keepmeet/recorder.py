import ctypes
import logging
import subprocess
import threading
import time
import wave
from collections import Counter
from ctypes import wintypes
from pathlib import Path

from .transcriber import _get_ffmpeg

logger = logging.getLogger(__name__)

MIC_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
TEAMS_PROCESSES = ("ms-teams.exe", "teams.exe")
TEAMS_NAV = {
    "chat", "activity", "calendar", "teams", "calls", "onedrive", "apps", "files",
    "people", "copilot", "communities", "assignments", "microsoft teams", "new teams",
}
FRAMES_PER_BUFFER = 1024
SOUND_RMS_THRESHOLD = 100


class RecorderError(Exception):
    pass


def _subkeys(key) -> list[str]:
    import winreg

    names = []
    i = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, i))
        except OSError:
            return names
        i += 1


def _key_in_use(key) -> bool:
    import winreg

    try:
        start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
        stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
    except OSError:
        return False
    return start > 0 and stop == 0


def teams_using_mic() -> bool:
    import winreg

    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, MIC_STORE)
    except OSError:
        return False
    with root:
        for name in _subkeys(root):
            if name.startswith("MSTeams_") or name.startswith("MicrosoftTeams_"):
                with winreg.OpenKey(root, name) as key:
                    if _key_in_use(key):
                        return True
        try:
            non_packaged = winreg.OpenKey(root, "NonPackaged")
        except OSError:
            return False
        with non_packaged:
            for name in _subkeys(non_packaged):
                if name.lower().rsplit("#", 1)[-1] in TEAMS_PROCESSES:
                    with winreg.OpenKey(non_packaged, name) as key:
                        if _key_in_use(key):
                            return True
    return False


def _process_name(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def teams_window_titles() -> list[str]:
    user32 = ctypes.windll.user32
    titles: list[str] = []
    names: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in names:
            names[pid.value] = _process_name(pid.value)
        if names[pid.value] in TEAMS_PROCESSES:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            titles.append(buf.value)
        return True

    user32.EnumWindows(_callback, 0)
    return titles


def meeting_name_from_title(title: str) -> str | None:
    parts = [p.strip() for p in title.split("|") if p.strip()]
    if parts and parts[-1].lower().startswith("microsoft teams"):
        parts = parts[:-1]
    if not parts or parts[0].lower() in TEAMS_NAV:
        return None
    for part in parts:
        low = part.lower()
        if "compact view" in low or low.startswith("meeting in"):
            continue
        return part
    return None


def pick_meeting_name(seen: Counter) -> str | None:
    return seen.most_common(1)[0][0] if seen else None


class AudioRecorder:
    def __init__(self, out_dir: Path, include_mic: bool = True):
        self.out_dir = out_dir
        self.include_mic = include_mic
        self._pa = None
        self._streams = []
        self._waves = []
        self._tracks: list[Path] = []
        self._lock = threading.Lock()
        self.mic_error: str | None = None
        self.last_sound = time.monotonic()

    def start(self):
        import pyaudiowpatch as pa

        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._pa = pa.PyAudio()
        try:
            wasapi = self._pa.get_host_api_info_by_type(pa.paWASAPI)
            loopback = self._pa.get_default_wasapi_loopback()
            output = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
            self._open_silence(output)
            self._open_capture(loopback, self.out_dir / "system.wav", track_sound=True)
            if self.include_mic:
                try:
                    mic = self._pa.get_device_info_by_index(wasapi["defaultInputDevice"])
                    self._open_capture(mic, self.out_dir / "mic.wav")
                except Exception as e:
                    self.mic_error = str(e)
                    logger.warning(f"Microphone capture unavailable: {e}")
        except Exception as e:
            self.close()
            raise RecorderError(f"Could not start audio capture: {e}") from e

    def _open_capture(self, device: dict, path: Path, track_sound: bool = False):
        import numpy as np
        import pyaudiowpatch as pa

        channels = max(1, min(2, int(device["maxInputChannels"])))
        rate = int(device["defaultSampleRate"])
        wf = wave.open(str(path), "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)

        def _callback(in_data, _frames, _time, _status):
            with self._lock:
                if in_data:
                    wf.writeframes(in_data)
            if track_sound and in_data:
                samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
                if samples.size and np.sqrt(np.mean(samples ** 2)) > SOUND_RMS_THRESHOLD:
                    self.last_sound = time.monotonic()
            return (None, pa.paContinue)

        stream = self._pa.open(
            format=pa.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=FRAMES_PER_BUFFER,
            stream_callback=_callback,
        )
        self._waves.append(wf)
        self._streams.append(stream)
        self._tracks.append(path)

    def _open_silence(self, device: dict):
        import pyaudiowpatch as pa

        channels = max(1, min(2, int(device["maxOutputChannels"])))
        rate = int(device["defaultSampleRate"])
        frame_bytes = channels * 2

        def _callback(_in, frames, _time, _status):
            return (bytes(frames * frame_bytes), pa.paContinue)

        stream = self._pa.open(
            format=pa.paInt16,
            channels=channels,
            rate=rate,
            output=True,
            output_device_index=device["index"],
            frames_per_buffer=FRAMES_PER_BUFFER,
            stream_callback=_callback,
        )
        self._streams.append(stream)

    def close(self):
        for stream in self._streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        with self._lock:
            for wf in self._waves:
                try:
                    wf.close()
                except Exception:
                    pass
        if self._pa is not None:
            self._pa.terminate()
        self._streams, self._waves, self._pa = [], [], None

    def stop(self, dest: Path) -> Path:
        self.close()
        return mix_tracks(self._tracks, dest)["mix"]


def track_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except Exception:
        return 0.0


def mix_tracks(paths: list[Path], dest: Path) -> dict[str, Path]:
    tracks = [t for t in paths if t.exists() and t.stat().st_size > 44]
    if not tracks:
        raise RecorderError("No audio was captured")

    ffmpeg = _get_ffmpeg()
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for t in tracks:
        cmd += ["-i", str(t)]
    if len(tracks) > 1:
        cmd += [
            "-filter_complex",
            f"amix=inputs={len(tracks)}:duration=longest:normalize=0",
        ]
    cmd += ["-ac", "1", "-ar", "48000", "-c:a", "aac", "-b:a", "96k", str(dest)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RecorderError(f"Mixing failed: {proc.stderr[-500:]}")

    outputs = {"mix": dest}
    if len(tracks) > 1:
        for t in tracks:
            flac = dest.parent / f"{t.stem}.flac"
            proc = subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(t),
                 "-ac", "1", "-ar", "16000", "-c:a", "flac", str(flac)],
                capture_output=True, text=True, timeout=600,
            )
            if proc.returncode == 0:
                outputs[t.stem] = flac
    for t in tracks:
        t.unlink(missing_ok=True)
    return outputs
