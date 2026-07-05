"use client"

import { BarChart3 } from "lucide-react"
import { useState } from "react"

import { UsageChart } from "@/components/charts/usage-chart"
import { Segmented } from "@/components/common/segmented"
import { SectionCard } from "@/components/common/section-card"
import { EmptyState, ErrorState, InlineError } from "@/components/common/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useMetricUsage, useMetrics } from "@/lib/api/hooks"
import { pickDefaultMetric } from "@/lib/metrics"
import type { Metric } from "@/lib/api/schemas"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

const ranges = [
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "90", label: "90D" },
] as const

const aggregationLabel: Record<Metric["aggregation"], string> = {
  count: "COUNT",
  sum: "SUM",
  max: "MAX",
  unique_count: "UNIQUE",
  latest: "LATEST",
}

export function UsageView() {
  const metrics = useMetrics()
  const [chosen, setChosen] = useState<string | null>(null)
  const selected = chosen ?? (metrics.data ? pickDefaultMetric(metrics.data)?.code : undefined)
  const [range, setRange] = useState<(typeof ranges)[number]["value"]>("30")
  const usage = useMetricUsage(selected, Number(range))

  if (metrics.error) return <ErrorState error={metrics.error} retry={() => void metrics.refetch()} />

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
      <nav aria-label="Billable metrics" className="space-y-2">
        <h2 className="px-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Billable metrics
        </h2>
        <ul className="divide-y divide-border/70 overflow-hidden rounded-xl bg-card shadow-xs ring-1 ring-border/70">
          {(metrics.data ?? []).map((metric) => (
            <li key={metric.code}>
              <button
                type="button"
                onClick={() => setChosen(metric.code)}
                aria-current={metric.code === selected}
                className={cn(
                  "w-full px-4 py-3 text-left transition-colors hover:bg-accent/50 focus-visible:bg-accent/60 focus-visible:outline-none",
                  metric.code === selected && "bg-primary/8",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[14px] font-medium">{metric.name}</span>
                  <span className="rounded-md bg-secondary px-1.5 py-0.5 font-mono text-[10px] font-medium text-muted-foreground">
                    {aggregationLabel[metric.aggregation]}
                  </span>
                </div>
                <div className="mt-0.5 font-mono text-[11px] break-words text-muted-foreground">
                  {metric.event_code}
                  {metric.field ? ` → ${metric.field}` : ""}
                  {metric.group_by.length ? ` · by ${metric.group_by.join(", ")}` : ""}
                </div>
              </button>
            </li>
          ))}
          {!metrics.data
            ? Array.from({ length: 5 }, (_, i) => (
                <li key={i} className="px-4 py-3">
                  <Skeleton className="h-9 w-full" />
                </li>
              ))
            : null}
        </ul>
      </nav>
      <SectionCard
        className="min-w-0 self-start"
        title={usage.data?.metric.name ?? "Usage"}
        description={
          usage.data
            ? `${formatNumber(usage.data.total, true)} ${usage.data.metric.unit} across all customers`
            : "Across all customers"
        }
        action={<Segmented label="Time range" value={range} options={ranges} onChange={setRange} />}
      >
        {usage.error ? (
          <InlineError error={usage.error} retry={() => void usage.refetch()} />
        ) : metrics.data && metrics.data.length === 0 ? (
          <EmptyState
            icon={BarChart3}
            title="No billable metrics"
            description="Create a metric with POST /v1/metrics; existing events are backfilled."
          />
        ) : usage.data ? (
          <UsageChart usage={usage.data} height={340} />
        ) : (
          <Skeleton className="h-[340px] w-full" />
        )}
      </SectionCard>
    </div>
  )
}
