import { apiFetch } from "./client"

export type PublishMode = "manual" | "auto" | "auto_if_matched"

export interface SourceSettings {
  onedrive: boolean
  meeting_chats: boolean
  shared_with_me: boolean
}

export interface LocalRecorderSettings {
  enabled: boolean
  include_mic: boolean
  auto_stop: boolean
  min_duration_seconds: number
}

export interface RecorderStatus {
  available: boolean
  enabled: boolean
  teams_in_call: boolean
  recording: boolean
  mode: "auto" | "manual" | null
  started_at: string | null
  meeting_name: string | null
  mic_error: string | null
  last_error: string | null
  last_job_id: string | null
  quiet_seconds: number
}

export interface TranscriptionSettings {
  model: "whisper-large-v3" | "whisper-large-v3-turbo"
  languages: string[]
  vocabulary: string
}

export interface Settings {
  watcher_enabled: boolean
  poll_interval_seconds: number
  recordings_folder: string
  sources: SourceSettings
  meeting_filter: string
  publish_mode: PublishMode
  notifications: boolean
  my_name: string
  confluence: { target_url: string }
  transcription: TranscriptionSettings
  knowledge: { path: string; lookups: boolean }
  local_recorder: LocalRecorderSettings
}

export interface LoginState {
  state: "idle" | "pending" | "success" | "failed"
  user_code?: string
  verification_uri?: string
  message?: string
  account?: string
  error?: string
}

export interface TeamsStatus {
  running: boolean
  enabled: boolean
  configured: boolean
  signed_in: boolean
  account: string | null
  chat_access: boolean | null
  last_poll_at: string | null
  last_error: string | null
  ingested_count: number
  sources: Record<string, { last_poll_at: string; last_error: string | null }>
  login: LoginState
}

export function getSettings() {
  return apiFetch<Settings>("/settings")
}

export function saveSettings(settings: Partial<Settings>) {
  return apiFetch<Settings>("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  })
}

export function getTeamsStatus() {
  return apiFetch<TeamsStatus>("/teams/status")
}

export function startTeamsLogin() {
  return apiFetch<LoginState>("/teams/login", { method: "POST" })
}

export function pollNow() {
  return apiFetch<{ ok: boolean }>("/teams/poll", { method: "POST" })
}

export function getRecorderStatus() {
  return apiFetch<RecorderStatus>("/recorder/status")
}

export function startRecording() {
  return apiFetch<RecorderStatus>("/recorder/start", { method: "POST" })
}

export function stopRecording() {
  return apiFetch<{ ok: boolean; job_id: string | null }>("/recorder/stop", { method: "POST" })
}

export function getSuggestedTerms() {
  return apiFetch<{ terms: string[] }>("/transcription/suggested-terms")
}

export interface KnowledgeStatus {
  configured: boolean
  loaded: boolean
  error?: string
  digest_chars?: number
  terms?: number
}

export function getKnowledgeStatus() {
  return apiFetch<KnowledgeStatus>("/knowledge/status")
}
