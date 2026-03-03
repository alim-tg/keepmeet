import dataclasses
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Config:
    hf_token: str
    confluence_base_url: str
    confluence_email: str
    confluence_api_token: str
    confluence_space_key: str
    confluence_parent_page_id: str | None
    whisper_model: str
    compute_type: str
    batch_size: int
    language: str | None
    speaker_profiles_dir: str
    default_speaker_profile: str


def load_config(
    env_path: str | None = None,
    yaml_path: str | None = None,
) -> Config:
    root = Path.cwd()

    load_dotenv(env_path or root / ".env")

    yaml_file = Path(yaml_path) if yaml_path else root / "config.yaml"
    cfg: dict = {}
    if yaml_file.exists():
        with open(yaml_file, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    confluence = cfg.get("confluence", {})
    whisper = cfg.get("whisper", {})
    speakers = cfg.get("speakers", {})

    hf_token = os.getenv("HF_TOKEN", "")
    if not hf_token:
        raise ConfigError("HF_TOKEN is required in .env for pyannote diarization model access")

    return Config(
        hf_token=hf_token,
        confluence_base_url=confluence.get("base_url", ""),
        confluence_email=os.getenv("CONFLUENCE_EMAIL", ""),
        confluence_api_token=os.getenv("CONFLUENCE_API_TOKEN", ""),
        confluence_space_key=confluence.get("space_key", ""),
        confluence_parent_page_id=confluence.get("parent_page_id"),
        whisper_model=whisper.get("model", "medium"),
        compute_type=whisper.get("compute_type", "int8"),
        batch_size=whisper.get("batch_size", 4),
        language=whisper.get("language"),
        speaker_profiles_dir=speakers.get("profiles_dir", "./speaker_profiles"),
        default_speaker_profile=speakers.get("default_profile", "default.json"),
    )
