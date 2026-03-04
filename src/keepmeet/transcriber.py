import dataclasses
import gc
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter

import requests

from .config import Config

CHUNK_DURATION = 60
CHUNK_PAD_LEAD = 5
CHUNK_PAD_TRAIL = 30


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


def _attach_words_to_segments(segments: list[dict], words: list[dict]):
    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        seg["words"] = [
            w for w in words
            if w.get("start", 0) >= seg_start - 0.01
            and w.get("end", 0) <= seg_end + 0.01
        ]


def _get_audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        ["ffmpeg", "-i", audio_path, "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    import re as _re
    match = _re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if not match:
        raise TranscriptionError("Could not determine audio duration")
    h, m, s, cs = int(match[1]), int(match[2]), int(match[3]), int(match[4])
    return h * 3600 + m * 60 + s + cs / 100


def _extract_chunk(audio_path: str, start: float, duration: float, out_path: str):
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ss", str(start), "-t", str(duration),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", out_path],
        capture_output=True, timeout=60,
    )


def _transcribe_deepinfra_chunk(chunk_path: str, config: Config, language: str | None = None) -> dict:
    data = {"chunk_level": "word"}
    if language:
        data["language"] = language
    with open(chunk_path, "rb") as f:
        resp = requests.post(
            "https://api.deepinfra.com/v1/inference/openai/whisper-large-v3-turbo",
            headers={"Authorization": f"bearer {config.deepinfra_api_key}"},
            files={"audio": f},
            data=data,
            timeout=600,
        )
    resp.raise_for_status()
    return resp.json()


def _flip_language(lang: str) -> str:
    if lang in ("ru", "uk", "be"):
        return "en"
    return "ru"


def _chunk_looks_hallucinated(data: dict) -> bool:
    text = " ".join(s.get("text", "") for s in data.get("segments", []))
    if _is_repetitive(text):
        return True
    words = text.split()
    if len(words) < 5:
        return False
    latin = sum(1 for c in text if c.isalpha() and ord(c) < 0x0250)
    cyrillic = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    total = latin + cyrillic
    if total < 20:
        return False
    lang = data.get("language", "en")
    if lang in ("ru", "uk", "be") and latin / total > 0.5:
        return True
    if lang == "en" and cyrillic / total > 0.3:
        return True
    return False


def _transcribe_chunk_with_retry(chunk_path: str, config: Config) -> dict:
    data = _transcribe_deepinfra_chunk(chunk_path, config)
    if _chunk_looks_hallucinated(data):
        forced_lang = _flip_language(data.get("language", "en"))
        retry = _transcribe_deepinfra_chunk(chunk_path, config, language=forced_lang)
        if not _chunk_looks_hallucinated(retry):
            return retry
    return data


def _transcribe_deepinfra(audio_path: str, config: Config):
    _ensure_ffmpeg()
    total_duration = _get_audio_duration(audio_path)

    if total_duration <= CHUNK_DURATION + CHUNK_PAD_TRAIL:
        data = _transcribe_chunk_with_retry(audio_path, config)
        segments = data.get("segments", [])
        words = data.get("words", [])
        _attach_words_to_segments(segments, words)
        return segments, data.get("language", "en")

    all_segments = []
    languages = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        logical_start = 0.0
        while logical_start < total_duration:
            logical_end = min(logical_start + CHUNK_DURATION, total_duration)

            feed_start = max(0.0, logical_start - CHUNK_PAD_LEAD)
            feed_end = min(total_duration, logical_end + CHUNK_PAD_TRAIL)
            feed_duration = feed_end - feed_start

            own_start = logical_start
            own_end = logical_end
            is_last = logical_end >= total_duration

            chunk_path = os.path.join(tmp_dir, f"chunk_{int(logical_start)}.wav")
            _extract_chunk(audio_path, feed_start, feed_duration, chunk_path)

            data = _transcribe_chunk_with_retry(chunk_path, config)
            languages.append(data.get("language", "en"))

            new_seg_idx = len(all_segments)

            for seg in data.get("segments", []):
                seg_start = seg.get("start", 0) + feed_start
                seg_end = seg.get("end", 0) + feed_start
                seg_mid = (seg_start + seg_end) / 2
                if seg_mid < own_start or (not is_last and seg_mid >= own_end):
                    continue
                seg["start"] = seg_start
                seg["end"] = seg_end
                all_segments.append(seg)

            for w in data.get("words", []):
                if "start" in w:
                    w["start"] += feed_start
                if "end" in w:
                    w["end"] += feed_start

            chunk_words = data.get("words", [])
            _attach_words_to_segments(all_segments[new_seg_idx:], chunk_words)

            logical_start = logical_end

    primary_lang = Counter(languages).most_common(1)[0][0]
    return all_segments, primary_lang


def transcribe_audio(
    audio_path: str, config: Config, on_stage=None
) -> TranscriptResult:
    _ensure_ffmpeg()
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"

    if on_stage:
        on_stage("transcribing")

    try:
        segments, language = _transcribe_deepinfra(audio_path, config)
    except requests.HTTPError as e:
        raise TranscriptionError(f"DeepInfra API error: {e}") from e
    except Exception as e:
        raise TranscriptionError(f"Transcription failed: {e}") from e

    segments = _remove_hallucinations(segments)

    if on_stage:
        on_stage("diarizing")

    try:
        import whisperx
        from whisperx.diarize import DiarizationPipeline

        audio = whisperx.load_audio(audio_path)
        diarize_model = DiarizationPipeline(token=config.hf_token, device=device)
        diarize_df = diarize_model(audio)

        transcript_dict = {"segments": segments}
        result = whisperx.assign_word_speakers(diarize_df, transcript_dict)
        segments = _regroup_by_speaker(result["segments"])

        del diarize_model
        _cleanup_cuda()
    except Exception as e:
        raise TranscriptionError(f"Diarization failed: {e}") from e

    segments = _clean_script_tails(segments)

    return TranscriptResult(
        segments=segments,
        language=language,
    )


