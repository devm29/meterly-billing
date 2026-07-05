import type { ReactNode } from "react"

import { ThemeToggle } from "@/components/shell/theme-toggle"
import { SidebarTrigger } from "@/components/ui/sidebar"

export function Toolbar({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  return (
    <header className="material sticky top-0 z-30 flex h-13 items-center gap-2 border-b border-border/60 bg-background/72 px-4 backdrop-blur-xl backdrop-saturate-[1.8]">
      <SidebarTrigger className="-ml-1" aria-label="Toggle sidebar" />
      <div className="min-w-0 truncate text-[15px] font-semibold">{title}</div>
      <div className="ml-auto flex items-center gap-1">
        {actions}
        <ThemeToggle />
      </div>
    </header>
  )
}
