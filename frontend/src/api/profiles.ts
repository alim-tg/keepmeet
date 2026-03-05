import { apiFetch } from "./client"

export interface SpeakerProfile {
  slug: string
  name: string
  role: string
  description: string
  has_embedding: boolean
  has_voice_sample: boolean
}

export interface ProfileCreateRequest {
  name: string
  role: string
  description: string
}

export function listProfiles() {
  return apiFetch<SpeakerProfile[]>("/profiles")
}

export function createProfileFromJob(jobId: string, speakerId: string, data: ProfileCreateRequest) {
  return apiFetch<SpeakerProfile>(`/profiles/from-job/${jobId}/${speakerId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
}

export function updateProfile(slug: string, data: Partial<Pick<SpeakerProfile, "name" | "role" | "description">>) {
  return apiFetch<SpeakerProfile>(`/profiles/${slug}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  })
}

export function deleteProfile(slug: string) {
  return apiFetch<{ ok: boolean }>(`/profiles/${slug}`, { method: "DELETE" })
}
