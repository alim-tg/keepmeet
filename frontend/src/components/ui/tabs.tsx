import * as React from "react"
import { cn } from "@/lib/utils"

interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
}

const TabsContext = React.createContext<TabsContextValue>({ value: "", onValueChange: () => {} })

function Tabs({ value, onValueChange, className, children, ...props }: {
  value: string
  onValueChange: (value: string) => void
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <TabsContext.Provider value={{ value, onValueChange }}>
      <div className={className} {...props}>{children}</div>
    </TabsContext.Provider>
  )
}

function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "inline-flex h-11 items-center gap-1 rounded-xl bg-white/[0.04] border border-white/[0.06] p-1 text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function TabsTrigger({ className, value, ...props }: { value: string } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = React.useContext(TabsContext)
  const isActive = ctx.value === value
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-lg px-4 py-1.5 text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:pointer-events-none disabled:opacity-40 cursor-pointer",
        isActive
          ? "bg-gradient-to-r from-primary/20 to-[#6366f1]/20 text-foreground shadow-sm border border-primary/20"
          : "hover:bg-white/[0.06] hover:text-foreground",
        className
      )}
      onClick={() => ctx.onValueChange(value)}
      {...props}
    />
  )
}

function TabsContent({ className, value, ...props }: { value: string } & React.HTMLAttributes<HTMLDivElement>) {
  const ctx = React.useContext(TabsContext)
  if (ctx.value !== value) return null
  return (
    <div
      className={cn("mt-3 animate-fade-in", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
