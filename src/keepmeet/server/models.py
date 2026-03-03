from typing import Any

from pydantic import BaseModel


class SpeakerUpdateRequest(BaseModel):
    speaker_map: dict[str, str]


class ReformatRequest(BaseModel):
    pass


class PublishRequest(BaseModel):
    space_key: str
    parent_page_id: str | None = None


class JobSummary(BaseModel):
    job_id: str
    status: str
    title: str
    meeting_date: str
    language: str | None
    created_at: str


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


class ConfigResponse(BaseModel):
    confluence_base_url: str
    confluence_space_key: str
    confluence_parent_page_id: str | None
