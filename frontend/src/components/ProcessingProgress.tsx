import { cn } from "@/lib/utils"
import { Loader2, Check, Mic, Users, UserCheck, FileText } from "lucide-react"

const STAGES = ["transcribing", "diarizing", "matching_speakers", "formatting"] as const

const STAGE_CONFIG: Record<string, { label: string; icon: typeof Mic }> = {
  transcribing: { label: "Transcribing audio", icon: Mic },
  diarizing: { label: "Identifying speakers", icon: Users },
  matching_speakers: { label: "Matching speakers", icon: UserCheck },
  formatting: { label: "Formatting notes", icon: FileText },
}

export function ProcessingProgress({ stage }: { stage: string | null }) {
  const currentIdx = stage ? STAGES.indexOf(stage as typeof STAGES[number]) : -1

  return (
    <div className="space-y-1 py-2">
      {STAGES.map((s, i) => {
        const isActive = i === currentIdx
        const isDone = i < currentIdx
        const config = STAGE_CONFIG[s]
        const Icon = config.icon
        return (
          <div
            key={s}
            className={cn(
              "flex items-center gap-4 rounded-xl px-4 py-3 transition-all duration-500",
              isActive && "bg-primary/[0.08] border border-primary/15",
              isDone && "opacity-60",
              !isDone && !isActive && "opacity-30"
            )}
          >
            <div
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-xl transition-all duration-500",
                isDone && "bg-emerald-500/15 text-emerald-400",
                isActive && "bg-primary/20 text-primary",
                !isDone && !isActive && "bg-white/[0.04] text-muted-foreground"
              )}
            >
              {isActive ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : isDone ? (
                <Check className="h-4 w-4" />
              ) : (
                <Icon className="h-4 w-4" />
              )}
            </div>
            <div className="flex-1">
              <span className={cn(
                "text-sm transition-colors",
                isActive && "font-medium text-foreground",
                isDone && "text-muted-foreground",
                !isDone && !isActive && "text-muted-foreground"
              )}>
                {config.label}
              </span>
            </div>
            {isActive && (
              <div className="flex gap-1">
                {[0, 1, 2].map((j) => (
                  <div
                    key={j}
                    className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse-glow"
                    style={{ animationDelay: `${j * 0.3}s` }}
                  />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
