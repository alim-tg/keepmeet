import { useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { JobTable } from "@/components/JobTable"
import { Skeleton } from "@/components/ui/skeleton"
import { usePolling } from "@/hooks/usePolling"
import { listJobs, type JobSummary } from "@/api/jobs"
import { Plus } from "lucide-react"

export function JobListPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [loading, setLoading] = useState(true)

  const hasProcessing = jobs.some((j) => j.status === "processing" || j.status === "pending")

  usePolling(
    () => {
      listJobs()
        .then((data) => {
          setJobs(data)
          setLoading(false)
        })
        .catch(() => setLoading(false))
    },
    hasProcessing ? 5000 : 30000,
    true
  )

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-white to-white/60 bg-clip-text text-transparent">
            Transcriptions
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {jobs.length > 0 ? `${jobs.length} recording${jobs.length > 1 ? "s" : ""}` : "Upload audio to transcribe"}
          </p>
        </div>
        <Link to="/new">
          <Button size="lg">
            <Plus className="h-4 w-4" /> New
          </Button>
        </Link>
      </div>
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : (
        <JobTable jobs={jobs} />
      )}
    </div>
  )
}
