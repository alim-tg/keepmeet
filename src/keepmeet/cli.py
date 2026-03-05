import shutil
from datetime import date
from pathlib import Path

import click

from .config import ConfigError, load_config
from .pipeline import PipelineOptions, process_meeting
from .speakers import load_speaker_map, save_speaker_map
from .transcriber import TranscriptionError


@click.group()
def cli():
    pass


@cli.command()
@click.argument("audio_file", type=click.Path(exists=True))
@click.option("--date", "-d", "meeting_date", default=None,
              help="Meeting date (YYYY-MM-DD). Defaults to today.")
@click.option("--language", "-l", default=None,
              help="Audio language code (en, ru). Auto-detect if omitted.")
@click.option("--speakers", "-s", "speaker_profile", default=None,
              type=click.Path(),
              help="Path to speaker profile JSON.")
@click.option("--skip-diarization", is_flag=True,
              help="Skip speaker diarization.")
@click.option("--skip-format", is_flag=True,
              help="Output raw transcript only, skip Claude formatting.")
@click.option("--skip-publish", is_flag=True,
              help="Do not publish to Confluence.")
@click.option("--skip-speaker-prompt", is_flag=True,
              help="Use default speaker labels without prompting.")
@click.option("--output-dir", "-o", default="./output",
              type=click.Path(),
              help="Directory for output files.")
def process(audio_file, meeting_date, language, speaker_profile,
            skip_diarization, skip_format, skip_publish, skip_speaker_prompt,
            output_dir):
    try:
        config = load_config()
    except ConfigError as e:
        raise click.ClickException(str(e))

    if not meeting_date:
        meeting_date = str(date.today())

    if not speaker_profile:
        speaker_profile = str(
            Path(config.speaker_profiles_dir) / config.default_speaker_profile
        )

    options = PipelineOptions(
        meeting_date=meeting_date,
        speaker_profile=speaker_profile,
        output_dir=output_dir,
        skip_diarization=skip_diarization,
        skip_format=skip_format,
        skip_publish=skip_publish,
        skip_speaker_prompt=skip_speaker_prompt,
    )

    try:
        result = process_meeting(audio_file, config, options)
    except TranscriptionError as e:
        raise click.ClickException(str(e))

    click.echo("\nDone!")
    if result.confluence_url:
        click.echo(f"Confluence: {result.confluence_url}")


@cli.command("speakers")
@click.argument("profile", type=click.Path(), required=False)
def speakers_cmd(profile):
    try:
        config = load_config()
    except ConfigError as e:
        raise click.ClickException(str(e))

    if not profile:
        profile = str(
            Path(config.speaker_profiles_dir) / config.default_speaker_profile
        )

    mapping = load_speaker_map(profile)

    if mapping:
        click.echo("Current speaker mappings:")
        for speaker_id, name in mapping.items():
            click.echo(f"  {speaker_id} -> {name}")
        click.echo()

    click.echo("Edit mappings (press Enter to keep current, type 'delete' to remove):")
    updated = {}
    for speaker_id, name in mapping.items():
        new_name = click.prompt(f"  {speaker_id}", default=name)
        if new_name.lower() != "delete":
            updated[speaker_id] = new_name

    add_more = click.confirm("Add a new speaker?", default=False)
    while add_more:
        speaker_id = click.prompt("  Speaker ID (e.g. SPEAKER_03)")
        name = click.prompt("  Name")
        updated[speaker_id] = name
        add_more = click.confirm("Add another?", default=False)

    save_speaker_map(profile, updated)
    click.echo(f"Saved to {profile}")


@cli.command()
def check():
    click.echo("Checking configuration and dependencies...\n")
    ok = True

    try:
        config = load_config()
        click.echo("[OK] Config loaded")
    except ConfigError as e:
        click.echo(f"[FAIL] Config: {e}")
        ok = False
        config = None

    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            click.echo(f"[OK] CUDA available: {name} ({mem:.1f} GB)")
        else:
            click.echo("[WARN] CUDA not available, will use CPU (slower)")
    except ImportError:
        click.echo("[FAIL] PyTorch not installed")
        ok = False

    try:
        import whisperx
        click.echo("[OK] whisperX installed")
    except ImportError:
        click.echo("[FAIL] whisperX not installed")
        ok = False

    if config and config.hf_token:
        click.echo("[OK] HuggingFace token set")
    else:
        click.echo("[FAIL] HF_TOKEN not set in .env")
        ok = False

    if config and config.deepinfra_api_key:
        click.echo("[OK] DeepInfra API key set")
    else:
        click.echo("[FAIL] DEEPINFRA_API_KEY not set in .env")
        ok = False

    if shutil.which("claude"):
        click.echo("[OK] claude CLI found")
    else:
        click.echo("[WARN] claude CLI not found (needed for --skip-format=false)")

    if config and config.confluence_base_url and config.confluence_api_token:
        click.echo("[OK] Confluence configured")
    else:
        click.echo("[WARN] Confluence not configured (publishing will be skipped)")

    click.echo()
    if ok:
        click.echo("All checks passed. Ready to process meetings.")
    else:
        click.echo("Some checks failed. Fix the issues above before proceeding.")
