import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Save, RefreshCw } from "lucide-react"
import type { JobDetail } from "@/api/jobs"

interface SpeakerEditorProps {
  job: JobDetail
  onSave: (map: Record<string, string>) => Promise<void>
  onReformat: () => Promise<void>
  saving: boolean
  reformatting: boolean
}

export function SpeakerEditor({ job, onSave, onReformat, saving, reformatting }: SpeakerEditorProps) {
  const [localMap, setLocalMap] = useState<Record<string, string>>({ ...job.speaker_map })

  const samples: Record<string, string> = {}
  for (const seg of job.segments ?? []) {
    const spk = (seg as Record<string, string>).speaker
    if (spk && !samples[spk]) {
      samples[spk] = ((seg as Record<string, string>).text ?? "").slice(0, 100)
    }
  }

  return (
    <div className="space-y-5">
      {job.speakers.map((spk) => (
        <div key={spk} className="space-y-2 rounded-xl bg-white/[0.02] border border-white/[0.04] p-4">
          <Label className="text-xs text-muted-foreground font-mono">{spk}</Label>
          <Input
            value={localMap[spk] ?? spk}
            onChange={(e) => setLocalMap((m) => ({ ...m, [spk]: e.target.value }))}
            placeholder="Enter speaker name..."
          />
          {samples[spk] && (
            <p className="text-xs text-muted-foreground/60 italic leading-relaxed">"{samples[spk]}"</p>
          )}
        </div>
      ))}
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
