import dataclasses
import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .config import Config
from .self_voice import SELF_SPEAKER
from .transcriber import _get_ffmpeg, load_embedding_inference, load_waveform

logger = logging.getLogger(__name__)

MAX_EMBEDDINGS = 30
MATCH_THRESHOLD = 0.5
MATCH_MARGIN = 0.05
MIN_CROP_SECONDS = 1.5
MAX_CROP_SECONDS = 10.0
CROPS_PER_SPEAKER = 12
SAMPLE_WINDOW_SECONDS = 4.0


@dataclasses.dataclass
class SpeakerProfile:
    slug: str
    name: str
    role: str
    description: str
    embeddings: np.ndarray | None
    sources: list = dataclasses.field(default_factory=list)

    @property
    def embedding(self) -> np.ndarray | None:
        if self.embeddings is None or len(self.embeddings) == 0:
            return None
        return _normalize(self.embeddings.mean(axis=0))


def _normalize(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _profiles_dir(config: Config) -> Path:
    return Path(config.speaker_profiles_dir)


def load_profile(profile_dir: Path) -> SpeakerProfile:
    meta = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
    embeddings = None
    if (profile_dir / "embeddings.npy").exists():
        embeddings = np.load(str(profile_dir / "embeddings.npy"))
    elif (profile_dir / "embedding.npy").exists():
        embeddings = np.load(str(profile_dir / "embedding.npy")).reshape(1, -1)
    sources = meta.get("embedding_sources") or []
    if embeddings is not None and len(sources) != len(embeddings):
        sources = [None] * len(embeddings)
    return SpeakerProfile(
        slug=profile_dir.name,
        name=meta["name"],
        role=meta.get("role", ""),
        description=meta.get("description", ""),
        embeddings=embeddings,
        sources=sources,
    )


def _write_profile(config: Config, profile: SpeakerProfile):
    profile_dir = _profiles_dir(config) / profile.slug
    profile_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": profile.name,
        "role": profile.role,
        "description": profile.description,
        "embedding_sources": profile.sources,
    }
    (profile_dir / "profile.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    emb_path = profile_dir / "embeddings.npy"
    if profile.embeddings is not None and len(profile.embeddings):
        np.save(str(emb_path), profile.embeddings.astype(np.float32))
    elif emb_path.exists():
        emb_path.unlink()
    legacy = profile_dir / "embedding.npy"
    if legacy.exists():
        legacy.unlink()


def list_profiles(config: Config) -> list[SpeakerProfile]:
    base = _profiles_dir(config)
    if not base.exists():
        return []
    profiles = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "profile.json").exists():
            profiles.append(load_profile(d))
    return profiles


def find_profile_by_name(config: Config, name: str) -> SpeakerProfile | None:
    wanted = name.strip().lower()
    for profile in list_profiles(config):
        if profile.name.strip().lower() == wanted:
            return profile
    return None


def _add_embeddings(profile: SpeakerProfile, embeddings: list, source=None):
    rows = [_normalize(e) for e in embeddings]
    if not rows:
        return
    existing = [] if profile.embeddings is None else list(profile.embeddings)
    sources = list(profile.sources) if profile.embeddings is not None else []
    existing.extend(rows)
    sources.extend([source] * len(rows))
    profile.embeddings = np.stack(existing[-MAX_EMBEDDINGS:])
    profile.sources = sources[-MAX_EMBEDDINGS:]


def save_profile(
    config: Config,
    name: str,
    role: str,
    description: str,
    embedding: np.ndarray | None,
    source=None,
) -> SpeakerProfile:
    slug = slugify(name) or "speaker"
    profile_dir = _profiles_dir(config) / slug
    if (profile_dir / "profile.json").exists():
        profile = load_profile(profile_dir)
        profile.name, profile.role, profile.description = name, role, description
    else:
        profile = SpeakerProfile(slug=slug, name=name, role=role, description=description, embeddings=None)
    if embedding is not None:
        _add_embeddings(profile, [embedding], source)
    _write_profile(config, profile)
    return profile


def update_profile(
    config: Config,
    slug: str,
    name: str | None = None,
    role: str | None = None,
    description: str | None = None,
) -> SpeakerProfile | None:
    profile_dir = _profiles_dir(config) / slug
    if not profile_dir.exists() or not (profile_dir / "profile.json").exists():
        return None
    profile = load_profile(profile_dir)
    if name is not None:
        profile.name = name
    if role is not None:
        profile.role = role
    if description is not None:
        profile.description = description
    _write_profile(config, profile)
    return profile


def delete_profile(config: Config, slug: str) -> bool:
    profile_dir = _profiles_dir(config) / slug
    if not profile_dir.exists():
        return False
    shutil.rmtree(profile_dir)
    return True


