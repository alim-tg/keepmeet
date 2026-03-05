import dataclasses
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .config import Config
from .transcriber import _get_ffmpeg


@dataclasses.dataclass
class SpeakerProfile:
    slug: str
    name: str
    role: str
    description: str
    embedding: np.ndarray | None


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _profiles_dir(config: Config) -> Path:
    return Path(config.speaker_profiles_dir)


def load_profile(profile_dir: Path) -> SpeakerProfile:
    meta = json.loads((profile_dir / "profile.json").read_text(encoding="utf-8"))
    embedding = None
    emb_path = profile_dir / "embedding.npy"
    if emb_path.exists():
        embedding = np.load(str(emb_path))
    return SpeakerProfile(
        slug=profile_dir.name,
        name=meta["name"],
        role=meta.get("role", ""),
        description=meta.get("description", ""),
        embedding=embedding,
    )


def list_profiles(config: Config) -> list[SpeakerProfile]:
    base = _profiles_dir(config)
    if not base.exists():
        return []
    profiles = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "profile.json").exists():
            profiles.append(load_profile(d))
    return profiles


def save_profile(
    config: Config,
    name: str,
    role: str,
    description: str,
    embedding: np.ndarray | None,
) -> SpeakerProfile:
    slug = slugify(name)
    profile_dir = _profiles_dir(config) / slug
    profile_dir.mkdir(parents=True, exist_ok=True)

    meta = {"name": name, "role": role, "description": description}
    (profile_dir / "profile.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

    if embedding is not None:
        np.save(str(profile_dir / "embedding.npy"), embedding)

    return SpeakerProfile(
        slug=slug, name=name, role=role, description=description, embedding=embedding
    )


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
    meta = {"name": profile.name, "role": profile.role, "description": profile.description}
    (profile_dir / "profile.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
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


def extract_speaker_embedding(
    audio_path: str,
    segments: list[dict],
    speaker_id: str,
    hf_token: str,
) -> np.ndarray:
    from pyannote.audio import Inference
    from pyannote.core import Segment
    import torch

    speaker_segs = [
        s for s in segments if s.get("speaker") == speaker_id
    ]
    speaker_segs.sort(key=lambda s: s.get("end", 0) - s.get("start", 0), reverse=True)

    selected = []
    total_dur = 0.0
    for s in speaker_segs:
        dur = s.get("end", 0) - s.get("start", 0)
        if dur < 0.5:
            continue
        selected.append(s)
        total_dur += dur
        if total_dur >= 30.0:
            break

    if not selected:
        raise ValueError(f"No usable segments found for {speaker_id}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    inference = Inference(
        "pyannote/embedding", use_auth_token=hf_token, device=device
    )

    embeddings = []
    for s in selected:
        seg = Segment(s["start"], s["end"])
        emb = inference.crop(audio_path, seg)
        if emb.ndim == 2:
            emb = emb.mean(axis=0)
        embeddings.append(emb)

    mean_emb = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(mean_emb)
    if norm > 0:
        mean_emb = mean_emb / norm
    return mean_emb


def match_speakers(
    audio_path: str,
    segments: list[dict],
    speaker_ids: list[str],
    config: Config,
    threshold: float = 0.7,
) -> dict:
    profiles = list_profiles(config)
    profiles_with_emb = [p for p in profiles if p.embedding is not None]

    if not profiles_with_emb:
        return {"speaker_map": {s: s for s in speaker_ids}, "matched_profiles": {}}

    speaker_embeddings = {}
    for sid in speaker_ids:
        try:
            emb = extract_speaker_embedding(
                audio_path, segments, sid, config.hf_token
            )
            speaker_embeddings[sid] = emb
        except (ValueError, Exception):
            continue

    if not speaker_embeddings:
        return {"speaker_map": {s: s for s in speaker_ids}, "matched_profiles": {}}

    speaker_map = {}
    matched_profiles = {}
    used_profiles: set[str] = set()
    used_speakers: set[str] = set()

    scores = []
    for sid, emb in speaker_embeddings.items():
        for prof in profiles_with_emb:
            sim = float(np.dot(emb, prof.embedding))
            scores.append((sim, sid, prof))

    scores.sort(key=lambda x: x[0], reverse=True)

    for sim, sid, prof in scores:
        if sid in used_speakers or prof.slug in used_profiles:
            continue
        if sim < threshold:
            break
        speaker_map[sid] = prof.name
        matched_profiles[sid] = {
            "slug": prof.slug,
            "name": prof.name,
            "role": prof.role,
            "description": prof.description,
            "confidence": round(sim, 3),
        }
        used_speakers.add(sid)
        used_profiles.add(prof.slug)

    for sid in speaker_ids:
        if sid not in speaker_map:
            speaker_map[sid] = sid

    return {"speaker_map": speaker_map, "matched_profiles": matched_profiles}
