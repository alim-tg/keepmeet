import { useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Toggle } from "@/components/Toggle"
import { usePolling } from "@/hooks/usePolling"
import {
  getRecorderStatus,
  startRecording,
  stopRecording,
  type LocalRecorderSettings,
  type RecorderStatus,
} from "@/api/settings"
import { Circle, Loader2, MonitorSpeaker, Square } from "lucide-react"

function elapsed(since: string | null, now: number) {
  if (!since) return "0:00"
  const secs = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000))
  const m = Math.floor(secs / 60)
  const s = String(secs % 60).padStart(2, "0")
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${s}` : `${m}:${s}`
}

interface LocalRecorderCardProps {
  settings: LocalRecorderSettings
  onChange: (settings: LocalRecorderSettings) => void
  myName: string
  onMyNameChange: (name: string) => void
}

export function LocalRecorderCard({ settings, onChange, myName, onMyNameChange }: LocalRecorderCardProps) {
  const navigate = useNavigate()
  const [status, setStatus] = useState<RecorderStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const version = useRef(0)

  const refresh = () => {
    const requested = ++version.current
    return getRecorderStatus().then((s) => {
      if (requested === version.current) setStatus(s)
    })
  }

  usePolling(() => {
    refresh().catch(() => {})
    setNow(Date.now())
  }, 1000, true)

  const handleStart = async () => {
    setBusy(true)
    try {
      version.current++
      setStatus(await startRecording())
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleStop = async () => {
    setBusy(true)
    try {
      version.current++
      const res = await stopRecording()
      await refresh()
      if (res.job_id) {
        toast.success("Recording saved, processing started")
        navigate(`/jobs/${res.job_id}`)
      } else {
        toast.message("Recording discarded")
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (status && !status.available) return null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <MonitorSpeaker className="h-4 w-4 text-primary" />
            Record from this PC
          </CardTitle>
          <Toggle checked={settings.enabled} onChange={(v) => onChange({ ...settings, enabled: v })} />
        </div>
        <CardDescription>
          Starts recording automatically when you join a Teams call and stops when you leave. Captures everyone you hear plus your microphone. No organizer or Microsoft setup needed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {status?.recording ? (
          <div className="flex items-center justify-between rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3">
            <div className="flex items-center gap-3">
              <span className="relative flex h-3 w-3">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
                <span className="relative inline-flex h-3 w-3 rounded-full bg-red-500" />
              </span>
              <div>
                <div className="text-sm font-medium">
                  Recording{status.meeting_name ? `: ${status.meeting_name}` : ""}
                  <span className="ml-2 font-mono text-muted-foreground">{elapsed(status.started_at, now)}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {status.mode === "auto" ? "Stops automatically when the call ends" : "Started manually. Click Stop when done."}
                </div>
              </div>
            </div>
            <Button variant="secondary" size="sm" onClick={handleStop} disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Square className="h-3.5 w-3.5" />}
              Stop
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-4 py-3">
            <div className="text-xs text-muted-foreground space-y-0.5">
              <div>
                Teams call: {status?.teams_in_call ? <span className="text-emerald-400">in progress</span> : "none"}
              </div>
              <div>
                {settings.enabled ? "Waiting for the next Teams call" : "Automatic recording is off"}
              </div>
            </div>
            <Button variant="secondary" size="sm" onClick={handleStart} disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Circle className="h-3.5 w-3.5 fill-red-500 text-red-500" />}
              Record now
            </Button>
          </div>
        )}
        {status?.mic_error && <p className="text-xs text-amber-300">Microphone not captured: {status.mic_error}</p>}
        {status?.last_error && <p className="text-xs text-muted-foreground">{status.last_error}</p>}
        <div className="space-y-2">
          <Label>Your name</Label>
          <Input value={myName} placeholder="e.g. Alex" onChange={(e) => onMyNameChange(e.target.value)} />
          <p className="text-xs text-muted-foreground">
            Everything picked up by your microphone is labeled with this name. Other people are recognized by their voices.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.06] px-4 py-2.5">
            <div>
              <div className="text-sm font-medium">Include my microphone</div>
              <div className="text-xs text-muted-foreground">Uses the Windows default mic</div>
            </div>
            <Toggle checked={settings.include_mic} onChange={(v) => onChange({ ...settings, include_mic: v })} />
          </div>
          <div className="space-y-2">
            <Label>Ignore calls shorter than (seconds)</Label>
            <Input
              type="number"
              min={0}
              value={settings.min_duration_seconds}
              onChange={(e) => onChange({ ...settings, min_duration_seconds: parseInt(e.target.value) || 0 })}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
