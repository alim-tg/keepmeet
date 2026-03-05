import { useEffect, useRef } from "react"
import { cn } from "@/lib/utils"

const SPEAKER_COLORS = [
  "text-violet-400",
  "text-sky-400",
  "text-emerald-400",
  "text-amber-400",
  "text-rose-400",
  "text-cyan-400",
  "text-fuchsia-400",
  "text-lime-400",
]

const SPEAKER_BG = [
  "bg-violet-400/10",
  "bg-sky-400/10",
  "bg-emerald-400/10",
  "bg-amber-400/10",
  "bg-rose-400/10",
  "bg-cyan-400/10",
  "bg-fuchsia-400/10",
  "bg-lime-400/10",
]

function hashSpeakerIndex(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0
  return Math.abs(h) % SPEAKER_COLORS.length
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, "0")}`
}

interface Segment {
  start?: number
  end?: number
  text?: string
  speaker?: string
}

interface TranscriptViewProps {
  segments: Segment[]
  speakerMap: Record<string, string>
  currentTime?: number
  onSeek: (seconds: number) => void
}

export function TranscriptView({ segments, speakerMap, currentTime, onSeek }: TranscriptViewProps) {
  const activeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }
  }, [currentTime])

  if (!segments || segments.length === 0) {
    return <p className="text-muted-foreground">No transcript available</p>
  }

  const colorCache: Record<string, number> = {}
  const getIndex = (id: string) => {
    if (!(id in colorCache)) colorCache[id] = hashSpeakerIndex(id)
    return colorCache[id]
  }

  return (
    <div className="space-y-3 max-h-[600px] overflow-y-auto pr-2">
      {segments.map((seg, i) => {
        const speakerId = seg.speaker || "UNKNOWN"
        const name = speakerMap[speakerId] || speakerId
        const idx = getIndex(speakerId)
        const start = seg.start ?? 0
        const end = seg.end ?? 0
        const text = (seg.text || "").trim()
        if (!text) return null

        const isActive = currentTime !== undefined && currentTime >= start && currentTime < end

        return (
          <div
            key={i}
            ref={isActive ? activeRef : undefined}
            className={cn(
              "group flex gap-3 rounded-lg px-2 py-1.5 transition-colors duration-300",
              isActive && "bg-primary/[0.08] ring-1 ring-primary/20"
            )}
          >
            <button
              onClick={() => onSeek(start)}
              className={cn(
                "shrink-0 mt-0.5 px-2 py-0.5 rounded text-xs font-mono cursor-pointer border-none transition-all duration-150 hover:brightness-125",
                SPEAKER_BG[idx]
              )}
              title="Seek to this position"
            >
              <span className="text-muted-foreground">{fmtTime(start)}</span>
            </button>
            <div className="min-w-0">
              <span className={`text-xs font-semibold ${SPEAKER_COLORS[idx]}`}>{name}</span>
              <span className="text-xs text-muted-foreground/50 ml-2">{fmtTime(start)} – {fmtTime(end)}</span>
              <p className={cn(
                "text-sm leading-relaxed mt-0.5 mb-0 transition-colors duration-300",
                isActive ? "text-foreground" : "text-muted-foreground"
              )}>{text}</p>
            </div>
          </div>
        )
      })}
    </div>
  )
}
