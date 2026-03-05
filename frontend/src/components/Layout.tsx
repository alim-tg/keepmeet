import type { ReactNode } from "react"
import { Link, useLocation } from "react-router-dom"
import { Mic } from "lucide-react"
import { cn } from "@/lib/utils"

export function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-[#09090b]/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-5xl items-center gap-8 px-6">
          <Link to="/" className="flex items-center gap-2.5 no-underline text-foreground group">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#a78bfa] to-[#6366f1] shadow-lg shadow-primary/20 group-hover:shadow-primary/40 transition-shadow">
              <Mic className="h-4 w-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight bg-gradient-to-r from-white to-white/70 bg-clip-text text-transparent">
              keepmeet
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            <Link
              to="/"
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors no-underline",
                pathname === "/" || pathname.startsWith("/jobs") || pathname === "/new"
                  ? "text-white bg-white/[0.08]"
                  : "text-muted-foreground hover:text-white hover:bg-white/[0.04]"
              )}
            >
              Transcriptions
            </Link>
            <Link
              to="/profiles"
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors no-underline",
                pathname === "/profiles"
                  ? "text-white bg-white/[0.08]"
                  : "text-muted-foreground hover:text-white hover:bg-white/[0.04]"
              )}
            >
              Profiles
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  )
}
