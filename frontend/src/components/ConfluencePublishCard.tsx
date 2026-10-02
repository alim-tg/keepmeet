import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { publishJob } from "@/api/jobs"
import { getConfluenceStatus, type ConfluenceStatus } from "@/api/confluence"
import { ExternalLink, Folder, Globe, Loader2 } from "lucide-react"

interface ConfluencePublishCardProps {
  jobId: string
  defaultTitle: string
  confluenceUrl: string | null
  onPublished: (url: string, title: string) => void
}

export function ConfluencePublishCard({ jobId, defaultTitle, confluenceUrl, onPublished }: ConfluencePublishCardProps) {
  const [title, setTitle] = useState(defaultTitle)
  const [status, setStatus] = useState<ConfluenceStatus | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    getConfluenceStatus().then(setStatus).catch(() => {})
  }, [])

  const handlePublish = async () => {
    setPublishing(true)
    setError("")
    try {
      const res = await publishJob(jobId, title.trim())
      onPublished(res.confluence_url, res.title)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPublishing(false)
    }
  }

  const target = status?.target
  const ready = status?.connected && target

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-primary" />
          Confluence
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {confluenceUrl && (
          <a
            href={confluenceUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-3 py-2 text-sm text-emerald-400 hover:bg-emerald-500/15 transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            View published page
          </a>
        )}
        {status && !ready && (
          <div className="rounded-lg border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-300">
            {status.error ?? "Confluence isn't connected yet."}{" "}
            <Link to="/settings" className="underline">Open Settings</Link> to connect your account.
          </div>
        )}
        <div className="space-y-2">
          <Label>Page title</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          <p className="text-xs text-muted-foreground">
            Generated from the meeting name and date. Edit it if you like. Publishing again with the same title updates that page.
          </p>
        </div>
        {target && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Folder className="h-3.5 w-3.5" />
            Publishes to {target.space_key}
            {target.parent_name ? ` / ${target.parent_name}` : ""}
            {status?.user?.name ? ` as ${status.user.name}` : ""}
          </div>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        <Button onClick={handlePublish} disabled={publishing || !title.trim() || !ready}>
          {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
          {publishing ? "Publishing..." : confluenceUrl ? "Publish again" : "Publish"}
        </Button>
      </CardContent>
    </Card>
  )
}
