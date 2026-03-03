import { cn } from "@/lib/utils"

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl bg-gradient-to-r from-white/[0.04] via-white/[0.08] to-white/[0.04] animate-shimmer",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }
