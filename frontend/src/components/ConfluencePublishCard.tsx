import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { getConfig, publishJob } from "@/api/jobs"
import { ExternalLink, Globe, Loader2 } from "lucide-react"

interface ConfluencePublishCardProps {
  jobId: string
  confluenceUrl: string | null
  onPublished: (url: string) => void
}

export function ConfluencePublishCard({ jobId, confluenceUrl, onPublished }: ConfluencePublishCardProps) {
  const [spaceKey, setSpaceKey] = useState("")
  const [parentPageId, setParentPageId] = useState("")
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    getConfig().then((cfg) => {
      setSpaceKey(cfg.confluence_space_key)
      setParentPageId(cfg.confluence_parent_page_id ?? "")
    }).catch(() => {})
  }, [])

  const handlePublish = async () => {
    setPublishing(true)
    setError("")
    try {
      const res = await publishJob(jobId, spaceKey, parentPageId)
      onPublished(res.confluence_url)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPublishing(false)
    }
  }

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
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Space Key</Label>
            <Input value={spaceKey} onChange={(e) => setSpaceKey(e.target.value)} placeholder="TEAM" />
          </div>
          <div className="space-y-2">
            <Label>Parent Page ID</Label>
            <Input value={parentPageId} onChange={(e) => setParentPageId(e.target.value)} placeholder="Optional" />
          </div>
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <Button onClick={handlePublish} disabled={publishing || !spaceKey}>
          {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
          {publishing ? "Publishing..." : "Publish"}
        </Button>
      </CardContent>
    </Card>
  )
}
