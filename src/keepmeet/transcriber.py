import dataclasses
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .asr import chunking, cleanup, deepinfra, vocabulary
from .asr.alignment import assign_speakers
from .asr.audio import (
    AudioError,
    as_waveform,
    ffmpeg_path,
    load_samples,
    load_waveform,
    to_wav_bytes,
)
from .asr.diarization import diarize, load_embedding_inference
from .asr.language import detect_window_languages
from .asr.vad import speech_regions
from .config import Config
from .self_voice import detect_self_regions

logger = logging.getLogger(__name__)

PARALLEL_REQUESTS = 3
JOBS_DIR = Path("data") / "jobs"

__all__ = [
    "TranscriptResult",
    "TranscriptionError",
    "extract_speakers",
    "ffmpeg_path",
    "format_raw_transcript",
    "load_embedding_inference",
    "load_samples",
    "load_waveform",
    "suggested_terms",
    "transcribe_audio",
]


class TranscriptionError(Exception):
    pass


@dataclasses.dataclass
class TranscriptResult:
    segments: list[dict]
    language: str
    languages: dict[str, float] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class TranscriptionOptions:
    model: str
    languages: list[str]
    names: list[str]
    terms: list[str]


def _load_options(config: Config) -> TranscriptionOptions:
    from .settings import load_settings
    from .speaker_profiles import list_profiles

    settings = load_settings(config)
    opts = settings["transcription"]
    names = [settings["my_name"]] + [p.name for p in list_profiles(config)]
    return TranscriptionOptions(
        model=opts["model"],
        languages=opts["languages"],
        names=names,
        terms=vocabulary.split_terms(opts["vocabulary"]),
    )


def suggested_terms(config: Config) -> list[str]:
    from . import knowledge
    from .settings import load_settings

    options = _load_options(config)
    exclude = {n.lower() for n in options.names if n} | {t.lower() for t in options.terms}
    kb = knowledge.load(load_settings(config)["knowledge"]["path"])
    from_system = [t for t in (kb.terms if kb else []) if t.lower() not in exclude]
    exclude |= {t.lower() for t in from_system}
    harvested = vocabulary.harvest_terms(JOBS_DIR, exclude) if JOBS_DIR.exists() else []
    return from_system + harvested


def _transcribe_chunk(samples, chunk: chunking.Chunk, options: TranscriptionOptions, api_key: str) -> list[dict]:
    audio, time_map = chunking.render(samples, chunk.spans)
    wav = to_wav_bytes(audio)
    results = {}
    for language in chunk.candidates:
        prompt = vocabulary.build_prompt(options.names, options.terms, language)
        results[language] = deepinfra.transcribe(wav, api_key, options.model, language, prompt)
    language = max(results, key=lambda lang: results[lang]["score"])
    if chunk.ambiguous:
        logger.info(
            "Ambiguous %.0fs at %.0fs: %s -> %s",
            chunk.speech_seconds, chunk.spans[0][0],
            ", ".join(f"{lang} {r['score']:.2f}" for lang, r in results.items()), language,
        )
    result = results[language]
    words = cleanup.clean_words(result["segments"], result["words"])
    if words and not words[0].get("raw", " ").startswith(" "):
        words[0] = {**words[0], "raw": " " + words[0]["raw"]}
    return [
        {
            "word": w["word"],
            "raw": w.get("raw", " " + w["word"]),
            "start": time_map.to_source(w["start"]),
            "end": time_map.to_source(w["end"]),
            "language": language,
        }
        for w in words
    ]


def _plan_chunks(samples, options: TranscriptionOptions) -> list[chunking.Chunk]:
    regions = speech_regions(samples)
    windows = chunking.build_windows(regions)
    window_audio = [chunking.render(samples, spans)[0] for spans in windows]
    choices = detect_window_languages(window_audio, options.languages)
    chunks = chunking.group_chunks(windows, choices)
    speech = sum(c.speech_seconds for c in chunks)
    logger.info(
        "Speech %.0fs of %.0fs in %d chunks (%s)",
        speech, len(samples) / 16000, len(chunks),
        " ".join("/".join(c.candidates) for c in chunks),
    )
    return chunks


def _language_shares(words: list[dict]) -> dict[str, float]:
    seconds: Counter = Counter()
    for w in words:
        seconds[w["language"]] += max(0.0, w["end"] - w["start"])
    total = sum(seconds.values()) or 1.0
    return {lang: round(s / total, 3) for lang, s in seconds.most_common()}


def transcribe_audio(
    audio_path: str,
    config: Config,
    on_stage=None,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    system_track: str | None = None,
    mic_track: str | None = None,
) -> TranscriptResult:
    def stage(name: str):
        if on_stage:
            on_stage(name)

    started = time.time()
    try:
        options = _load_options(config)
        samples = load_samples(audio_path)
        stage("transcribing")
        chunks = _plan_chunks(samples, options)
    except AudioError as e:
        raise TranscriptionError(str(e)) from e
    if not chunks:
        return TranscriptResult(segments=[], language=options.languages[0])

    diarize_samples = load_samples(system_track) if system_track else samples
    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        futures = [
            pool.submit(_transcribe_chunk, samples, chunk, options, config.deepinfra_api_key)
            for chunk in chunks
        ]
        stage("diarizing")
        try:
            self_regions = detect_self_regions(load_samples(mic_track), diarize_samples) if mic_track and system_track else []
            turns = diarize(
                as_waveform(diarize_samples), config.hf_token, self_regions,
                num_speakers, min_speakers, max_speakers,
            )
        except Exception as e:
            for f in futures:
                f.cancel()
            raise TranscriptionError(f"Diarization failed: {e}") from e
        try:
            words = [w for f in futures for w in f.result()]
        except deepinfra.AsrError as e:
            raise TranscriptionError(str(e)) from e

    words.sort(key=lambda w: w["start"])
    shares = _language_shares(words)
    segments = assign_speakers(turns, words)
    logger.info("Transcribed %d words, languages %s, in %.0fs", len(words), shares, time.time() - started)
    return TranscriptResult(
        segments=segments,
        language=next(iter(shares), options.languages[0]),
        languages=shares,
    )


def format_raw_transcript(result: TranscriptResult, speaker_map: dict[str, str]) -> str:
    lines: list[str] = []
    for seg in result.segments:
        speaker_id = seg.get("speaker", "UNKNOWN")
        name = speaker_map.get(speaker_id, speaker_id)
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{_fmt_time(seg.get('start', 0))} - {_fmt_time(seg.get('end', 0))}] {name}:\n{text}\n")
    return "\n".join(lines)


def extract_speakers(result: TranscriptResult) -> list[str]:
    return list(dict.fromkeys(seg.get("speaker", "UNKNOWN") for seg in result.segments))


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
