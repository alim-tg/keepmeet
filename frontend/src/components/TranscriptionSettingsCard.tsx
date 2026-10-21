import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { getSuggestedTerms, type TranscriptionSettings } from "@/api/settings"
import { cn } from "@/lib/utils"
import { AudioLines, Plus } from "lucide-react"

const LANGUAGES: { code: string; label: string }[] = [
  { code: "ru", label: "Russian" },
  { code: "en", label: "English" },
  { code: "uk", label: "Ukrainian" },
  { code: "he", label: "Hebrew" },
  { code: "de", label: "German" },
]

const MODELS: { value: TranscriptionSettings["model"]; label: string; description: string }[] = [
  { value: "whisper-large-v3", label: "Best quality", description: "Whisper large-v3. Keeps English terms in Latin and uses your vocabulary. About $2.70 per hour of speech." },
  { value: "whisper-large-v3-turbo", label: "Cheaper", description: "Whisper turbo. Faster and about half the price, but ignores the vocabulary and writes more terms in Cyrillic." },
]

const textareaClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-3.5 py-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"

interface Props {
  settings: TranscriptionSettings
  onChange: (settings: TranscriptionSettings) => void
}

function parseTerms(text: string) {
  return text.split(/[,\n;]/).map((t) => t.trim()).filter(Boolean)
}

export function TranscriptionSettingsCard({ settings, onChange }: Props) {
  const [suggested, setSuggested] = useState<string[]>([])

  useEffect(() => {
    getSuggestedTerms().then((r) => setSuggested(r.terms)).catch(() => {})
  }, [])

  const current = new Set(parseTerms(settings.vocabulary).map((t) => t.toLowerCase()))
  const remaining = suggested.filter((t) => !current.has(t.toLowerCase()))

  const toggleLanguage = (code: string) => {
    const has = settings.languages.includes(code)
    const next = has ? settings.languages.filter((l) => l !== code) : [...settings.languages, code]
    if (next.length) onChange({ ...settings, languages: next })
  }

  const addTerm = (term: string) => {
    const terms = parseTerms(settings.vocabulary)
    onChange({ ...settings, vocabulary: [...terms, term].join(", ") })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AudioLines className="h-4 w-4 text-primary" />
          Transcription
        </CardTitle>
        <CardDescription>How speech is turned into text. Language is detected for every part of the meeting, so switching between languages mid-meeting works.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <Label>Languages spoken in your meetings</Label>
          <div className="flex flex-wrap gap-2">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                type="button"
                onClick={() => toggleLanguage(l.code)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors cursor-pointer",
                  settings.languages.includes(l.code)
                    ? "border-primary/40 bg-primary/15 text-primary"
                    : "border-white/10 text-muted-foreground hover:text-foreground"
                )}
              >
                {l.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">Only these languages are considered. The first one is used when detection is unsure.</p>
        </div>

        <div className="space-y-2">
          <Label>Quality</Label>
          {MODELS.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => onChange({ ...settings, model: m.value })}
              className={cn(
                "w-full text-left rounded-lg border px-4 py-3 transition-colors",
                settings.model === m.value ? "border-primary/40 bg-primary/10" : "border-white/[0.06] hover:bg-white/[0.03]"
              )}
            >
              <div className="text-sm font-medium">{m.label}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{m.description}</div>
            </button>
          ))}
        </div>

        <div className="space-y-2">
          <Label>Vocabulary</Label>
          <textarea
            className={`${textareaClass} min-h-[80px]`}
            value={settings.vocabulary}
            placeholder="Billing Service, CRM, Kubernetes, feature flag, DLQ"
            onChange={(e) => onChange({ ...settings, vocabulary: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">
            Product, service and project names, comma separated. They're spelled this way in transcripts. Names from voice profiles are added automatically.
          </p>
          {remaining.length > 0 && (
            <div className="space-y-1.5 pt-1">
              <div className="text-xs text-muted-foreground">Found in your recent meetings. Add the ones that are spelled correctly:</div>
              <div className="flex flex-wrap gap-1.5">
                {remaining.map((term) => (
                  <button
                    key={term}
                    type="button"
                    onClick={() => addTerm(term)}
                    className="inline-flex items-center gap-1 rounded-full border border-white/10 px-2.5 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:border-primary/30 cursor-pointer"
                  >
                    <Plus className="h-3 w-3" /> {term}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