def extract_voice_sample(
    audio_path: str,
    segments: list[dict],
    speaker_id: str,
    profile_dir: Path,
) -> Path | None:
    speaker_segs = [s for s in segments if s.get("speaker") == speaker_id]
    speaker_segs.sort(key=lambda s: s.get("end", 0) - s.get("start", 0), reverse=True)

    selected = []
    total_dur = 0.0
    for s in speaker_segs:
        dur = s.get("end", 0) - s.get("start", 0)
        if dur < 0.5:
            continue
        selected.append(s)
        total_dur += dur
        if total_dur >= 15.0:
            break

    if not selected:
        return None

    ffmpeg = _get_ffmpeg()
    profile_dir = profile_dir.resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)
    out_path = profile_dir / "voice_sample.wav"
    abs_audio = str(Path(audio_path).resolve())

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        chunk_paths = []
        for i, s in enumerate(selected):
            chunk_path = str(tmp_dir / f"chunk_{i}.wav")
            subprocess.run(
                [ffmpeg, "-y", "-i", abs_audio,
                 "-ss", str(s["start"]), "-t", str(s["end"] - s["start"]),
                 "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", chunk_path],
                capture_output=True, timeout=60,
            )
            if Path(chunk_path).exists():
                chunk_paths.append(chunk_path)

        if not chunk_paths:
            return None

        if len(chunk_paths) == 1:
            shutil.copy2(chunk_paths[0], str(out_path))
        else:
            list_file = str(tmp_dir / "concat.txt")
            with open(list_file, "w") as f:
                for cp in chunk_paths:
                    f.write(f"file '{cp}'\n")
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                 "-c", "copy", str(out_path)],
                capture_output=True, timeout=60,
            )

    return out_path if out_path.exists() else None


def _embed(inference, audio: dict, start: float, end: float) -> np.ndarray | None:
    from pyannote.core import Segment

    duration = audio["waveform"].shape[-1] / audio["sample_rate"]
    end = min(end, duration - 0.02)
    if end - start < 0.5:
        return None
    try:
        emb = np.asarray(inference.crop(audio, Segment(start, end)))
    except Exception:
        logger.exception("Embedding extraction failed")
        return None
    if emb.ndim == 2:
        emb = emb.mean(axis=0)
    if not np.all(np.isfinite(emb)):
        return None
    return _normalize(emb)


def speaker_embeddings(
    audio: dict,
    segments: list[dict],
    speaker_id: str,
    inference,
) -> list[np.ndarray]:
    duration = audio["waveform"].shape[-1] / audio["sample_rate"]
    speaker_segs = [
        s for s in segments
        if s.get("speaker") == speaker_id and s.get("end", 0) - s.get("start", 0) >= MIN_CROP_SECONDS
    ]
    speaker_segs.sort(key=lambda s: s["end"] - s["start"], reverse=True)
    result = []
    for s in speaker_segs[:CROPS_PER_SPEAKER]:
        start, end = s["start"], min(s["end"], duration)
        if end - start > MAX_CROP_SECONDS:
            mid = (start + end) / 2
            start, end = mid - MAX_CROP_SECONDS / 2, mid + MAX_CROP_SECONDS / 2
        if end - start < MIN_CROP_SECONDS:
            continue
        emb = _embed(inference, audio, start, end)
        if emb is not None:
            result.append(emb)
    return result


def extract_speaker_embedding(
    audio_path: str,
    segments: list[dict],
    speaker_id: str,
    hf_token: str | None = None,
    inference=None,
) -> np.ndarray:
    inference = inference or load_embedding_inference(window="whole")
    embs = speaker_embeddings(load_waveform(audio_path), segments, speaker_id, inference)
    if not embs:
        raise ValueError(f"No usable segments found for {speaker_id}")
    return _normalize(np.mean(embs, axis=0))


def ensure_profile_embeddings(config: Config, inference=None) -> int:
    repaired = 0
    for profile in list_profiles(config):
        sample = _profiles_dir(config) / profile.slug / "voice_sample.wav"
        if profile.embedding is not None or not sample.exists():
            continue
        inference = inference or load_embedding_inference(window="whole")
        audio = load_waveform(str(sample))
        duration = audio["waveform"].shape[-1] / audio["sample_rate"]
        embs = []
        start = 0.0
        while start + MIN_CROP_SECONDS <= duration:
            emb = _embed(inference, audio, start, min(start + SAMPLE_WINDOW_SECONDS, duration))
            if emb is not None:
                embs.append(emb)
            start += SAMPLE_WINDOW_SECONDS
        if embs:
            _add_embeddings(profile, [np.mean(embs, axis=0)], {"voice_sample": True})
            _write_profile(config, profile)
            repaired += 1
    return repaired


