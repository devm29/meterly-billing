import { ArrowDownRight, ArrowUpRight } from "lucide-react"
import type { ReactNode } from "react"

import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"

export function KpiTile({
  label,
  value,
  delta,
  hint,
  loading,
}: {
  label: string
  value: ReactNode
  delta?: number | null
  hint?: ReactNode
  loading?: boolean
}) {
  return (
    <Card className="gap-1 px-5">
      <div className="text-[13px] text-muted-foreground">{label}</div>
      {loading ? (
        <Skeleton className="mt-1 h-8 w-32" />
      ) : (
        <div className="text-[28px] leading-[34px] font-semibold tracking-tight tabular-nums">{value}</div>
      )}
      <div className="flex min-h-[18px] items-center gap-2 text-[13px]">
        {delta !== undefined && delta !== null && !loading ? (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 font-medium tabular-nums",
              delta >= 0 ? "text-success-foreground" : "text-destructive",
            )}
          >
            {delta >= 0 ? (
              <ArrowUpRight className="size-3.5" strokeWidth={2} aria-hidden />
            ) : (
              <ArrowDownRight className="size-3.5" strokeWidth={2} aria-hidden />
            )}
            {formatPercent(Math.abs(delta))}
            <span className="sr-only">{delta >= 0 ? "increase" : "decrease"}</span>
          </span>
        ) : null}
        {hint ? <span className="text-muted-foreground">{hint}</span> : null}
      </div>
    </Card>
  )
}
