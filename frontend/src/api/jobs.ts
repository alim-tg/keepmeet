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
    slug: string
    name: string
    role: string
    description: string
    confidence: number
    merged?: boolean
    self?: boolean
  }>
  source: string | null
  publish_status: string | null
  publish_error: string | null
  tracks: Record<string, string>
  learned_voices: string[]
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

export function reformatJob(id: string) {
  return apiFetch<{ ok: boolean; formatted_notes: string }>(`/jobs/${id}/reformat`, {
    method: "POST",
  })
}

export function publishJob(id: string, spaceKey: string, parentPageId: string) {
  return apiFetch<{ ok: boolean; confluence_url: string }>(`/jobs/${id}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ space_key: spaceKey, parent_page_id: parentPageId || null }),
  })
}

export function getConfig() {
  return apiFetch<AppConfig>("/config")
}
