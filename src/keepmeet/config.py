import dataclasses
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclasses.dataclass
class Config:
    hf_token: str
    deepinfra_api_key: str
    confluence_base_url: str
    confluence_email: str
    confluence_api_token: str
    confluence_space_key: str
    confluence_parent_page_id: str | None
    speaker_profiles_dir: str
    default_speaker_profile: str
    graph_client_id: str
    graph_tenant_id: str
    teams_enabled: bool
    teams_poll_interval: int
    teams_recordings_folder: str


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
    speakers = cfg.get("speakers", {})
    teams = cfg.get("teams", {}) or {}

    hf_token = os.getenv("HF_TOKEN", "")
    if not hf_token:
        raise ConfigError("HF_TOKEN is required in .env for pyannote diarization model access")

    deepinfra_api_key = os.getenv("DEEPINFRA_API_KEY", "")
    if not deepinfra_api_key:
        raise ConfigError("DEEPINFRA_API_KEY is required in .env for transcription")

    return Config(
        hf_token=hf_token,
        deepinfra_api_key=deepinfra_api_key,
        confluence_base_url=confluence.get("base_url", ""),
        confluence_email=os.getenv("CONFLUENCE_EMAIL", ""),
        confluence_api_token=os.getenv("CONFLUENCE_API_TOKEN", ""),
        confluence_space_key=confluence.get("space_key", ""),
        confluence_parent_page_id=confluence.get("parent_page_id"),
        speaker_profiles_dir=speakers.get("profiles_dir", "./speaker_profiles"),
        default_speaker_profile=speakers.get("default_profile", "default.json"),
        graph_client_id=os.getenv("GRAPH_CLIENT_ID", ""),
        graph_tenant_id=os.getenv("GRAPH_TENANT_ID", ""),
        teams_enabled=bool(teams.get("enabled", True)),
        teams_poll_interval=int(teams.get("poll_interval_seconds", 300)),
        teams_recordings_folder=teams.get("recordings_folder", "Recordings"),
    )
