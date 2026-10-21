import { apiFetch } from "./client"

export interface JobSummary {
  job_id: string
  status: string
  title: string
  meeting_date: string
  language: string | null
  created_at: string
  source: string | null
  publish_status: string | null
}

export interface JobDetail {
  job_id: string
  status: string
  stage: string | null
  error: string | null
  title: string
  meeting_date: string
  language: string | null
  created_at: string
  completed_at: string | null
  audio_filename: string
  speakers: string[]
  speaker_map: Record<string, string>
  segments: Record<string, string>[]
  raw_transcript: string | null
  formatted_notes: string | null
  confluence_url: string | null
  matched_profiles: Record<string, {
    slug: string | null
    name: string
    role?: string
    description?: string
    confidence: number | null
    merged?: boolean
    self?: boolean
    source?: "voice" | "conversation" | "voice+conversation" | "microphone"
    evidence?: string
  }>
  source: string | null
  publish_status: string | null
  publish_error: string | null
  tracks: Record<string, string>
  learned_voices: string[]
  publish_title: string | null
  languages: Record<string, number>
  notes_context: string | null
  notes_edited: boolean
  name_suggestions: Record<string, string>
  note_format: string | null
  note_format_override: string | null
}

export interface AppConfig {
  confluence_base_url: string
  confluence_space_key: string
  confluence_parent_page_id: string | null
}

export function listJobs() {
  return apiFetch<JobSummary[]>("/jobs")
}

export function getJob(id: string) {
  return apiFetch<JobDetail>(`/jobs/${id}`)
}

export function deleteJob(id: string) {
  return apiFetch<{ ok: boolean }>(`/jobs/${id}`, { method: "DELETE" })
}

export async function createJob(file: File, title: string, meetingDate: string, language: string, numSpeakers?: number) {
  const form = new FormData()
  form.append("file", file)
  form.append("title", title)
  form.append("meeting_date", meetingDate)
  form.append("language", language)
  if (numSpeakers !== undefined) {
    form.append("num_speakers", String(numSpeakers))
  }
  return apiFetch<{ job_id: string }>("/jobs", { method: "POST", body: form })
}

export function createJobFromLink(url: string, title?: string, meetingDate?: string, language?: string) {
  return apiFetch<{ job_id: string }>("/jobs/from-link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      title: title || null,
      meeting_date: meetingDate || null,
      language: language || null,
    }),
  })
}

export function updateSpeakers(id: string, speakerMap: Record<string, string>) {
  return apiFetch<{ ok: boolean; raw_transcript: string }>(`/jobs/${id}/speakers`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speaker_map: speakerMap }),
  })
}

export interface NotesResult {
  ok: boolean
  formatted_notes: string
  name_suggestions: Record<string, string>
  notes_edited: boolean
  note_format: string | null
}

export function reformatJob(id: string, context?: string, noteFormat?: string) {
  const body: Record<string, string> = {}
  if (context !== undefined) body.context = context
  if (noteFormat !== undefined) body.note_format = noteFormat
  return apiFetch<NotesResult>(`/jobs/${id}/reformat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export interface NoteFormatOption {
  key: string
  label: string
  when: string
}

export function getNoteFormats() {
  return apiFetch<{ formats: NoteFormatOption[] }>("/note-formats")
}

export function saveNotes(id: string, formattedNotes: string) {
  return apiFetch<{ ok: boolean; unnamed: string[] }>(`/jobs/${id}/notes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ formatted_notes: formattedNotes }),
  })
}

export function publishJob(id: string, title: string) {
  return apiFetch<{ ok: boolean; confluence_url: string; title: string }>(`/jobs/${id}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  })
}

export function getConfig() {
  return apiFetch<AppConfig>("/config")
}

export function retryJob(id: string) {
  return apiFetch<{ ok: boolean; mode: "notes" | "full" }>(`/jobs/${id}/retry`, { method: "POST" })
}

export function retranscribeJob(id: string) {
  return apiFetch<{ ok: boolean }>(`/jobs/${id}/retranscribe`, { method: "POST" })
}
