import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { CopyButton } from "@/components/CopyButton"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { getNoteFormats, saveNotes, type JobDetail, type NoteFormatOption } from "@/api/jobs"
import { Select } from "@/components/ui/select"
import { AlertTriangle, Loader2, Pencil, RefreshCw, Save, X } from "lucide-react"

const LABEL_RE = /\b(?:SPEAKER_\d+|SELF)\b/g

interface NotesPanelProps {
  job: JobDetail
  reformatting: boolean
  onRegenerate: (context: string, noteFormat: string) => Promise<void>
  onNotesSaved: (notes: string) => void
  onGoToSpeakers: () => void
}

const textareaClass =
  "w-full rounded-lg border border-white/10 bg-white/[0.04] px-3.5 py-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"

export function NotesPanel({ job, reformatting, onRegenerate, onNotesSaved, onGoToSpeakers }: NotesPanelProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(job.formatted_notes ?? "")
  const [saving, setSaving] = useState(false)
  const [context, setContext] = useState(job.notes_context ?? "")
  const [formats, setFormats] = useState<NoteFormatOption[]>([])
  const [noteFormat, setNoteFormat] = useState(job.note_format_override ?? "auto")

  useEffect(() => {
    getNoteFormats().then((r) => setFormats(r.formats)).catch(() => {})
  }, [])

  const detected = formats.find((f) => f.key === job.note_format)?.label

  const notes = job.formatted_notes ?? ""
  const unnamed = [...new Set(notes.match(LABEL_RE) ?? [])]

  const startEditing = () => {
    setDraft(notes)
    setEditing(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await saveNotes(job.job_id, draft)
      onNotesSaved(draft.trim())
      setEditing(false)
      toast.success("Notes saved")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      {unnamed.length > 0 && !editing && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-300">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            The notes still mention {unnamed.join(", ")}, so they can't be published yet.{" "}
            <button onClick={onGoToSpeakers} className="underline bg-transparent border-none p-0 text-amber-300 cursor-pointer">
              Name them in Speakers
            </button>{" "}
            and regenerate, add who they are in the context below, or edit the notes.
          </div>
        </div>
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Meeting Notes</CardTitle>
          <div className="flex items-center gap-2">
            {editing ? (
              <>
                <Button variant="secondary" size="sm" onClick={() => setEditing(false)} disabled={saving}>
                  <X className="h-3.5 w-3.5" /> Cancel
                </Button>
                <Button size="sm" onClick={handleSave} disabled={saving || !draft.trim()}>
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                  Save
                </Button>
              </>
            ) : (
              <>
                {notes && (
                  <Button variant="secondary" size="sm" onClick={startEditing} disabled={reformatting}>
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </Button>
                )}
                {notes && <CopyButton text={notes} />}
              </>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {editing ? (
            <textarea
              className={`${textareaClass} min-h-[480px] font-mono leading-relaxed`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          ) : reformatting ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> Regenerating notes...
            </div>
          ) : notes ? (
            <MarkdownRenderer content={notes} />
          ) : (
            <p className="text-muted-foreground">No formatted notes yet</p>
          )}
        </CardContent>
      </Card>

      {!editing && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <RefreshCw className="h-4 w-4 text-primary" />
              Regenerate with more context
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Label>Format</Label>
            <Select value={noteFormat} onChange={(e) => setNoteFormat(e.target.value)}>
              <option value="auto">Auto{detected ? ` (currently ${detected})` : ""}</option>
              {formats.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              {noteFormat === "auto"
                ? "The format is picked from the meeting title and conversation."
                : formats.find((f) => f.key === noteFormat)?.when && `For ${formats.find((f) => f.key === noteFormat)?.when}.`}
            </p>
            <Label>Additional context for Claude</Label>
            <textarea
              className={`${textareaClass} min-h-[96px]`}
              value={context}
              placeholder={"e.g. SPEAKER_02 is Alex, our QA lead.\nDavid joined from the data team. Keep the blockers short."}
              onChange={(e) => setContext(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Names you set in the Speakers tab and saved voice profiles are always used. This text is saved with the meeting.
              {job.notes_edited && " Regenerating replaces your manual edits."}
            </p>
            <Button onClick={() => onRegenerate(context, noteFormat)} disabled={reformatting}>
              {reformatting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {reformatting ? "Regenerating..." : "Regenerate notes"}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
