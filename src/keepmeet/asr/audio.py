import io
import shutil
import subprocess
import wave

import numpy as np

SAMPLE_RATE = 16000

_ffmpeg_path: str | None = None


class AudioError(Exception):
    pass


def ffmpeg_path() -> str:
    global _ffmpeg_path
    if _ffmpeg_path:
        return _ffmpeg_path
    if shutil.which("ffmpeg"):
        _ffmpeg_path = "ffmpeg"
        return _ffmpeg_path
    try:
        import imageio_ffmpeg

        _ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        return _ffmpeg_path
    except ImportError as e:
        raise AudioError("ffmpeg not found") from e


def load_samples(audio_path: str) -> np.ndarray:
    proc = subprocess.run(
        [ffmpeg_path(), "-i", audio_path, "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, timeout=600,
    )
    if proc.returncode != 0:
        raise AudioError(f"Could not decode {audio_path}: {proc.stderr.decode(errors='ignore')[-300:]}")
    return np.frombuffer(proc.stdout, np.int16).astype(np.float32) / 32768.0


def load_waveform(audio_path: str) -> dict:
    return as_waveform(load_samples(audio_path))


def as_waveform(samples: np.ndarray) -> dict:
    import torch

    return {"waveform": torch.from_numpy(samples.copy()).unsqueeze(0), "sample_rate": SAMPLE_RATE}


def to_wav_bytes(samples: np.ndarray) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def duration(samples: np.ndarray) -> float:
    return len(samples) / SAMPLE_RATE


def free_gpu_memory():
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
