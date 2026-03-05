import { useState, useEffect } from "react"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { listProfiles, updateProfile, deleteProfile, type SpeakerProfile } from "@/api/profiles"
import { AudioPlayer } from "@/components/AudioPlayer"
import { Pencil, Trash2, X, Check, AudioLines } from "lucide-react"

export function ProfilesPage() {
  const [profiles, setProfiles] = useState<SpeakerProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [editingSlug, setEditingSlug] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({ name: "", role: "", description: "" })
  const [saving, setSaving] = useState(false)
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null)

  const fetchProfiles = () => {
    listProfiles()
      .then(setProfiles)
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchProfiles() }, [])

  const startEdit = (p: SpeakerProfile) => {
    setEditingSlug(p.slug)
    setEditForm({ name: p.name, role: p.role, description: p.description })
  }

  const cancelEdit = () => {
    setEditingSlug(null)
  }

  const saveEdit = async (slug: string) => {
    setSaving(true)
    try {
      const updated = await updateProfile(slug, editForm)
      setProfiles((prev) => prev.map((p) => (p.slug === slug ? updated : p)))
      setEditingSlug(null)
    } catch {
    } finally {
      setSaving(false)
    }
  }

  const confirmDelete = async (slug: string) => {
    try {
      await deleteProfile(slug)
      setProfiles((prev) => prev.filter((p) => p.slug !== slug))
    } catch {
    } finally {
      setDeletingSlug(null)
    }
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-white to-white/60 bg-clip-text text-transparent">
          Speaker Profiles
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {profiles.length > 0
            ? `${profiles.length} profile${profiles.length > 1 ? "s" : ""}`
            : "No profiles yet"}
        </p>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40 w-full rounded-2xl" />
          ))}
        </div>
      ) : profiles.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
          <div className="h-16 w-16 rounded-2xl bg-white/[0.04] flex items-center justify-center mb-4">
            <span className="text-2xl">👤</span>
          </div>
          <p className="text-muted-foreground text-sm">No speaker profiles</p>
          <p className="text-muted-foreground/60 text-xs mt-1">
            Create profiles from a job's Speakers tab
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {profiles.map((p, i) => (
            <Card
              key={p.slug}
              className="p-5 animate-fade-in relative group"
              style={{ animationDelay: `${i * 50}ms` }}
            >
              {editingSlug === p.slug ? (
                <div className="space-y-3">
                  <Input
                    value={editForm.name}
                    onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                    placeholder="Name"
                  />
                  <Input
                    value={editForm.role}
                    onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                    placeholder="Role"
                  />
                  <Input
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    placeholder="Description"
                  />
                  <div className="flex gap-2 justify-end">
                    <Button variant="ghost" size="sm" onClick={cancelEdit} disabled={saving}>
                      <X className="h-4 w-4" />
                      Cancel
                    </Button>
                    <Button size="sm" onClick={() => saveEdit(p.slug)} disabled={saving}>
                      <Check className="h-4 w-4" />
                      Save
                    </Button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold truncate">{p.name}</span>
                        {p.role && <Badge variant="outline">{p.role}</Badge>}
                      </div>
                      {p.description && (
                        <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">
                          {p.description}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => startEdit(p)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      {deletingSlug === p.slug ? (
                        <div className="flex items-center gap-1">
                          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setDeletingSlug(null)}>
                            <X className="h-3.5 w-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-red-400 hover:text-red-300 hover:bg-red-500/10" onClick={() => confirmDelete(p.slug)}>
                            <Check className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ) : (
                        <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-red-400" onClick={() => setDeletingSlug(p.slug)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="mt-3 pt-3 border-t border-white/[0.06] space-y-2.5">
                    <div className="flex items-center gap-1.5">
                      <AudioLines className={`h-3.5 w-3.5 ${p.has_embedding ? "text-emerald-400" : "text-muted-foreground/40"}`} />
                      <span className={`text-xs ${p.has_embedding ? "text-emerald-400" : "text-muted-foreground/40"}`}>
                        {p.has_embedding ? "Voice linked" : "No voice"}
                      </span>
                    </div>
                    {p.has_voice_sample && (
                      <AudioPlayer src={`/api/profiles/${p.slug}/voice-sample`} />
                    )}
                  </div>
                </>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
