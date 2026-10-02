import dataclasses
import gc
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter

logger = logging.getLogger(__name__)

import requests

from .config import Config
from .self_voice import SELF_SPEAKER

CHUNK_DURATION = 60
CHUNK_PAD_LEAD = 5
CHUNK_PAD_TRAIL = 30


_ffmpeg_path: str | None = None


def _get_ffmpeg() -> str:
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
    except ImportError:
        pass
    raise TranscriptionError("ffmpeg not found")


def _ensure_ffmpeg():
    _get_ffmpeg()


def load_samples(audio_path: str):
    import numpy as np

    raw = subprocess.run(
        [_get_ffmpeg(), "-i", audio_path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True, timeout=300,
    ).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def load_waveform(audio_path: str) -> dict:
    import torch

    samples = load_samples(audio_path)
    return {"waveform": torch.from_numpy(samples.copy()).unsqueeze(0), "sample_rate": 16000}


def load_embedding_inference(window: str = "sliding"):
    import torch
    from pyannote.audio import Inference, Model

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM")
    return Inference(model, window=window, device=device)


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
        [_get_ffmpeg(), "-i", audio_path, "-f", "null", "-"],
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
        [_get_ffmpeg(), "-y", "-i", audio_path, "-ss", str(start), "-t", str(duration),
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
    return _normalize_response(resp.json())


def _normalize_response(data: dict | None) -> dict:
    data = dict(data or {})
    data["segments"] = [dict(seg) for seg in (data.get("segments") or [])]
    for seg in data["segments"]:
        seg["words"] = seg.get("words") or []
        seg["text"] = seg.get("text") or ""
    data["words"] = data.get("words") or []
    data["language"] = data.get("language") or "en"
    return data


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

            chunk_size_mb = os.path.getsize(chunk_path) / (1024 * 1024)
            logger.info(f"Chunk {int(logical_start)}s: {feed_duration:.0f}s audio, {chunk_size_mb:.1f}MB, uploading...")
            t0 = time.time()
            data = _transcribe_chunk_with_retry(chunk_path, config)
            logger.info(f"Chunk {int(logical_start)}s: API took {time.time() - t0:.1f}s")
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

        all_segments.sort(key=lambda s: s.get("start", 0))

        gaps = []
        for i in range(len(all_segments) - 1):
            gap_start = all_segments[i].get("end", 0)
            gap_end = all_segments[i + 1].get("start", 0)
            if gap_end - gap_start > 5.0:
                gaps.append((gap_end - gap_start, gap_start, gap_end))
        gaps.sort(reverse=True)
        gaps = [(s, e) for _, s, e in gaps[:5]]

        for gap_start, gap_end in gaps:
            pad = 2.0
            chunk_path = os.path.join(tmp_dir, f"gap_{int(gap_start)}.wav")
            extract_start = max(0.0, gap_start - pad)
            extract_dur = (gap_end - gap_start) + 2 * pad
            _extract_chunk(audio_path, extract_start, extract_dur, chunk_path)
            try:
                data = _transcribe_deepinfra_chunk(chunk_path, config)
            except Exception:
                continue
            for seg in data.get("segments", []):
                seg_start = seg.get("start", 0) + extract_start
                seg_end = seg.get("end", 0) + extract_start
                if seg_start < gap_start - 0.5 or seg_end > gap_end + 0.5:
                    continue
                seg["start"] = seg_start
                seg["end"] = seg_end
                for w in seg.get("words", []):
                    if "start" in w:
                        w["start"] += extract_start
                    if "end" in w:
                        w["end"] += extract_start
                all_segments.append(seg)
            gap_words = data.get("words", [])
            for w in gap_words:
                if "start" in w:
                    w["start"] += extract_start
                if "end" in w:
                    w["end"] += extract_start
            new_segs = [s for s in all_segments if s.get("start", 0) >= gap_start - 0.5 and s.get("end", 0) <= gap_end + 0.5]
            for seg in new_segs:
                if not seg.get("words"):
                    _attach_words_to_segments([seg], gap_words)

        all_segments.sort(key=lambda s: s.get("start", 0))

    primary_lang = Counter(languages).most_common(1)[0][0]
    return all_segments, primary_lang


def transcribe_audio(
    audio_path: str, config: Config, on_stage=None,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    system_track: str | None = None,
    mic_track: str | None = None,
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
        import pandas as pd
        from pyannote.audio import Pipeline as DiarizePipeline

        pipeline = DiarizePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=config.hf_token,
        )
        pipeline.to(torch.device(device))

        try:
            params = pipeline.parameters(instantiated=True)
            params["segmentation"]["min_duration_off"] = 0.2
            pipeline.instantiate(params)
        except Exception:
            logger.warning("Could not tune pipeline parameters, using defaults")

        from .self_voice import detect_self_regions, overlay_self

        diarize_path = system_track or audio_path
        audio_input = load_waveform(diarize_path)

        self_regions = []
        if system_track and mic_track:
            try:
                self_regions = detect_self_regions(
                    load_samples(mic_track), audio_input["waveform"][0].numpy()
                )
                logger.info(f"Detected {len(self_regions)} regions of the local speaker")
            except Exception:
                logger.exception("Local speaker detection failed")

        diar_kwargs = {}
        if num_speakers is not None:
            diar_kwargs["num_speakers"] = num_speakers
        if min_speakers is not None:
            diar_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            diar_kwargs["max_speakers"] = max_speakers

        diarization = pipeline(audio_input, **diar_kwargs)
        annotation = getattr(diarization, "speaker_diarization", diarization)

        rows = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            rows.append({"start": turn.start, "end": turn.end, "speaker": speaker})
        diarize_df = pd.DataFrame(rows)

        del pipeline
        _cleanup_cuda()

        raw_turns = [
            (row["start"], row["end"], row["speaker"])
            for _, row in diarize_df.iterrows()
        ]
        raw_turns.sort(key=lambda x: x[0])

        inference = load_embedding_inference()
        try:
            raw_turns = _merge_similar_speakers(raw_turns, audio_input, inference)
            raw_turns = _refine_diarization(raw_turns, audio_input, inference)
        except Exception:
            logger.exception("Diarization refinement failed, using raw turns")
        finally:
            del inference

        raw_turns = overlay_self(raw_turns, self_regions)
        diarize_df = pd.DataFrame(raw_turns, columns=["start", "end", "speaker"])

        _cleanup_cuda()
        segments = _assign_speakers_and_regroup(diarize_df, segments)
    except Exception as e:
        raise TranscriptionError(f"Diarization failed: {e}") from e

    segments = _clean_script_tails(segments)

    return TranscriptResult(
        segments=segments,
        language=language,
    )


def _refine_diarization(diar_segs: list[tuple], audio, inference) -> list[tuple]:
    import numpy as np
    from pyannote.core import Segment

    if len(diar_segs) < 3:
        return diar_segs

    speaker_embs: dict[str, list] = {}
    for start, end, speaker in diar_segs:
        dur = end - start
        if dur < 4.0:
            continue
        margin = dur * 0.2
        try:
            emb = inference.crop(audio, Segment(start + margin, end - margin))
            if emb.ndim == 2:
                emb = emb.mean(axis=0)
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            speaker_embs.setdefault(speaker, []).append(emb)
        except Exception:
            continue

    centroids = {}
    for speaker, embs in speaker_embs.items():
        c = np.mean(embs, axis=0)
        norm = np.linalg.norm(c)
        if norm > 0:
            c = c / norm
        centroids[speaker] = c

    if len(centroids) < 2:
        return diar_segs

    CHECK_DUR = 2.5
    MIN_TURN_DUR = 5.0
    SHORT_MIN = 1.0
    MARGIN = 0.08

    result = []
    for i, (start, end, speaker) in enumerate(diar_segs):
        dur = end - start

        if dur < SHORT_MIN or speaker not in centroids:
            result.append((start, end, speaker))
            continue

        if dur < MIN_TURN_DUR:
            try:
                margin = dur * 0.1
                emb = inference.crop(audio, Segment(start + margin, end - margin))
                if emb.ndim == 2:
                    emb = emb.mean(axis=0)
                norm = np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm
                best_speaker = speaker
                best_sim = float(np.dot(emb, centroids[speaker]))
                for other, centroid in centroids.items():
                    if other == speaker:
                        continue
                    sim = float(np.dot(emb, centroid))
                    if sim > best_sim + MARGIN:
                        best_sim = sim
                        best_speaker = other
                result.append((start, end, best_speaker))
            except Exception:
                result.append((start, end, speaker))
            continue

        check_dur = min(CHECK_DUR, dur * 0.3)
        new_start = start
        new_end = end

        prev_speaker = diar_segs[i - 1][2] if i > 0 else None
        if (
            prev_speaker
            and prev_speaker != speaker
            and prev_speaker in centroids
        ):
            try:
                start_emb = inference.crop(audio, Segment(start, start + check_dur))
                if start_emb.ndim == 2:
                    start_emb = start_emb.mean(axis=0)
                norm = np.linalg.norm(start_emb)
                if norm > 0:
                    start_emb = start_emb / norm
                sim_cur = float(np.dot(start_emb, centroids[speaker]))
                sim_prev = float(np.dot(start_emb, centroids[prev_speaker]))
                if sim_prev > sim_cur + MARGIN:
                    result.append((start, start + check_dur, prev_speaker))
                    new_start = start + check_dur
            except Exception:
                pass

        next_speaker = diar_segs[i + 1][2] if i < len(diar_segs) - 1 else None
        remaining = new_end - new_start
        if (
            next_speaker
            and next_speaker != speaker
            and next_speaker in centroids
            and remaining > MIN_TURN_DUR
        ):
            try:
                end_emb = inference.crop(audio, Segment(end - check_dur, end))
                if end_emb.ndim == 2:
                    end_emb = end_emb.mean(axis=0)
                norm = np.linalg.norm(end_emb)
                if norm > 0:
                    end_emb = end_emb / norm
                sim_cur = float(np.dot(end_emb, centroids[speaker]))
                sim_next = float(np.dot(end_emb, centroids[next_speaker]))
                if sim_next > sim_cur + MARGIN:
                    new_end = end - check_dur
                    result.append((new_start, new_end, speaker))
                    result.append((end - check_dur, end, next_speaker))
                    continue
            except Exception:
                pass

        result.append((new_start, new_end, speaker))

    result.sort(key=lambda x: x[0])
    return result


def _merge_similar_speakers(diar_segs: list[tuple], audio, inference, min_seg_dur: float = 4.0, threshold: float = 0.80) -> list[tuple]:
    import numpy as np
    from pyannote.core import Segment

    speaker_embs: dict[str, list] = {}
    for start, end, speaker in diar_segs:
        dur = end - start
        if dur < min_seg_dur:
            continue
        margin = dur * 0.2
        try:
            emb = inference.crop(audio, Segment(start + margin, end - margin))
            if emb.ndim == 2:
                emb = emb.mean(axis=0)
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            speaker_embs.setdefault(speaker, []).append(emb)
        except Exception:
            continue

    if len(speaker_embs) < 2:
        return diar_segs

    speaking_time: dict[str, float] = {}
    for start, end, speaker in diar_segs:
        speaking_time[speaker] = speaking_time.get(speaker, 0) + (end - start)

    centroids = {}
    for speaker, embs in speaker_embs.items():
        c = np.mean(embs, axis=0)
        norm = np.linalg.norm(c)
        if norm > 0:
            c = c / norm
        centroids[speaker] = c

    merged = True
    rename_map: dict[str, str] = {}
    while merged:
        merged = False
        speakers = list(centroids.keys())
        best_sim = -1.0
        best_pair = None
        for i in range(len(speakers)):
            for j in range(i + 1, len(speakers)):
                sim = float(np.dot(centroids[speakers[i]], centroids[speakers[j]]))
                if sim > best_sim:
                    best_sim = sim
                    best_pair = (speakers[i], speakers[j])
        if best_pair and best_sim > threshold:
            a, b = best_pair
            dominant = a if speaking_time.get(a, 0) >= speaking_time.get(b, 0) else b
            lesser = b if dominant == a else a
            logger.info(f"Merging speakers {lesser} -> {dominant} (similarity={best_sim:.3f})")
            rename_map[lesser] = dominant
            for k, v in rename_map.items():
                if v == lesser:
                    rename_map[k] = dominant
            speaking_time[dominant] = speaking_time.get(dominant, 0) + speaking_time.get(lesser, 0)
            all_embs = speaker_embs.get(dominant, []) + speaker_embs.get(lesser, [])
            c = np.mean(all_embs, axis=0)
            norm = np.linalg.norm(c)
            if norm > 0:
                c = c / norm
            centroids[dominant] = c
            del centroids[lesser]
            speaker_embs[dominant] = all_embs
            if lesser in speaker_embs:
                del speaker_embs[lesser]
            merged = True

    if not rename_map:
        return diar_segs

    return [(start, end, rename_map.get(speaker, speaker)) for start, end, speaker in diar_segs]


def _filter_diarization_noise(segs: list[tuple], min_dur: float = 0.25) -> list[tuple]:
    kept = []
    for start, end, speaker in segs:
        dur = end - start
        if dur >= min_dur:
            kept.append((start, end, speaker))
            continue
        dominated = False
        for o_start, o_end, o_speaker in segs:
            if o_speaker == speaker:
                continue
            overlap = max(0, min(end, o_end) - max(start, o_start))
            if overlap > dur * 0.5 and (o_end - o_start) > dur * 3:
                dominated = True
                break
        if not dominated:
            kept.append((start, end, speaker))
    return kept


def _assign_speakers_and_regroup(diarize_df, segments: list[dict]) -> list[dict]:
    if diarize_df is None or len(diarize_df) == 0:
        return segments

    raw_segs = [
        (row["start"], row["end"], row["speaker"])
        for _, row in diarize_df.iterrows()
    ]
    raw_segs.sort(key=lambda x: x[0])

    diar_segs = _filter_diarization_noise(raw_segs)

    boundaries = []
    for i in range(1, len(diar_segs)):
        boundaries.append({
            "time": (diar_segs[i - 1][1] + diar_segs[i][0]) / 2,
            "prev_speaker": diar_segs[i - 1][2],
            "next_speaker": diar_segs[i][2],
            "prev_end": diar_segs[i - 1][1],
            "next_start": diar_segs[i][0],
        })

    all_words = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" in w:
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

    for w in all_words:
        mid = (w["start"] + w.get("end", w["start"])) / 2
        best_speaker = None
        best_overlap = 0.0
        for ds_start, ds_end, ds_speaker in diar_segs:
            if ds_end < w["start"] - 1.0:
                continue
            if ds_start > w.get("end", w["start"]) + 1.0:
                break
            overlap = max(0, min(ds_end, w.get("end", w["start"])) - max(ds_start, w["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = ds_speaker
        if not best_speaker:
            min_dist = float("inf")
            for ds_start, ds_end, ds_speaker in diar_segs:
                dist = min(abs(mid - ds_start), abs(mid - ds_end))
                if dist < min_dist:
                    min_dist = dist
                    best_speaker = ds_speaker
        w["speaker"] = best_speaker

    SNAP_TOLERANCE = 4.0
    SELF_SNAP_TOLERANCE = 1.0
    for b in boundaries:
        if b["prev_speaker"] == b["next_speaker"]:
            continue
        bt = b["time"]
        tolerance = SELF_SNAP_TOLERANCE if SELF_SPEAKER in (b["prev_speaker"], b["next_speaker"]) else SNAP_TOLERANCE
        nearby_idx = []
        for i, w in enumerate(all_words):
            w_mid = (w["start"] + w.get("end", w["start"])) / 2
            if abs(w_mid - bt) < tolerance:
                nearby_idx.append(i)
        if not nearby_idx:
            continue

        best_split = None
        best_score = -1.0
        for i in nearby_idx:
            if i == 0:
                continue
            prev_end = all_words[i - 1].get("end", all_words[i - 1]["start"])
            cur_start = all_words[i]["start"]
            gap = cur_start - prev_end
            if gap < 0.05:
                continue
            score = gap
            prev_text = (all_words[i - 1].get("word") or all_words[i - 1].get("text", "")).strip()
            if prev_text and prev_text[-1] in ".?!":
                score += 2.0
            next_text = (all_words[i].get("word") or all_words[i].get("text", "")).strip()
            if next_text and next_text[0].isupper():
                score += 0.5
            if score > best_score:
                best_score = score
                best_split = i

        if best_split is not None and best_score >= 0.05:
            lo = nearby_idx[0]
            hi = nearby_idx[-1] + 1
            for i in range(lo, best_split):
                all_words[i]["speaker"] = b["prev_speaker"]
            for i in range(best_split, hi):
                all_words[i]["speaker"] = b["next_speaker"]

    return _words_to_segments(all_words)


def _words_to_segments(all_words: list[dict]) -> list[dict]:
    if not all_words:
        return []

    result = []
    cur_spk = all_words[0].get("speaker")
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
            cur_spk = w.get("speaker")
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

    merged = _merge_same_speaker(result)
    return _merge_sandwiched(merged)


def _merge_same_speaker(segments: list[dict]) -> list[dict]:
    if not segments:
        return segments
    merged = [segments[0]]
    for cur in segments[1:]:
        prev = merged[-1]
        if cur.get("speaker") == prev.get("speaker"):
            merged[-1] = {
                **prev,
                "end": cur["end"],
                "text": (prev.get("text", "") + " " + cur.get("text", "")).strip(),
            }
        else:
            merged.append(cur)
    return merged


def _merge_sandwiched(segments: list[dict], max_duration: float = 5.0) -> list[dict]:
    if len(segments) < 3:
        return segments
    changed = True
    while changed:
        changed = False
        new_segs = [segments[0]]
        i = 1
        while i < len(segments):
            cur = segments[i]
            prev = new_segs[-1]
            cur_dur = cur.get("end", 0) - cur.get("start", 0)
            nxt = segments[i + 1] if i + 1 < len(segments) else None
            if (
                cur_dur < max_duration
                and cur.get("speaker") != prev.get("speaker")
                and nxt
                and nxt.get("speaker") == prev.get("speaker")
            ):
                gap_before = cur.get("start", 0) - prev.get("end", 0)
                gap_after = nxt.get("start", 0) - cur.get("end", 0)
                if gap_before < 2.0 and gap_after < 2.0:
                    new_segs[-1] = {
                        **prev,
                        "end": nxt["end"],
                        "text": (prev.get("text", "") + " " + cur.get("text", "") + " " + nxt.get("text", "")).strip(),
                    }
                    i += 2
                    changed = True
                    continue
            new_segs.append(cur)
            i += 1
        segments = new_segs
    return segments


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
