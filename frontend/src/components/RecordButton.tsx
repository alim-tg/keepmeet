import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { startRecording, stopRecording, type RecorderStatus } from "@/api/settings"
import { Circle, Loader2, Square } from "lucide-react"

function elapsed(since: string | null) {
  if (!since) return "0:00"
  const secs = Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 1000))
  const m = Math.floor(secs / 60)
  const s = String(secs % 60).padStart(2, "0")
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`
}

interface RecordButtonProps {
  status: RecorderStatus | null
  onChange: (status: RecorderStatus | null) => void
}

export function RecordButton({ status, onChange }: RecordButtonProps) {
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)

  if (!status?.available) return null

  const handleStart = async () => {
    setBusy(true)
    try {
      onChange(await startRecording())
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleStop = async () => {
    setBusy(true)
    try {
      const res = await stopRecording()
      onChange({ ...status, recording: false, mode: null, started_at: null })
      if (res.job_id) {
        toast.success("Recording saved, processing started")
        navigate(`/jobs/${res.job_id}`)
      } else {
        toast.message("Recording discarded (too short)")
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (status.recording) {
    return (
      <div className="ml-auto flex items-center gap-2">
        <span className="inline-flex items-center gap-2 rounded-full border border-red-500/30 bg-red-500/10 px-3 py-1 text-xs font-semibold text-red-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
          REC {elapsed(status.started_at)}
          {status.meeting_name ? ` · ${status.meeting_name}` : ""}
          {status.mode === "auto" ? " · auto" : ""}
        </span>
        {status.mode === "auto" && (
          <button
            onClick={handleStart}
            disabled={busy}
            title="Keep recording until you click Stop, even if the call seems to end"
            className="rounded-full border border-white/10 px-3 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-white/[0.06] cursor-pointer bg-transparent"
          >
            Keep until I stop
          </button>
        )}
        <button
          onClick={handleStop}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-full bg-red-500 px-3 py-1 text-xs font-semibold text-white hover:bg-red-600 cursor-pointer border-none"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Square className="h-3 w-3 fill-white" />}
          Stop
        </button>
      </div>
    )
  }

  return (
    <button
      onClick={handleStart}
      disabled={busy}
      className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs font-semibold text-foreground hover:bg-white/[0.08] cursor-pointer"
    >
      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Circle className="h-3 w-3 fill-red-500 text-red-500" />}
      Record
    </button>
  )
}
