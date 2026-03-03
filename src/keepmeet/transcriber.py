import dataclasses
import gc
import os
import shutil

from .config import Config


def _ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        ffmpeg_dir = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        pass


class TranscriptionError(Exception):
    pass


@dataclasses.dataclass
class TranscriptResult:
    segments: list[dict]
    language: str


def transcribe_audio(audio_path: str, config: Config) -> TranscriptResult:
    _ensure_ffmpeg()
    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"

    try:
        audio = whisperx.load_audio(audio_path)
    except Exception as e:
        raise TranscriptionError(f"Failed to load audio: {e}") from e

    try:
        model = whisperx.load_model(
            config.whisper_model,
            device,
            compute_type=config.compute_type,
            language=config.language,
        )
        result = model.transcribe(audio, batch_size=config.batch_size)
    except torch.cuda.OutOfMemoryError:
        _cleanup_cuda()
        try:
            model = whisperx.load_model(
                config.whisper_model,
                device,
                compute_type=config.compute_type,
                language=config.language,
            )
            result = model.transcribe(audio, batch_size=1)
        except torch.cuda.OutOfMemoryError:
            raise TranscriptionError(
                "Out of GPU memory even with batch_size=1. "
                "Try a smaller model (e.g. 'small') or use CPU."
            )
    except Exception as e:
        raise TranscriptionError(f"Transcription failed: {e}") from e

    detected_language = result["language"]
    del model
    _cleanup_cuda()

    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=detected_language, device=device
        )
        result = whisperx.align(
            result["segments"],
            model_a,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        del model_a
        _cleanup_cuda()
    except Exception as e:
        raise TranscriptionError(f"Alignment failed: {e}") from e

    try:
        from whisperx.diarize import DiarizationPipeline
        diarize_model = DiarizationPipeline(
            token=config.hf_token, device=device
        )
        diarize_segments = diarize_model(audio)
        result = whisperx.assign_word_speakers(diarize_segments, result)
        del diarize_model
        _cleanup_cuda()
    except Exception as e:
        raise TranscriptionError(f"Diarization failed: {e}") from e

    return TranscriptResult(
        segments=result["segments"],
        language=detected_language,
    )


def format_raw_transcript(
    result: TranscriptResult, speaker_map: dict[str, str]
) -> str:
    lines: list[str] = []
    for seg in result.segments:
        speaker_id = seg.get("speaker", "UNKNOWN")
        name = speaker_map.get(speaker_id, speaker_id)
        start = _fmt_time(seg.get("start", 0))
        end = _fmt_time(seg.get("end", 0))
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{start} - {end}] {name}:\n{text}\n")
    return "\n".join(lines)


def extract_speakers(result: TranscriptResult) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for seg in result.segments:
        speaker = seg.get("speaker", "UNKNOWN")
        if speaker not in seen:
            seen.add(speaker)
            ordered.append(speaker)
    return ordered


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _cleanup_cuda() -> None:
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
