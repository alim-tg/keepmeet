from typing import Any, Literal

from pydantic import BaseModel


class SpeakerUpdateRequest(BaseModel):
    speaker_map: dict[str, str]


class ReformatRequest(BaseModel):
    context: str | None = None
    note_format: str | None = None


class NotesUpdateRequest(BaseModel):
    formatted_notes: str


class PublishRequest(BaseModel):
    title: str | None = None


class ConfluenceAuthRequest(BaseModel):
    email: str
    token: str


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
    publish_title: str | None = None
    languages: dict[str, float] = {}
    notes_context: str | None = None
    note_format: str | None = None
    note_format_override: str | None = None
    notes_edited: bool = False
    name_suggestions: dict[str, str] = {}


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
    auto_stop: bool = True
    min_duration_seconds: int = 60


class KnowledgeSettings(BaseModel):
    path: str = ""
    lookups: bool = True


class TranscriptionSettings(BaseModel):
    model: Literal["whisper-large-v3", "whisper-large-v3-turbo"] = "whisper-large-v3"
    languages: list[str] = ["ru", "en"]
    vocabulary: str = ""


class ConfluenceSettings(BaseModel):
    target_url: str = ""


class Settings(BaseModel):
    watcher_enabled: bool
    poll_interval_seconds: int
    recordings_folder: str
    sources: SourceSettings
    meeting_filter: str
    publish_mode: Literal["manual", "auto", "auto_if_matched"]
    notifications: bool
    my_name: str = ""
    confluence: ConfluenceSettings = ConfluenceSettings()
    transcription: TranscriptionSettings = TranscriptionSettings()
    knowledge: KnowledgeSettings = KnowledgeSettings()
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
    confluence: ConfluenceSettings | None = None
    transcription: TranscriptionSettings | None = None
    knowledge: KnowledgeSettings | None = None
    local_recorder: LocalRecorderSettings | None = None
