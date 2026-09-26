from typing import Any, Literal

from pydantic import BaseModel


class SpeakerUpdateRequest(BaseModel):
    speaker_map: dict[str, str]


class ReformatRequest(BaseModel):
    pass


class PublishRequest(BaseModel):
    space_key: str
    parent_page_id: str | None = None


class JobFromLinkRequest(BaseModel):
    url: str
    title: str | None = None
    meeting_date: str | None = None
    language: str | None = None


class JobSummary(BaseModel):
    job_id: str
    status: str
    title: str
    meeting_date: str
    language: str | None
    created_at: str
    source: str | None = None
    publish_status: str | None = None


class JobDetail(BaseModel):
    job_id: str
    status: str
    stage: str | None
    error: str | None
    title: str
    meeting_date: str
    language: str | None
    created_at: str
    completed_at: str | None
    audio_filename: str
    speakers: list[str]
    speaker_map: dict[str, str]
    segments: list[dict[str, Any]] = []
    raw_transcript: str | None
    formatted_notes: str | None
    confluence_url: str | None
    matched_profiles: dict[str, Any] = {}
    source: str | None = None
    publish_status: str | None = None
    publish_error: str | None = None
    tracks: dict[str, str] = {}
    learned_voices: list[str] = []


class SpeakerProfileResponse(BaseModel):
    slug: str
    name: str
    role: str
    description: str
    has_embedding: bool
    has_voice_sample: bool = False


class SpeakerProfileCreateRequest(BaseModel):
    name: str
    role: str = ""
    description: str = ""


class SpeakerProfileUpdateRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    description: str | None = None


class ConfigResponse(BaseModel):
    confluence_base_url: str
    confluence_space_key: str
    confluence_parent_page_id: str | None


class SourceSettings(BaseModel):
    onedrive: bool = True
    meeting_chats: bool = True
    shared_with_me: bool = False


class LocalRecorderSettings(BaseModel):
    enabled: bool = False
    include_mic: bool = True
    min_duration_seconds: int = 60


class Settings(BaseModel):
    watcher_enabled: bool
    poll_interval_seconds: int
    recordings_folder: str
    sources: SourceSettings
    meeting_filter: str
    publish_mode: Literal["manual", "auto", "auto_if_matched"]
    notifications: bool
    my_name: str = ""
    local_recorder: LocalRecorderSettings


class SettingsUpdateRequest(BaseModel):
    watcher_enabled: bool | None = None
    poll_interval_seconds: int | None = None
    recordings_folder: str | None = None
    sources: SourceSettings | None = None
    meeting_filter: str | None = None
    publish_mode: Literal["manual", "auto", "auto_if_matched"] | None = None
    notifications: bool | None = None
    my_name: str | None = None
    local_recorder: LocalRecorderSettings | None = None
