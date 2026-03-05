import { useState, useRef, useEffect, useImperativeHandle, forwardRef, useCallback } from "react"
import { Slider } from "@/components/ui/slider"
import { Play, Pause, Volume2 } from "lucide-react"

export interface AudioPlayerHandle {
  seekTo: (seconds: number) => void
}

interface AudioPlayerProps {
  src: string
  onTimeUpdate?: (time: number) => void
}

function fmtTime(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, "0")}`
}

export const AudioPlayer = forwardRef<AudioPlayerHandle, AudioPlayerProps>(
  ({ src, onTimeUpdate: onTimeUpdateProp }, ref) => {
    const audioRef = useRef<HTMLAudioElement>(null)
    const [playing, setPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [duration, setDuration] = useState(0)

    useImperativeHandle(ref, () => ({
      seekTo(seconds: number) {
        const el = audioRef.current
        if (!el) return
        el.currentTime = seconds
        setCurrentTime(seconds)
        if (el.paused) {
          el.play()
          setPlaying(true)
        }
      },
    }))

    const onTimeUpdate = useCallback(() => {
      if (audioRef.current) {
        const t = audioRef.current.currentTime
        setCurrentTime(t)
        onTimeUpdateProp?.(t)
      }
    }, [onTimeUpdateProp])

    const onLoaded = useCallback(() => {
      if (audioRef.current) setDuration(audioRef.current.duration || 0)
    }, [])

    const onEnded = useCallback(() => setPlaying(false), [])

    useEffect(() => {
      const el = audioRef.current
      if (!el) return
      el.addEventListener("timeupdate", onTimeUpdate)
      el.addEventListener("loadedmetadata", onLoaded)
      el.addEventListener("durationchange", onLoaded)
      el.addEventListener("ended", onEnded)
      return () => {
        el.removeEventListener("timeupdate", onTimeUpdate)
        el.removeEventListener("loadedmetadata", onLoaded)
        el.removeEventListener("durationchange", onLoaded)
        el.removeEventListener("ended", onEnded)
      }
    }, [onTimeUpdate, onLoaded, onEnded])

    const togglePlay = () => {
      const el = audioRef.current
      if (!el) return
      if (el.paused) {
        el.play()
        setPlaying(true)
      } else {
        el.pause()
        setPlaying(false)
      }
    }

    const handleSeek = (val: number) => {
      const el = audioRef.current
      if (!el) return
      el.currentTime = val
      setCurrentTime(val)
    }

    return (
      <div className="flex items-center gap-3">
        <audio ref={audioRef} src={src} preload="metadata" className="hidden" />
        <button
          onClick={togglePlay}
          className="h-9 w-9 rounded-full bg-gradient-to-r from-[#a78bfa] to-[#6366f1] flex items-center justify-center shrink-0 cursor-pointer border-none shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:brightness-110 active:scale-95 transition-all duration-150"
        >
          {playing ? <Pause className="h-4 w-4 text-white" /> : <Play className="h-4 w-4 text-white ml-0.5" />}
        </button>
        <span className="text-xs text-muted-foreground font-mono w-10 text-right shrink-0">
          {fmtTime(currentTime)}
        </span>
        <Slider value={currentTime} max={duration} onChange={handleSeek} className="flex-1" />
        <span className="text-xs text-muted-foreground font-mono w-10 shrink-0">
          {fmtTime(duration)}
        </span>
        <Volume2 className="h-4 w-4 text-muted-foreground shrink-0" />
      </div>
    )
  }
)
AudioPlayer.displayName = "AudioPlayer"
