# keepmeet-ai — Configuration

## Files

| File | Contents | Git tracked |
|------|----------|-------------|
| `.env` | Secrets (tokens, credentials) | No |
| `config.yaml` | Non-secret settings | No |
| `.env.example` | Template for `.env` | Yes |
| `config.yaml.example` | Template for `config.yaml` | Yes |

## .env (secrets)

```
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx
CONFLUENCE_EMAIL=your.email@company.com
CONFLUENCE_API_TOKEN=xxxxxxxxxxxxxxxx
```

| Variable | Required | Purpose |
|----------|----------|---------|
| `HF_TOKEN` | Yes | HuggingFace token for downloading pyannote models |
| `CONFLUENCE_EMAIL` | For publishing | Atlassian account email |
| `CONFLUENCE_API_TOKEN` | For publishing | Atlassian API token (Settings → Security → API tokens) |

## config.yaml (settings)

```yaml
confluence:
  base_url: https://yourcompany.atlassian.net
  space_key: "TEAM"
  parent_page_id: null

whisper:
  model: medium
  compute_type: int8
  batch_size: 4
  language: null

speakers:
  profiles_dir: ./speaker_profiles
  default_profile: default.json
```

| Setting | Default | Options |
|---------|---------|---------|
| `whisper.model` | `medium` | tiny, base, small, medium, large-v3 |
| `whisper.compute_type` | `int8` | int8, float16, float32 |
| `whisper.batch_size` | `4` | 1-16 (lower = less VRAM) |
| `whisper.language` | `null` | null (auto), en, ru, etc. |
| `confluence.parent_page_id` | `null` | Page ID to nest notes under |

## CLI Options

```
keepmeet process <audio_file> [OPTIONS]

Options:
  -d, --date TEXT              Meeting date (YYYY-MM-DD), defaults to today
  -l, --language TEXT          Force language (en, ru), auto-detect if omitted
  -s, --speakers PATH          Speaker profile JSON path
      --skip-diarization       Skip speaker identification
      --skip-format            Output raw transcript only, no Claude formatting
      --skip-publish           Do not publish to Confluence
      --skip-speaker-prompt    Use SPEAKER_XX labels without interactive prompt
  -o, --output-dir PATH        Output directory (default: ./output)

keepmeet speakers [PROFILE]    Edit speaker name mappings interactively
keepmeet check                 Verify config, GPU, and dependencies
```

## Speaker Profiles

Stored as JSON in `speaker_profiles/`:

```json
{
    "SPEAKER_00": "John Smith",
    "SPEAKER_01": "Maria Ivanova",
    "SPEAKER_02": "Alex Petrov"
}
```

Speaker numbering is NOT consistent across recordings. Each recording may assign different numbers to the same person. Map manually after each run, or use `--skip-speaker-prompt` to keep default labels.

## Output Files

| File | Content |
|------|---------|
| `output/transcript-YYYY-MM-DD.txt` | Raw transcript with timestamps and speaker labels |
| `output/notes-YYYY-MM-DD.md` | Formatted meeting notes (markdown) |