def _regroup_by_speaker(segments: list[dict]) -> list[dict]:
    all_words = []
    for seg in segments:
        seg_speaker = seg.get("speaker")
        for w in seg.get("words", []):
            if "start" not in w:
                continue
            if not w.get("speaker") and seg_speaker:
                w["speaker"] = seg_speaker
            if w.get("speaker"):
                all_words.append(w)
    if not all_words:
        return segments

    all_words.sort(key=lambda w: w["start"])

    deduped = [all_words[0]]
    for w in all_words[1:]:
        if w["start"] - deduped[-1]["start"] < 0.1:
            continue
        deduped.append(w)
    all_words = deduped

    result = []
    cur_spk = all_words[0]["speaker"]
    cur_words = [all_words[0]]

    for w in all_words[1:]:
        if w.get("speaker") == cur_spk:
            cur_words.append(w)
        else:
            text = " ".join(
                (x.get("word") or x.get("text", "")).strip() for x in cur_words
            ).strip()
            if text:
                result.append({
                    "speaker": cur_spk,
                    "start": cur_words[0]["start"],
                    "end": cur_words[-1].get("end", cur_words[-1]["start"]),
                    "text": text,
                })
            cur_spk = w["speaker"]
            cur_words = [w]

    text = " ".join(
        (x.get("word") or x.get("text", "")).strip() for x in cur_words
    ).strip()
    if text:
        result.append({
            "speaker": cur_spk,
            "start": cur_words[0]["start"],
            "end": cur_words[-1].get("end", cur_words[-1]["start"]),
            "text": text,
        })

    return _merge_short_fragments(result)


def _merge_short_fragments(segments: list[dict], min_duration: float = 0.8) -> list[dict]:
    if len(segments) < 3:
        return segments
    merged = [segments[0]]
    for i in range(1, len(segments)):
        cur = segments[i]
        prev = merged[-1]
        cur_dur = cur.get("end", 0) - cur.get("start", 0)
        if (
            cur_dur < min_duration
            and cur.get("speaker") != prev.get("speaker")
            and i + 1 < len(segments)
            and segments[i + 1].get("speaker") == prev.get("speaker")
        ):
            merged[-1] = {
                **prev,
                "end": cur["end"],
                "text": (prev.get("text", "") + " " + cur.get("text", "")).strip(),
            }
            continue
        if cur.get("speaker") == prev.get("speaker"):
            merged[-1] = {
                **prev,
                "end": cur["end"],
                "text": (prev.get("text", "") + " " + cur.get("text", "")).strip(),
            }
            continue
        merged.append(cur)
    return merged


def _clean_script_tails(segments: list[dict]) -> list[dict]:
    cleaned = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        trimmed = _trim_script_tail(text)
        if trimmed != text:
            seg = {**seg, "text": trimmed}
            if trimmed:
                cleaned.append(seg)
        else:
            cleaned.append(seg)
    return cleaned


def _trim_script_tail(text: str) -> str:
    words = text.split()
    if len(words) < 3:
        return text

    def _dominant_script(word: str):
        latin = sum(1 for c in word if c.isalpha() and ord(c) < 0x0250)
        cyrillic = sum(1 for c in word if '\u0400' <= c <= '\u04FF')
        if latin > cyrillic:
            return "latin"
        if cyrillic > latin:
            return "cyrillic"
        return None

    first_scripts = [_dominant_script(w) for w in words[:10] if _dominant_script(w)]
    if not first_scripts:
        return text
    main_script = Counter(first_scripts).most_common(1)[0][0]

    cut = len(words)
    foreign_run = 0
    for i in range(len(words) - 1, -1, -1):
        s = _dominant_script(words[i])
        if s and s != main_script:
            foreign_run += 1
        elif s == main_script:
            break
    if foreign_run >= 2:
        cut = len(words) - foreign_run
        return " ".join(words[:cut]).rstrip(" ,.:;-–—")
    return text


def _remove_hallucinations(segments: list[dict]) -> list[dict]:
    cleaned = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        if _is_repetitive(text):
            trimmed = _trim_repetition(text)
            if trimmed:
                trimmed = _trim_script_tail(trimmed)
            if trimmed:
                trimmed_word_count = len(trimmed.split())
                words = seg.get("words", [])
                kept_words = words[:trimmed_word_count]
                new_end = kept_words[-1].get("end", seg.get("end", 0)) if kept_words else seg.get("end", 0)
                seg = {**seg, "text": trimmed, "words": kept_words, "end": new_end}
                cleaned.append(seg)
            continue

        trimmed = _trim_script_tail(text)
        if trimmed != text:
            trimmed_word_count = len(trimmed.split())
            words = seg.get("words", [])
            kept_words = words[:trimmed_word_count]
            new_end = kept_words[-1].get("end", seg.get("end", 0)) if kept_words else seg.get("end", 0)
            seg = {**seg, "text": trimmed, "words": kept_words, "end": new_end}
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
        if most_common_count >= 4 and (most_common_count / len(ngrams) > 0.3 or most_common_count >= 8):
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
