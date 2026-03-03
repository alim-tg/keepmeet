# keepmeet-ai — Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         keepmeet CLI                                │
│                    (python -m keepmeet process)                      │
└──────────────┬──────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        PIPELINE (pipeline.py)                        │
│                                                                      │
│  ┌────────────┐   ┌───────────┐   ┌────────────┐   ┌────────────┐  │
│  │ 1. TRANSCR │──▶│ 2. ALIGN  │──▶│ 3. DIARIZE │──▶│ 4. SPEAKER │  │
│  │   IBE      │   │           │   │            │   │    MAP     │  │
│  └────────────┘   └───────────┘   └────────────┘   └─────┬──────┘  │
│       │                │               │                   │         │
│   del model        del model       del model          save JSON     │
│   gc.collect()     gc.collect()    gc.collect()                     │
│   cuda.empty()     cuda.empty()    cuda.empty()                     │
│                                                                      │
│                        ┌──────────────────┐                          │
│                        │ 5. RAW TRANSCRIPT │                         │
│                        │    (save .txt)    │                         │
│                        └────────┬─────────┘                          │
│                                 │                                    │
│                                 ▼                                    │
│                   ┌──────────────────────────┐                       │
│                   │ 6. CLAUDE CODE CLI        │                      │
│                   │ (subprocess: claude -p)   │                      │
│                   │ → structured meeting notes│                      │
│                   └────────────┬─────────────┘                       │
│                                │                                     │
│                                ▼                                     │
│                   ┌──────────────────────────┐                       │
│                   │ 7. CONFLUENCE REST API v2 │                      │
│                   │ (create/update page)      │                      │
│                   └──────────────────────────┘                       │
└──────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
Audio File (.m4a/.wav/.mp3)
    │
    │  ffmpeg (via imageio_ffmpeg)
    ▼
numpy array (16kHz mono)
    │
    │  Whisper medium (int8, GPU)
    ▼
segments[] = [{text, start, end}, ...]  +  detected language
    │
    │  wav2vec2 alignment model
    ▼
segments[] = [{text, start, end, words[]}, ...]  (word-level timestamps)
    │
    │  pyannote diarization pipeline
    ▼
segments[] = [{text, start, end, speaker: "SPEAKER_XX"}, ...]
    │
    │  speaker profile mapping (JSON)
    ▼
raw transcript (timestamped text with speaker names)
    │
    │  Claude Code CLI (subprocess)
    ▼
formatted meeting notes (markdown)
    │
    │  markdown → Confluence storage format (XHTML)
    ▼
Confluence page (REST API v2)
```
