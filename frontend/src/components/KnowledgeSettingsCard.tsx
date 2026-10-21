import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Toggle } from "@/components/Toggle"
import { getKnowledgeStatus, type KnowledgeStatus } from "@/api/settings"
import { BookOpen, CheckCircle2, XCircle } from "lucide-react"

interface Props {
  path: string
  lookups: boolean
  savedPath: string
  onChange: (value: { path: string; lookups: boolean }) => void
}

export function KnowledgeSettingsCard({ path, lookups, savedPath, onChange }: Props) {
  const [status, setStatus] = useState<KnowledgeStatus | null>(null)

  useEffect(() => {
    getKnowledgeStatus().then(setStatus).catch(() => {})
  }, [savedPath])

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          System knowledge
        </CardTitle>
        <CardDescription>
          Point keepmeet at a folder with your team's docs. Its glossary.md and index.md go into every notes prompt,
          so misheard service names get corrected and technical points come out precise.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>Knowledge folder</Label>
          <Input
            value={path}
            placeholder="C:\path\to\team-docs"
            onChange={(e) => onChange({ path: e.target.value, lookups })}
          />
          {status && path === savedPath && status.configured && (
            <p className={`flex items-center gap-1.5 text-xs ${status.loaded ? "text-emerald-400" : "text-red-400"}`}>
              {status.loaded ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
              {status.loaded
                ? `Loaded: glossary and index (${Math.round((status.digest_chars ?? 0) / 1000)}K characters, ${status.terms} terms)`
                : status.error}
            </p>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.06] px-4 py-2.5">
          <div>
            <div className="text-sm font-medium">Deep lookups</div>
            <div className="text-xs text-muted-foreground">
              Let the notes writer read other files in the folder (read-only) when a meeting goes deep on a service. Takes a bit longer.
            </div>
          </div>
          <Toggle checked={lookups} onChange={(v) => onChange({ path, lookups: v })} />
        </div>
      </CardContent>
    </Card>
  )
}
