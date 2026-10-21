import logging

import numpy as np

from ..self_voice import overlay_self
from .audio import free_gpu_memory

logger = logging.getLogger(__name__)

PIPELINE_NAME = "pyannote/speaker-diarization-3.1"
EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"

Turn = tuple[float, float, str]


def load_embedding_inference(window: str = "sliding"):
    import torch
    from pyannote.audio import Inference, Model

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return Inference(Model.from_pretrained(EMBEDDING_MODEL), window=window, device=device)


def _run_pipeline(audio: dict, hf_token: str, speaker_hints: dict) -> list[Turn]:
    import torch
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(PIPELINE_NAME, token=hf_token)
    pipeline.to(torch.device("cuda" if torch.cuda.is_available() else "cpu"))
    try:
        params = pipeline.parameters(instantiated=True)
        params["segmentation"]["min_duration_off"] = 0.2
        pipeline.instantiate(params)
    except Exception:
        logger.warning("Could not tune diarization parameters, using defaults")

    output = pipeline(audio, **{k: v for k, v in speaker_hints.items() if v is not None})
    annotation = getattr(output, "speaker_diarization", output)
    turns = sorted(
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    )
    del pipeline
    free_gpu_memory()
    return turns


def diarize(
    audio: dict,
    hf_token: str,
    self_regions: list[tuple[float, float]] | None = None,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[Turn]:
    turns = _run_pipeline(audio, hf_token, {
        "num_speakers": num_speakers,
        "min_speakers": min_speakers,
        "max_speakers": max_speakers,
    })
    inference = load_embedding_inference()
    try:
        turns = _merge_similar_speakers(turns, audio, inference)
        turns = _refine_diarization(turns, audio, inference)
    except Exception:
        logger.exception("Diarization refinement failed, using raw turns")
    finally:
        del inference
        free_gpu_memory()
    return overlay_self(turns, self_regions or [])


def _refine_diarization(diar_segs: list[tuple], audio, inference) -> list[tuple]:
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
