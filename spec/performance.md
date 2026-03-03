# keepmeet-ai — Performance

## Benchmarks (RTX 3050 4GB, i7-12700, 40GB RAM)

Tested with 16-minute audio file (16MB m4a), Russian language, 5 speakers.

| Stage | GPU Time | What happens |
|-------|----------|-------------|
| Audio loading | ~1 sec | ffmpeg decodes m4a → 16kHz mono numpy array |
| Transcription | ~2 min | Whisper medium (int8) processes audio in batches |
| Alignment | ~30 sec | wav2vec2 aligns words to timestamps |
| Diarization | ~1 min | pyannote identifies speaker segments |
| Claude formatting | ~15 sec | Claude Code CLI structures the notes |
| **Total** | **~3.5 min** | |

## Estimated Processing Times by Model

For a 15-minute recording:

| Model | GPU (RTX 3050) | CPU (i7-12700) |
|-------|----------------|----------------|
| tiny | ~15 sec | ~1 min |
| small | ~30-40 sec | ~2-3 min |
| medium | ~1-1.5 min | ~5-7 min |
| large-v3 | ~2-3 min | ~15-20 min |

Diarization adds ~1 min (GPU) or ~2-3 min (CPU) on top.

## VRAM Usage (Peak, per stage)

| Stage | VRAM |
|-------|------|
| Whisper medium (int8) | ~1.5 GB |
| wav2vec2 alignment | ~1.5 GB |
| pyannote diarization | ~1.5 GB |
| **Peak (sequential)** | **~1.5-2 GB** |

Models are never loaded simultaneously. Each is deleted and VRAM freed before the next loads.

## Hardware Recommendations

| GPU VRAM | Recommended model | Batch size |
|----------|-------------------|------------|
| 2 GB | small | 1-2 |
| 4 GB | medium (int8) | 4 |
| 6 GB | medium (float16) | 8 |
| 8 GB+ | large-v3 | 8-16 |
| CPU only | small | 4 |

## First Run

First run downloads models from HuggingFace (~3-5 GB total). Subsequent runs use cached models from `~/.cache/huggingface/hub/`.
