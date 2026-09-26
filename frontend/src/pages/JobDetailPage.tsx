import { useState, useCallback, useRef } from "react"
import { toast } from "sonner"
import { useParams, useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { ProcessingProgress } from "@/components/ProcessingProgress"
import { MarkdownRenderer } from "@/components/MarkdownRenderer"
import { CopyButton } from "@/components/CopyButton"
import { SpeakerEditor } from "@/components/SpeakerEditor"
import { ConfluencePublishCard } from "@/components/ConfluencePublishCard"
import { AudioPlayer, type AudioPlayerHandle } from "@/components/AudioPlayer"
import { TranscriptView } from "@/components/TranscriptView"
import { usePolling } from "@/hooks/usePolling"
import {
  getJob,
  deleteJob,
  updateSpeakers,
  reformatJob,
  type JobDetail,
} from "@/api/jobs"
import { AlertCircle, Trash2, ArrowLeft, Calendar, Languages } from "lucide-react"

export function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<JobDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState("notes")
  const [saving, setSaving] = useState(false)
  const [reformatting, setReformatting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [audioTime, setAudioTime] = useState(0)
  const audioRef = useRef<AudioPlayerHandle>(null)

  const isProcessing = job?.status === "processing" || job?.status === "pending"

  usePolling(
    useCallback(() => {
      if (!id) return
      getJob(id)
        .then((data) => {
          setJob(data)
          setLoading(false)
        })
        .catch(() => setLoading(false))
    }, [id]),
    isProcessing ? 2000 : 60000,
    true
  )

  const handleDelete = async () => {
    if (!id || !confirm("Delete this job?")) return
    setDeleting(true)
    await deleteJob(id)
    navigate("/")
  }

  const handleSaveSpeakers = async (map: Record<string, string>) => {
    if (!id) return
    setSaving(true)
    try {
      const res = await updateSpeakers(id, map)
      setJob((prev) => prev ? { ...prev, speaker_map: map, raw_transcript: res.raw_transcript } : prev)
      const named = Object.entries(map).filter(([spk, name]) => name && name !== spk).length
      if (named) toast.success(`Names saved. keepmeet will recognize ${named === 1 ? "this voice" : `these ${named} voices`} next time.`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleReformat = async () => {
    if (!id) return
    setReformatting(true)
    try {
      const res = await reformatJob(id)
      setJob((prev) => prev ? { ...prev, formatted_notes: res.formatted_notes, status: "completed" } : prev)
      setTab("notes")
    } finally {
      setReformatting(false)
    }
  }

  const handlePublished = (url: string) => {
    setJob((prev) => prev ? { ...prev, confluence_url: url } : prev)
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-80 w-full" />
      </div>
    )
  }

  if (!job) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-muted-foreground">Job not found</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4 cursor-pointer bg-transparent border-none p-0"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back
        </button>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{job.title}</h1>
            <div className="flex items-center gap-4 mt-2">
              <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Calendar className="h-3.5 w-3.5" /> {job.meeting_date}
              </span>
              <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Languages className="h-3.5 w-3.5" /> {job.language ?? "auto"}
              </span>
            </div>
          </div>
          <Badge variant={job.status === "failed" ? "destructive" : job.status === "completed" ? "default" : "secondary"}>
            {job.status}
          </Badge>
        </div>
      </div>

      <Card>
        <CardContent className="py-4">
          <AudioPlayer ref={audioRef} src={`/api/jobs/${job.job_id}/audio`} onTimeUpdate={setAudioTime} />
        </CardContent>
      </Card>

      {isProcessing && (
        <Card>
          <CardHeader>
            <CardTitle>Processing your recording</CardTitle>
          </CardHeader>
          <CardContent>
            <ProcessingProgress stage={job.stage} />
          </CardContent>
        </Card>
      )}

      {job.status === "failed" && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Processing failed</AlertTitle>
          <AlertDescription>{job.error}</AlertDescription>
        </Alert>
      )}

      {job.status === "completed" && job.publish_status === "publish_failed" && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Auto-publish failed</AlertTitle>
          <AlertDescription>{job.publish_error}</AlertDescription>
        </Alert>
      )}

      {job.status === "completed" && (
        <>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="notes">Formatted Notes</TabsTrigger>
              <TabsTrigger value="transcript">Raw Transcript</TabsTrigger>
              <TabsTrigger value="speakers">Speakers</TabsTrigger>
            </TabsList>

            <TabsContent value="notes">
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle>Meeting Notes</CardTitle>
                  {job.formatted_notes && <CopyButton text={job.formatted_notes} />}
                </CardHeader>
                <CardContent>
                  {job.formatted_notes ? (
                    <MarkdownRenderer content={job.formatted_notes} />
                  ) : (
                    <p className="text-muted-foreground">No formatted notes yet</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="transcript">
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle>Raw Transcript</CardTitle>
                  {job.raw_transcript && <CopyButton text={job.raw_transcript} />}
                </CardHeader>
                <CardContent>
                  {job.segments && job.segments.length > 0 ? (
                    <TranscriptView
                      segments={job.segments}
                      speakerMap={job.speaker_map}
                      currentTime={audioTime}
                      onSeek={(s) => audioRef.current?.seekTo(s)}
                    />
                  ) : job.raw_transcript ? (
                    <pre className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground font-mono">{job.raw_transcript}</pre>
                  ) : (
                    <p className="text-muted-foreground">No transcript available</p>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="speakers">
              <Card>
                <CardHeader>
                  <CardTitle>Speaker Mapping</CardTitle>
                </CardHeader>
                <CardContent>
                  <SpeakerEditor
                    job={job}
                    onSave={handleSaveSpeakers}
                    onReformat={handleReformat}
                    saving={saving}
                    reformatting={reformatting}
                  />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          <ConfluencePublishCard
            jobId={job.job_id}
            confluenceUrl={job.confluence_url}
            onPublished={handlePublished}
          />
        </>
      )}

      <div className="flex justify-end pt-2 pb-8">
        <Button variant="ghost" size="sm" onClick={handleDelete} disabled={deleting} className="text-muted-foreground hover:text-red-400">
          <Trash2 className="h-3.5 w-3.5" /> {deleting ? "Deleting..." : "Delete"}
        </Button>
      </div>
    </div>
  )
}
