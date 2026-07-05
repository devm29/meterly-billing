import { cn } from "@/lib/utils"

const tones = {
  green: "bg-success/15 text-success-foreground",
  blue: "bg-primary/12 text-primary",
  orange: "bg-warning/15 text-warning-foreground",
  gray: "bg-muted-foreground/12 text-muted-foreground",
  red: "bg-destructive/12 text-destructive",
} as const

const statusTone: Record<string, keyof typeof tones> = {
  active: "green",
  finalized: "green",
  trialing: "blue",
  draft: "orange",
  scheduled: "blue",
  canceled: "gray",
  none: "gray",
  void: "red",
}

const labels: Record<string, string> = {
  none: "No plan",
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = tones[statusTone[status] ?? "gray"]
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1.5 rounded-full px-2 text-[11px] font-medium capitalize",
        tone,
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {labels[status] ?? status}
    </span>
  )
}
