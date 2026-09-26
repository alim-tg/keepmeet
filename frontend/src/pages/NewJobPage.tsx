import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { FileDropzone } from "@/components/FileDropzone"
import { createJob, createJobFromLink } from "@/api/jobs"
import { ArrowLeft, Link2, Loader2, Sparkles } from "lucide-react"
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
  const [numSpeakers, setNumSpeakers] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const [link, setLink] = useState("")
  const [linkSubmitting, setLinkSubmitting] = useState(false)
  const [linkError, setLinkError] = useState("")

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
      const res = await createJob(file, title, date, language, numSpeakers ? parseInt(numSpeakers) : undefined)
      navigate(`/jobs/${res.job_id}`)
    } catch (err) {
      setError((err as Error).message)
      setSubmitting(false)
    }
  }

  const handleLinkSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!link.trim()) return
    setLinkSubmitting(true)
    setLinkError("")
    try {
      const res = await createJobFromLink(link.trim(), "", "", language)
      navigate(`/jobs/${res.job_id}`)
    } catch (err) {
      setLinkError((err as Error).message)
      setLinkSubmitting(false)
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
            <div className="space-y-2">
              <Label>Number of Speakers</Label>
              <Input
                type="number"
                min="1"
                max="20"
                placeholder="Auto-detect"
                value={numSpeakers}
                onChange={(e) => setNumSpeakers(e.target.value)}
              />
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
      <Card className="mx-auto max-w-lg mt-6">
        <CardHeader>
          <CardTitle className="text-xl">From Teams Link</CardTitle>
          <CardDescription>Paste a Teams meeting recap or SharePoint recording link — the file is fetched from OneDrive automatically</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLinkSubmit} className="space-y-4">
            <Input
              placeholder="https://teams.microsoft.com/l/meetingrecap?... or SharePoint link"
              value={link}
              onChange={(e) => setLink(e.target.value)}
            />
            {linkError && (
              <div className="rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-3">
                <p className="text-sm text-red-400">{linkError}</p>
              </div>
            )}
            <Button type="submit" variant="secondary" className="w-full" disabled={!link.trim() || linkSubmitting}>
              {linkSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Link2 className="h-4 w-4" />
              )}
              {linkSubmitting ? "Fetching..." : "Fetch & Process"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
