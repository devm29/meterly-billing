"use client"

import { Check, Minus, X } from "lucide-react"

import { SectionCard } from "@/components/common/section-card"
import { InlineError } from "@/components/common/states"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { useEntitlements } from "@/lib/api/hooks"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

export function EntitlementsCard({ customerId }: { customerId: string }) {
  const entitlements = useEntitlements(customerId)
  const items = entitlements.data?.entitlements

  return (
    <SectionCard title="Entitlements" description="Live from hourly rollups, cached for 15 seconds" flush>
      {entitlements.error ? (
        <InlineError error={entitlements.error} retry={() => void entitlements.refetch()} />
      ) : !items ? (
        <div className="space-y-3 px-5">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : items.length === 0 ? (
        <p className="px-5 pb-5 text-[13px] text-muted-foreground">
          No active subscription, so no features are unlocked.
        </p>
      ) : (
        <ul className="divide-y divide-border/70">
          {items.map((e) => {
            const limit = e.limit ? Number(e.limit) : null
            const used = e.used ? Number(e.used) : null
            const ratio = limit && used !== null ? Math.min(used / limit, 1) : null
            return (
              <li key={e.feature} className="px-5 py-3">
                <div className="flex items-center gap-3">
                  <span
                    className={cn(
                      "grid size-5 place-items-center rounded-full",
                      e.allowed
                        ? "bg-success/15 text-success-foreground"
                        : "bg-destructive/12 text-destructive",
                    )}
                  >
                    {e.allowed ? (
                      <Check className="size-3" strokeWidth={2.5} aria-hidden />
                    ) : (
                      <X className="size-3" strokeWidth={2.5} aria-hidden />
                    )}
                    <span className="sr-only">{e.allowed ? "Allowed:" : "Blocked:"}</span>
                  </span>
                  <span className="flex-1 text-[14px] font-medium">{e.name}</span>
                  <span className="text-[13px] text-muted-foreground tabular-nums">
                    {limit !== null && used !== null ? (
                      <>
                        {formatNumber(used, true)} of {formatNumber(limit, true)}
                      </>
                    ) : e.metric_code && used === null ? (
                      "Unlimited"
                    ) : (
                      <span className="inline-flex items-center gap-1">
                        <Minus className="size-3" aria-hidden /> Included
                      </span>
                    )}
                  </span>
                </div>
                {ratio !== null ? (
                  <Progress
                    value={ratio * 100}
                    aria-label={`${e.name} quota used`}
                    className={cn(
                      "mt-2.5 ml-8 h-1.5 w-auto",
                      ratio > 0.9 && "[&_[data-slot=progress-indicator]]:bg-warning",
                    )}
                  />
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </SectionCard>
  )
}
