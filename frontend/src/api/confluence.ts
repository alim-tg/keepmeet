import { apiFetch } from "./client"

export interface ConfluenceTarget {
  base_url: string
  space_key: string
  parent_id: string | null
  parent_name: string | null
}

export interface ConfluenceStatus {
  connected: boolean
  user: { name: string | null; email: string } | null
  error: string | null
  target: ConfluenceTarget | null
}

export function getConfluenceStatus() {
  return apiFetch<ConfluenceStatus>("/confluence/status")
}

export function connectConfluence(email: string, token: string) {
  return apiFetch<ConfluenceStatus>("/confluence/auth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, token }),
  })
}

export function disconnectConfluence() {
  return apiFetch<ConfluenceStatus>("/confluence/auth", { method: "DELETE" })
}
