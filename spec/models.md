# keepmeet-ai — Models & Dependencies

## ML Models

### 1. Whisper (Speech-to-Text)

| Property | Value |
|----------|-------|
| Source | OpenAI Whisper via [WhisperX](https://github.com/m-bain/whisperX) |
| Backend | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) |
| Default model | `medium` |
| Compute type | `int8` (quantized) |
| Languages | Auto-detect, supports English + Russian |
| VRAM usage | ~1.5-2 GB (medium, int8) |

Available model sizes:

| Model | VRAM (int8) | VRAM (float16) | Quality (RU) |
|-------|-------------|----------------|--------------|
| tiny | ~0.5 GB | ~1 GB | poor |
| base | ~0.5 GB | ~1 GB | basic |
| small | ~1 GB | ~2 GB | decent |
| **medium** | **~1.5 GB** | **~2.5 GB** | **good** |
| large-v3 | ~3 GB | ~4 GB | best |

### 2. wav2vec2 (Word Alignment)

| Property | Value |
|----------|-------|
| Source | HuggingFace Hub, auto-selected by whisperX |
| English | `jonatasgrosman/wav2vec2-large-xlsr-53-english` |
| Russian | `jonatasgrosman/wav2vec2-large-xlsr-53-russian` |
| Purpose | Aligns transcribed text to precise word-level timestamps |
| VRAM usage | ~1.5 GB |

### 3. Pyannote (Speaker Diarization)

| Property | Value |
|----------|-------|
| Source | [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) |
| Library | [pyannote-audio](https://github.com/pyannote/pyannote-audio) 4.x |
| Auth | Requires HuggingFace token (`HF_TOKEN`) |
| License | Accept on HuggingFace (free) |
| VRAM usage | ~1-1.5 GB |
| Output | Speaker segments: `SPEAKER_00`, `SPEAKER_01`, etc. |

Also requires license acceptance for:
- [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0)
- [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)

### 4. Claude (Meeting Notes Formatting)

| Property | Value |
|----------|-------|
| Tool | Claude Code CLI (`claude` binary) |
| Invocation | `claude -p --output-format text` via subprocess |
| Input | Raw transcript piped via stdin |
| Output | Structured markdown meeting notes |
| Timeout | 120 seconds |

## VRAM Management Strategy

Models are loaded and unloaded **sequentially** — never simultaneously in VRAM:

```
Timeline:
├── Load Whisper ──── transcribe ──── del + gc + empty_cache
├── Load wav2vec2 ─── align ───────── del + gc + empty_cache
└── Load pyannote ─── diarize ─────── del + gc + empty_cache

Peak VRAM: ~1.5-2 GB (one model at a time)
Total GPU memory needed: 4 GB sufficient
```

OOM fallback: if transcription fails with `batch_size=4`, retries with `batch_size=1`.

## Python Dependencies

| Package | Role |
|---------|------|
| `whisperx` | Orchestrates transcription + alignment + diarization |
| `torch` + `torchaudio` | GPU inference, CUDA memory management |
| `click` | CLI framework |
| `requests` | HTTP client for Confluence REST API |
| `pyyaml` | Config file parsing |
| `python-dotenv` | .env secrets loading |
| `imageio-ffmpeg` | Bundled ffmpeg binary fallback (Windows) |

## External Services

| Service | Protocol | Auth |
|---------|----------|------|
| HuggingFace Hub | HTTPS | Bearer token (`HF_TOKEN`) |
| Confluence Cloud | REST API v2 | Basic Auth (email + API token) |
| Claude Code | Local subprocess | Uses local Claude session |
