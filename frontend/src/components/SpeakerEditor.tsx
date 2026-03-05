import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Save, RefreshCw, UserPlus, Loader2, Check, ChevronDown, ChevronUp } from "lucide-react"
import type { JobDetail } from "@/api/jobs"
import { createProfileFromJob } from "@/api/profiles"

interface SpeakerEditorProps {
  job: JobDetail
  onSave: (map: Record<string, string>) => Promise<void>
  onReformat: () => Promise<void>
  saving: boolean
  reformatting: boolean
}

export function SpeakerEditor({ job, onSave, onReformat, saving, reformatting }: SpeakerEditorProps) {
  const [localMap, setLocalMap] = useState<Record<string, string>>({ ...job.speaker_map })
  const [expandedProfile, setExpandedProfile] = useState<string | null>(null)
  const [profileForms, setProfileForms] = useState<Record<string, { name: string; role: string; description: string }>>({})
  const [savingProfile, setSavingProfile] = useState<string | null>(null)
  const [savedProfiles, setSavedProfiles] = useState<Set<string>>(new Set())

  const matched = job.matched_profiles ?? {}

  const samples: Record<string, string> = {}
  for (const seg of job.segments ?? []) {
    const spk = (seg as Record<string, string>).speaker
    if (spk && !samples[spk]) {
      samples[spk] = ((seg as Record<string, string>).text ?? "").slice(0, 100)
    }
  }

  const toggleProfile = (spk: string) => {
    if (expandedProfile === spk) {
      setExpandedProfile(null)
    } else {
      setExpandedProfile(spk)
      if (!profileForms[spk]) {
        const match = matched[spk]
        setProfileForms((f) => ({
          ...f,
          [spk]: {
            name: localMap[spk] !== spk ? localMap[spk] : match?.name ?? "",
            role: match?.role ?? "",
            description: match?.description ?? "",
          },
        }))
      }
    }
  }

  const handleSaveProfile = async (spk: string) => {
    const form = profileForms[spk]
    if (!form?.name) return
    setSavingProfile(spk)
    try {
      await createProfileFromJob(job.job_id, spk, form)
      setSavedProfiles((s) => new Set(s).add(spk))
      setExpandedProfile(null)
    } catch {
      // let user retry
    } finally {
      setSavingProfile(null)
    }
  }

  return (
    <div className="space-y-5">
      {job.speakers.map((spk) => {
        const match = matched[spk]
        const isExpanded = expandedProfile === spk
        const form = profileForms[spk]
        const isSaving = savingProfile === spk
        const isSaved = savedProfiles.has(spk)

        return (
          <div key={spk} className="space-y-2 rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
            <div className="flex items-center gap-2">
              <Label className="text-xs text-muted-foreground font-mono">{spk}</Label>
              {match && (
                <Badge variant="secondary" className="text-xs gap-1">
                  {match.name} - {Math.round(match.confidence * 100)}%
                </Badge>
              )}
              {match?.role && (
                <span className="text-xs text-muted-foreground">{match.role}</span>
              )}
            </div>
            <Input
              value={localMap[spk] ?? spk}
              onChange={(e) => setLocalMap((m) => ({ ...m, [spk]: e.target.value }))}
              placeholder="Enter speaker name..."
            />
            {match?.description && (
              <p className="text-xs text-muted-foreground/80">{match.description}</p>
            )}
            {samples[spk] && (
              <p className="text-xs text-muted-foreground/60 italic leading-relaxed">"{samples[spk]}"</p>
            )}

            {isSaved ? (
              <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                <Check className="h-3.5 w-3.5" /> Profile saved
              </div>
            ) : (
              <button
                onClick={() => toggleProfile(spk)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors bg-transparent border-none p-0 cursor-pointer"
              >
                {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                <UserPlus className="h-3 w-3" /> Save as Profile
              </button>
            )}

            {isExpanded && (
              <div className="space-y-3 pt-2 pl-4 border-l-2 border-white/[0.06]">
                <div>
                  <Label className="text-xs text-muted-foreground">Name</Label>
                  <Input
                    value={form?.name ?? ""}
                    onChange={(e) =>
                      setProfileForms((f) => ({ ...f, [spk]: { ...f[spk], name: e.target.value } }))
                    }
                    placeholder="Full name..."
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Role</Label>
                  <Input
                    value={form?.role ?? ""}
                    onChange={(e) =>
                      setProfileForms((f) => ({ ...f, [spk]: { ...f[spk], role: e.target.value } }))
                    }
                    placeholder="e.g. Engineering Lead..."
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">Description</Label>
                  <Input
                    value={form?.description ?? ""}
                    onChange={(e) =>
                      setProfileForms((f) => ({ ...f, [spk]: { ...f[spk], description: e.target.value } }))
                    }
                    placeholder="e.g. Works on backend platform..."
                  />
                </div>
                <Button
                  size="sm"
                  onClick={() => handleSaveProfile(spk)}
                  disabled={isSaving || !form?.name}
                >
                  {isSaving ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" /> Extracting voice...
                    </>
                  ) : (
                    <>
                      <UserPlus className="h-3.5 w-3.5" /> Save Profile
                    </>
                  )}
                </Button>
              </div>
            )}
          </div>
        )
      })}
      <div className="flex gap-3 pt-2">
        <Button onClick={() => onSave(localMap)} disabled={saving}>
          <Save className="h-4 w-4" />
          {saving ? "Saving..." : "Save Names"}
        </Button>
        <Button variant="outline" onClick={onReformat} disabled={reformatting}>
          <RefreshCw className={`h-4 w-4 ${reformatting ? "animate-spin" : ""}`} />
          {reformatting ? "Re-formatting..." : "Re-format Notes"}
        </Button>
      </div>
    </div>
  )
}
