import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { usePolling } from "@/hooks/usePolling"
import { LocalRecorderCard } from "@/components/LocalRecorderCard"
import { ConfluenceSettingsCard } from "@/components/ConfluenceSettingsCard"
import { Toggle } from "@/components/Toggle"
import {
  getSettings,
  getTeamsStatus,
  pollNow,
  saveSettings,
  startTeamsLogin,
  type PublishMode,
  type Settings,
  type SourceSettings,
  type TeamsStatus,
} from "@/api/settings"
import { cn } from "@/lib/utils"
import { Bell, CheckCircle2, ExternalLink, Loader2, LogIn, Radio, RefreshCw, Save, Send, XCircle } from "lucide-react"

const SOURCES: { key: keyof SourceSettings; label: string; description: string }[] = [
  {
    key: "meeting_chats",
    label: "Meeting chats",
    description: "Picks up recordings posted in Teams meeting chats, including meetings organized by someone else. Needs Chat.Read.",
  },
  {
    key: "onedrive",
    label: "My OneDrive Recordings",
    description: "Meetings you recorded yourself end up in your own OneDrive.",
  },
  {
    key: "shared_with_me",
    label: "Shared with me",
    description: "A fallback that scans recording files shared with you. Less reliable.",
  },
]

const PUBLISH_MODES: { value: PublishMode; label: string; description: string }[] = [
  { value: "manual", label: "Manual review", description: "Notes wait here until you check the speakers and click Publish." },
  { value: "auto_if_matched", label: "Auto if all speakers matched", description: "Publishes automatically only when every speaker matched a voice profile. Otherwise waits for review." },
  { value: "auto", label: "Auto-publish", description: "Publishes to Confluence as soon as the notes are ready." },
]

