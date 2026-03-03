import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-3 py-0.5 text-xs font-medium tracking-wide transition-colors",
  {
    variants: {
      variant: {
        default: "bg-primary/15 text-primary border border-primary/20",
        secondary: "bg-amber-400/10 text-amber-300 border border-amber-400/20",
        destructive: "bg-red-500/10 text-red-400 border border-red-500/20",
        outline: "border border-white/10 text-muted-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