def _profile_score(centroid: np.ndarray, profile: SpeakerProfile) -> float:
    sims = profile.embeddings @ centroid
    k = min(3, len(sims))
    return float(np.sort(sims)[-k:].mean())


def match_speakers(
    segments: list[dict],
    speaker_ids: list[str],
    config: Config,
    audio: dict,
    self_audio: dict | None = None,
    threshold: float = MATCH_THRESHOLD,
) -> dict:
    inference = load_embedding_inference(window="whole")
    try:
        ensure_profile_embeddings(config, inference)
    except Exception:
        logger.exception("Could not repair profile embeddings")

    centroids: dict[str, np.ndarray] = {}
    for sid in speaker_ids:
        source = self_audio if sid == SELF_SPEAKER and self_audio is not None else audio
        embs = speaker_embeddings(source, segments, sid, inference)
        if embs:
            centroids[sid] = _normalize(np.mean(embs, axis=0))
    del inference

    speaker_map = {s: s for s in speaker_ids}
    matched_profiles: dict[str, dict] = {}
    result = {
        "speaker_map": speaker_map,
        "matched_profiles": matched_profiles,
        "speaker_embeddings": {k: v.tolist() for k, v in centroids.items()},
    }
    profiles = [p for p in list_profiles(config) if p.embedding is not None]
    candidates = [sid for sid in centroids if sid != SELF_SPEAKER]
    if not profiles or not candidates:
        return result

    scores = {sid: {p.slug: _profile_score(centroids[sid], p) for p in profiles} for sid in candidates}
    by_slug = {p.slug: p for p in profiles}

    def _record(sid: str, prof: SpeakerProfile, score: float, merged: bool):
        speaker_map[sid] = prof.name
        matched_profiles[sid] = {
            "slug": prof.slug,
            "name": prof.name,
            "role": prof.role,
            "description": prof.description,
            "confidence": round(score, 3),
            "merged": merged,
        }

    ranked = sorted(
        ((score, sid, slug) for sid, row in scores.items() for slug, score in row.items()),
        reverse=True,
    )
    used_slugs: set[str] = set()
    for score, sid, slug in ranked:
        if score < threshold:
            break
        if sid in matched_profiles or slug in used_slugs:
            continue
        others = sorted((v for k, v in scores[sid].items() if k != slug), reverse=True)
        if others and score - others[0] < MATCH_MARGIN:
            continue
        _record(sid, by_slug[slug], score, merged=False)
        used_slugs.add(slug)

    for sid in candidates:
        if sid in matched_profiles:
            continue
        slug, score = max(scores[sid].items(), key=lambda kv: kv[1])
        if slug in used_slugs and score >= threshold:
            _record(sid, by_slug[slug], score, merged=True)

    return result


def learn_from_job(config: Config, job: dict, speaker_map: dict[str, str]) -> list[str]:
    stored = job.get("speaker_embeddings") or {}
    segments = job.get("segments") or []
    tracks = job.get("tracks") or {}
    job_id = job["job_id"]
    learned: list[str] = []
    inference = None
    audio_cache: dict[str, dict] = {}

    def _audio_path_for(sid: str) -> str:
        if sid == SELF_SPEAKER and tracks.get("mic"):
            return tracks["mic"]
        return tracks.get("system") or job["audio_path"]

    def _audio_for(sid: str) -> dict:
        path = _audio_path_for(sid)
        if path not in audio_cache:
            audio_cache[path] = load_waveform(path)
        return audio_cache[path]

    for sid, name in speaker_map.items():
        name = (name or "").strip()
        if not name or name == sid:
            continue
        if sid in stored:
            emb = _normalize(stored[sid])
        else:
            inference = inference or load_embedding_inference(window="whole")
            embs = speaker_embeddings(_audio_for(sid), segments, sid, inference)
            if not embs:
                continue
            emb = _normalize(np.mean(embs, axis=0))

        source = {"job": job_id, "speaker": sid}
        for profile in list_profiles(config):
            if source in profile.sources:
                keep = [i for i, src in enumerate(profile.sources) if src != source]
                profile.embeddings = profile.embeddings[keep] if keep else None
                profile.sources = [profile.sources[i] for i in keep]
                _write_profile(config, profile)

        profile = find_profile_by_name(config, name) or save_profile(config, name, "", "", None)
        _add_embeddings(profile, [emb], source)
        _write_profile(config, profile)

        sample_dir = _profiles_dir(config) / profile.slug
        if not (sample_dir / "voice_sample.wav").exists():
            try:
                extract_voice_sample(_audio_path_for(sid), segments, sid, sample_dir)
            except Exception:
                logger.exception("Could not extract voice sample")
        learned.append(profile.name)
    return learned
