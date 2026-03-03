import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { FileDropzone } from "@/components/FileDropzone"
import { createJob } from "@/api/jobs"
import { ArrowLeft, Loader2, Sparkles } from "lucide-react"
import { Link } from "react-router-dom"

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

export function NewJobPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState(`Daily Standup - ${todayStr()}`)
  const [date, setDate] = useState(todayStr())
  const [language, setLanguage] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")

  const handleDateChange = (d: string) => {
    setDate(d)
    setTitle(`Daily Standup - ${d}`)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return
    setSubmitting(true)
    setError("")
    try {
      const res = await createJob(file, title, date, language)
      navigate(`/jobs/${res.job_id}`)
    } catch (err) {
      setError((err as Error).message)
      setSubmitting(false)
    }
  }

  return (
    <div className="animate-fade-in">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6 no-underline">
        <ArrowLeft className="h-3.5 w-3.5" /> Back
      </Link>
      <Card className="mx-auto max-w-lg">
        <CardHeader>
          <CardTitle className="text-xl">New Transcription</CardTitle>
          <CardDescription>Upload a meeting recording to transcribe and format</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-5">
            <FileDropzone onFile={setFile} file={file} />
            <div className="space-y-2">
              <Label>Title</Label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Meeting Date</Label>
                <Input type="date" value={date} onChange={(e) => handleDateChange(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>Language</Label>
                <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="">Auto-detect</option>
                  <option value="en">English</option>
                  <option value="ru">Russian</option>
                </Select>
              </div>
            </div>
            {error && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3">
                <p className="text-sm text-red-400">{error}</p>
              </div>
            )}
            <Button type="submit" size="lg" className="w-full" disabled={!file || submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {submitting ? "Uploading..." : "Start Processing"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
