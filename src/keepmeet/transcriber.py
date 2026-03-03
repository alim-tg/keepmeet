import dataclasses
import gc
import os
import re
import shutil
import threading
from collections import Counter

from .config import Config

SAMPLE_RATE = 16000
CHUNK_DURATION = 30
CHUNK_PAD = 5

ASR_OPTIONS = {
    "repetition_penalty": 1.2,
    "no_repeat_ngram_size": 3,
    "compression_ratio_threshold": 2.0,
    "log_prob_threshold": -0.8,
    "hallucination_silence_threshold": 2.0,
    "condition_on_previous_text": False,
}


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


def transcribe_audio(
    audio_path: str, config: Config, on_stage=None
) -> TranscriptResult:
    _ensure_ffmpeg()
    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"

    if on_stage:
        on_stage("transcribing")

    try:
        audio = whisperx.load_audio(audio_path)
    except Exception as e:
        raise TranscriptionError(f"Failed to load audio: {e}") from e

    try:
        model = whisperx.load_model(
            config.whisper_model,
            device,
            compute_type=config.compute_type,
            asr_options=ASR_OPTIONS,
        )
        if config.language:
            result = model.transcribe(
                audio,
                batch_size=config.batch_size,
                language=config.language,
            )
        else:
            result = _chunked_transcribe(model, audio, config.batch_size)
    except torch.cuda.OutOfMemoryError:
        _cleanup_cuda()
        try:
            model = whisperx.load_model(
                config.whisper_model,
                device,
                compute_type=config.compute_type,
                asr_options=ASR_OPTIONS,
            )
            if config.language:
                result = model.transcribe(
                    audio,
                    batch_size=1,
                    language=config.language,
                )
            else:
                result = _chunked_transcribe(model, audio, 1)
        except torch.cuda.OutOfMemoryError:
            raise TranscriptionError(
                "Out of GPU memory even with batch_size=1. "
                "Try a smaller model (e.g. 'small') or use CPU."
            )
    except Exception as e:
        raise TranscriptionError(f"Transcription failed: {e}") from e

    languages_used = result.get("_languages", [result["language"]])
    result["segments"] = _remove_hallucinations(result["segments"])
    del model
    _cleanup_cuda()

    if on_stage:
        on_stage("aligning")

    try:
        aligned = _align_with_timeout(result, languages_used, audio, device, timeout=120)
        if aligned is not None:
            result = aligned
    except Exception:
        pass

    if on_stage:
        on_stage("diarizing")

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

    primary_lang = Counter(languages_used).most_common(1)[0][0]

    return TranscriptResult(
        segments=result["segments"],
        language=primary_lang,
    )


EXPECTED_LANGUAGES = {"ru", "en"}


def _chunked_transcribe(model, audio, batch_size):
    chunk_samples = CHUNK_DURATION * SAMPLE_RATE
    pad_samples = CHUNK_PAD * SAMPLE_RATE
    total = len(audio)
    all_segments = []
    languages = []
    prev_lang = None

    for logical_start in range(0, total, chunk_samples):
        logical_end = min(logical_start + chunk_samples, total)
        is_last = logical_end >= total

        feed_start = max(0, logical_start - pad_samples)
        feed_end = min(total, logical_end + pad_samples)
        chunk = audio[feed_start:feed_end]
        feed_offset = feed_start / SAMPLE_RATE

        own_start = logical_start / SAMPLE_RATE
        own_end = logical_end / SAMPLE_RATE

        chunk_result = model.transcribe(chunk, batch_size=batch_size)
        detected = chunk_result["language"]

        if detected not in EXPECTED_LANGUAGES and prev_lang:
            lang = prev_lang
            chunk_result = model.transcribe(
                chunk, batch_size=batch_size, language=lang
            )
        else:
            lang = detected

        prev_lang = lang
        languages.append(lang)

        for seg in chunk_result["segments"]:
            seg_start = seg.get("start", 0) + feed_offset
            seg_end = seg.get("end", 0) + feed_offset
            seg_mid = (seg_start + seg_end) / 2
            if seg_mid < own_start or (not is_last and seg_mid >= own_end):
                continue
            seg["start"] = seg_start
            seg["end"] = seg_end
            seg["_lang"] = lang
            if "words" in seg:
                for w in seg["words"]:
                    if "start" in w:
                        w["start"] += feed_offset
                    if "end" in w:
                        w["end"] += feed_offset
            all_segments.append(seg)

    primary_lang = Counter(languages).most_common(1)[0][0]

    return {
        "segments": all_segments,
        "language": primary_lang,
        "_languages": languages,
    }


def _remove_hallucinations(segments: list[dict]) -> list[dict]:
    cleaned = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        if _is_repetitive(text):
            trimmed = _trim_repetition(text)
            if trimmed:
                seg = {**seg, "text": trimmed}
                cleaned.append(seg)
            continue
        cleaned.append(seg)
    return cleaned


def _is_repetitive(text: str) -> bool:
    words = text.split()
    if len(words) < 6:
        return False
    for ngram_size in range(2, 6):
        ngrams = [" ".join(words[i:i + ngram_size]) for i in range(len(words) - ngram_size + 1)]
        if not ngrams:
            continue
        most_common_count = Counter(ngrams).most_common(1)[0][1]
        if most_common_count >= 4 and most_common_count / len(ngrams) > 0.3:
            return True
    return False


def _trim_repetition(text: str) -> str:
    match = re.search(r"(.{4,}?)\1{3,}", text)
    if match:
        return text[:match.start()] + match.group(1)
    words = text.split()
    for ngram_size in range(2, 6):
        ngrams = [" ".join(words[i:i + ngram_size]) for i in range(len(words) - ngram_size + 1)]
        counts = Counter(ngrams)
        repeated, count = counts.most_common(1)[0]
        if count >= 4:
            first_idx = next(i for i in range(len(words) - ngram_size + 1) if " ".join(words[i:i + ngram_size]) == repeated)
            return " ".join(words[:first_idx + ngram_size])
    return text


def _align_with_timeout(result, languages_used, audio, device, timeout=120):
    container = [None]
    error = [None]

    def run():
        try:
            container[0] = _align_multilang(result, languages_used, audio, device)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return None
    if error[0]:
        raise error[0]
    return container[0]


def _align_multilang(result, languages_used, audio, device):
    import whisperx

    unique_langs = list(dict.fromkeys(languages_used))
    segments = result["segments"]

    aligned_segments = []
    for lang in unique_langs:
        lang_segs = [s for s in segments if s.get("_lang", unique_langs[0]) == lang]
        if not lang_segs:
            continue
        try:
            model_a, metadata = whisperx.load_align_model(
                language_code=lang, device=device
            )
            aligned = whisperx.align(
                lang_segs, model_a, metadata, audio, device,
                return_char_alignments=False,
            )
            aligned_segments.extend(aligned["segments"])
            del model_a
            _cleanup_cuda()
        except Exception:
            aligned_segments.extend(lang_segs)

    aligned_segments.sort(key=lambda s: s.get("start", 0))
    return {"segments": aligned_segments}


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
