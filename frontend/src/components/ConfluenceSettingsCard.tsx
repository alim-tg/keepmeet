import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  connectConfluence,
  disconnectConfluence,
  getConfluenceStatus,
  type ConfluenceStatus,
} from "@/api/confluence"
import { CheckCircle2, ExternalLink, Globe, Loader2, LogOut } from "lucide-react"

interface ConfluenceSettingsCardProps {
  targetUrl: string
  onTargetUrlChange: (url: string) => void
  savedTargetUrl: string
}

export function ConfluenceSettingsCard({ targetUrl, onTargetUrlChange, savedTargetUrl }: ConfluenceSettingsCardProps) {
  const [status, setStatus] = useState<ConfluenceStatus | null>(null)
  const [email, setEmail] = useState("")
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getConfluenceStatus().then(setStatus).catch(() => {})
  }, [savedTargetUrl])

  const handleConnect = async () => {
    setBusy(true)
    try {
      setStatus(await connectConfluence(email.trim(), token.trim()))
      setToken("")
      toast.success("Confluence connected")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const handleDisconnect = async () => {
    setBusy(true)
    try {
      setStatus(await disconnectConfluence())
    } finally {
      setBusy(false)
    }
  }

  const target = status?.target

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-primary" />
          Confluence
        </CardTitle>
        <CardDescription>Where meeting notes are published. Connect once, then publishing just works.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label>Publish folder</Label>
          <Input
            value={targetUrl}
            placeholder="https://site.atlassian.net/wiki/spaces/KEY/folder/123/Name"
            onChange={(e) => onTargetUrlChange(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Paste the link to the Confluence folder or parent page.
            {target && targetUrl === savedTargetUrl && ` Space ${target.space_key}${target.parent_name ? `, folder "${target.parent_name}"` : ""}.`}
          </p>
        </div>

        {status?.connected ? (
          <div className="flex items-center justify-between rounded-lg bg-white/[0.03] px-4 py-3">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              Connected as {status.user?.name ?? status.user?.email}
            </div>
            <Button variant="secondary" size="sm" onClick={handleDisconnect} disabled={busy}>
              <LogOut className="h-3.5 w-3.5" />
              Disconnect
            </Button>
          </div>
        ) : (
          <div className="space-y-3 rounded-lg border border-white/[0.06] p-4">
            <p className="text-xs text-muted-foreground">
              Create an API token for your Atlassian account, then paste it here. It's stored encrypted on this PC.{" "}
              <a
                href="https://id.atlassian.com/manage-profile/security/api-tokens"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                Create token <ExternalLink className="h-3 w-3" />
              </a>
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label>Atlassian email</Label>
                <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
              </div>
              <div className="space-y-2">
                <Label>API token</Label>
                <Input type="password" value={token} onChange={(e) => setToken(e.target.value)} />
              </div>
            </div>
            {status?.error && <p className="text-xs text-red-400">{status.error}</p>}
            <Button
              variant="secondary"
              onClick={handleConnect}
              disabled={busy || !email.trim() || !token.trim() || targetUrl !== savedTargetUrl || !savedTargetUrl}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
              Connect
            </Button>
            {targetUrl !== savedTargetUrl && <p className="text-xs text-amber-300">Save the folder link first.</p>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
