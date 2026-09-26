import { useNavigate } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import type { JobSummary } from "@/api/jobs"
import { ChevronRight, Loader2 } from "lucide-react"

const PUBLISH_LABEL: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  published: { label: "published", variant: "default" },
  awaiting_review: { label: "needs review", variant: "secondary" },
  publish_failed: { label: "publish failed", variant: "destructive" },
}

const SOURCE_LABEL: Record<string, string> = {
  "teams-auto": "Teams · OneDrive",
  "teams-chat": "Teams · chat",
  "teams-shared": "Teams · shared",
  "teams-link": "Teams link",
  "local-recorder": "Recorded on this PC",
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  completed: "default",
  processing: "secondary",
  pending: "outline",
  failed: "destructive",
  reformatting: "secondary",
}

export function JobTable({ jobs }: { jobs: JobSummary[] }) {
  const navigate = useNavigate()

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 animate-fade-in">
        <div className="h-16 w-16 rounded-2xl bg-white/[0.04] flex items-center justify-center mb-4">
          <span className="text-2xl">🎙</span>
        </div>
        <p className="text-muted-foreground text-sm">No transcriptions yet</p>
        <p className="text-muted-foreground/60 text-xs mt-1">Upload an audio file to get started</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {jobs.map((job, i) => (
        <div
          key={job.job_id}
          className="group flex items-center gap-4 rounded-xl border border-white/[0.04] bg-white/[0.02] px-5 py-4 cursor-pointer hover:bg-white/[0.04] hover:border-white/[0.08] transition-all duration-200 animate-fade-in"
          style={{ animationDelay: `${i * 50}ms` }}
          onClick={() => navigate(`/jobs/${job.job_id}`)}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium truncate">{job.title}</span>
              <Badge variant={STATUS_VARIANT[job.status] ?? "outline"}>
                {job.status === "processing" && <Loader2 className="h-3 w-3 animate-spin mr-1" />}
                {job.status}
              </Badge>
              {job.status === "completed" && job.publish_status && PUBLISH_LABEL[job.publish_status] && (
                <Badge variant={PUBLISH_LABEL[job.publish_status].variant}>
                  {PUBLISH_LABEL[job.publish_status].label}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1">
              <span className="text-xs text-muted-foreground">{job.meeting_date}</span>
              {job.language && <span className="text-xs text-muted-foreground/60">{job.language}</span>}
              {job.source && SOURCE_LABEL[job.source] && (
                <span className="text-xs text-muted-foreground/60">{SOURCE_LABEL[job.source]}</span>
              )}
            </div>
          </div>
          <ChevronRight className="h-4 w-4 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
        </div>
      ))}
    </div>
  )
}