function StatusLine({ ok, children }: { ok: boolean | null; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      {ok ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <XCircle className="h-4 w-4 text-red-400" />}
      <span className={ok ? "text-foreground" : "text-muted-foreground"}>{children}</span>
    </div>
  )
}

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [saved, setSaved] = useState<Settings | null>(null)
  const [status, setStatus] = useState<TeamsStatus | null>(null)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [loggingIn, setLoggingIn] = useState(false)

  useEffect(() => {
    getSettings().then((s) => { setSettings(s); setSaved(s) }).catch((e) => toast.error((e as Error).message))
  }, [])

  const loginPending = status?.login?.state === "pending"
  usePolling(() => {
    getTeamsStatus().then(setStatus).catch(() => {})
  }, loginPending ? 2000 : 10000, true)

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev))
    setDirty(true)
  }

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    try {
      const result = await saveSettings(settings)
      setSettings(result)
      setSaved(result)
      setDirty(false)
      toast.success("Settings saved")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleLogin = async () => {
    setLoggingIn(true)
    try {
      await startTeamsLogin()
      setStatus(await getTeamsStatus())
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setLoggingIn(false)
    }
  }

  const handlePoll = async () => {
    await pollNow()
    toast.success("Checking for new recordings...")
    setTimeout(() => getTeamsStatus().then(setStatus).catch(() => {}), 3000)
  }

  if (!settings) {
    return <Loader2 className="mx-auto mt-20 h-6 w-6 animate-spin text-muted-foreground" />
  }

  const needsChatAccess = settings.sources.meeting_chats && status?.signed_in && status.chat_access === false

  return (
    <div className="mx-auto max-w-2xl space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground mt-1">Record Teams meetings automatically and turn them into notes</p>
        </div>
        <Button onClick={handleSave} disabled={!dirty || saving}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save
        </Button>
      </div>

      <LocalRecorderCard
        settings={settings.local_recorder}
        onChange={(v) => update("local_recorder", v)}
        myName={settings.my_name}
        onMyNameChange={(v) => update("my_name", v)}
      />

      <ConfluenceSettingsCard
        targetUrl={settings.confluence.target_url}
        savedTargetUrl={saved?.confluence.target_url ?? ""}
        onTargetUrlChange={(v) => update("confluence", { target_url: v })}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LogIn className="h-4 w-4 text-primary" />
            Microsoft account
          </CardTitle>
          <CardDescription>Read-only access to your recordings and meeting chats</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {status && !status.configured && (
            <p className="text-sm text-amber-300">GRAPH_CLIENT_ID and GRAPH_TENANT_ID aren't set in .env. See docs/teams-setup.md.</p>
          )}
          {status?.configured && (
            <>
              <StatusLine ok={status.signed_in}>
                {status.signed_in ? `Signed in as ${status.account}` : "Not signed in"}
              </StatusLine>
              {status.signed_in && (
                <StatusLine ok={status.chat_access !== false}>
                  {status.chat_access === false ? "No meeting chat access (sign in again to grant Chat.Read)" : "Meeting chat access"}
                </StatusLine>
              )}
            </>
          )}
          {loginPending && status?.login.user_code && (
            <div className="rounded-lg border border-primary/20 bg-primary/10 px-4 py-3 space-y-2">
              <p className="text-sm">Open the link below and enter this code:</p>
              <div className="flex items-center gap-3">
                <code className="rounded-md bg-black/40 px-3 py-1.5 text-lg font-mono tracking-widest">{status.login.user_code}</code>
                <a
                  href={status.login.verification_uri}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
                >
                  {status.login.verification_uri} <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
              <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" /> Waiting for you to finish signing in...
              </p>
            </div>
          )}
          {status?.login.state === "failed" && <p className="text-sm text-red-400">{status.login.error}</p>}
          {status?.configured && !loginPending && (!status.signed_in || needsChatAccess) && (
            <Button variant="secondary" onClick={handleLogin} disabled={loggingIn}>
              {loggingIn ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
              {status.signed_in ? "Sign in again" : "Sign in with Microsoft"}
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Radio className="h-4 w-4 text-primary" />
              Recording sources
            </CardTitle>
            <Toggle checked={settings.watcher_enabled} onChange={(v) => update("watcher_enabled", v)} />
          </div>
          <CardDescription>Where keepmeet looks for new recordings while the server is running</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {SOURCES.map((s) => (
            <div key={s.key} className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{s.label}</span>
                  {status?.sources[s.key]?.last_error && <Badge variant="destructive">error</Badge>}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{s.description}</p>
                {status?.sources[s.key]?.last_error && (
                  <p className="text-xs text-red-400 mt-1 break-all">{status.sources[s.key].last_error}</p>
                )}
              </div>
              <Toggle
                checked={settings.sources[s.key]}
                disabled={!settings.watcher_enabled}
                onChange={(v) => update("sources", { ...settings.sources, [s.key]: v })}
              />
            </div>
          ))}
          <div className="grid grid-cols-2 gap-4 pt-2">
            <div className="space-y-2">
              <Label>Meeting name filter</Label>
              <Input
                value={settings.meeting_filter}
                placeholder="All meetings"
                onChange={(e) => update("meeting_filter", e.target.value)}
              />
              <p className="text-xs text-muted-foreground">e.g. "Daily". Leave empty to process every meeting.</p>
            </div>
            <div className="space-y-2">
              <Label>Check every (seconds)</Label>
              <Input
                type="number"
                min={30}
                value={settings.poll_interval_seconds}
                onChange={(e) => update("poll_interval_seconds", parseInt(e.target.value) || 30)}
              />
            </div>
          </div>
          {settings.sources.onedrive && (
            <div className="space-y-2">
              <Label>OneDrive folder</Label>
              <Input value={settings.recordings_folder} onChange={(e) => update("recordings_folder", e.target.value)} />
            </div>
          )}
          <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-4 py-3">
            <div className="text-xs text-muted-foreground space-y-0.5">
              <div>Last check: {status?.last_poll_at ?? "never"}</div>
              <div>Recordings picked up this session: {status?.ingested_count ?? 0}</div>
            </div>
            <Button variant="secondary" size="sm" onClick={handlePoll} disabled={!status?.signed_in}>
              <RefreshCw className="h-3.5 w-3.5" />
              Check now
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Send className="h-4 w-4 text-primary" />
            After processing
          </CardTitle>
          <CardDescription>What happens to automatic recordings (from this PC or Teams) once the notes are ready</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {PUBLISH_MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => update("publish_mode", m.value)}
              className={cn(
                "w-full text-left rounded-lg border px-4 py-3 transition-colors",
                settings.publish_mode === m.value
                  ? "border-primary/40 bg-primary/10"
                  : "border-white/[0.06] hover:bg-white/[0.03]"
              )}
            >
              <div className="text-sm font-medium">{m.label}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{m.description}</div>
            </button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center justify-between py-5">
          <div className="flex items-center gap-3">
            <Bell className="h-4 w-4 text-primary" />
            <div>
              <div className="text-sm font-medium">Windows notifications</div>
              <div className="text-xs text-muted-foreground">When a recording is found, its notes are ready or published, or something fails</div>
            </div>
          </div>
          <Toggle checked={settings.notifications} onChange={(v) => update("notifications", v)} />
        </CardContent>
      </Card>
    </div>
  )
}
