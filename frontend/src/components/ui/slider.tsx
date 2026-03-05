import * as React from "react"
import { cn } from "@/lib/utils"

interface SliderProps {
  value: number
  max: number
  onChange: (value: number) => void
  className?: string
}

const Slider = React.forwardRef<HTMLDivElement, SliderProps>(
  ({ value, max, onChange, className }, ref) => {
    const trackRef = React.useRef<HTMLDivElement>(null)
    const dragging = React.useRef(false)

    const pct = max > 0 ? (value / max) * 100 : 0

    const calcValue = (e: React.MouseEvent | MouseEvent) => {
      const track = trackRef.current
      if (!track) return
      const rect = track.getBoundingClientRect()
      const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width))
      onChange((x / rect.width) * max)
    }

    React.useEffect(() => {
      const onMove = (e: MouseEvent) => {
        if (dragging.current) calcValue(e)
      }
      const onUp = () => {
        dragging.current = false
      }
      window.addEventListener("mousemove", onMove)
      window.addEventListener("mouseup", onUp)
      return () => {
        window.removeEventListener("mousemove", onMove)
        window.removeEventListener("mouseup", onUp)
      }
    })

    return (
      <div
        ref={ref}
        className={cn("relative flex w-full touch-none select-none items-center group cursor-pointer", className)}
        onMouseDown={(e) => {
          dragging.current = true
          calcValue(e)
        }}
      >
        <div ref={trackRef} className="relative h-1.5 w-full rounded-full bg-white/[0.08] overflow-hidden">
          <div
            className="absolute h-full rounded-full bg-gradient-to-r from-[#a78bfa] to-[#6366f1] transition-[width] duration-75"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div
          className="absolute h-3.5 w-3.5 rounded-full bg-white shadow-md border-2 border-primary opacity-0 group-hover:opacity-100 transition-opacity duration-150 -translate-x-1/2"
          style={{ left: `${pct}%` }}
        />
      </div>
    )
  }
)
Slider.displayName = "Slider"

export { Slider }
