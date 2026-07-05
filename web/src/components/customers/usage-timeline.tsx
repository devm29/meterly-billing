"use client"

import { BarChart3 } from "lucide-react"
import { useId, useState } from "react"

import { UsageChart } from "@/components/charts/usage-chart"
import { Segmented } from "@/components/common/segmented"
import { SectionCard } from "@/components/common/section-card"
import { EmptyState, InlineError } from "@/components/common/states"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useCustomerUsage, useMetrics } from "@/lib/api/hooks"
import { formatNumber } from "@/lib/format"
import { pickDefaultMetric } from "@/lib/metrics"

const ranges = [
  { value: "1", label: "24H" },
  { value: "7", label: "7D" },
  { value: "30", label: "30D" },
  { value: "90", label: "90D" },
] as const
type Range = (typeof ranges)[number]["value"]

export function UsageTimeline({ customerId }: { customerId: string }) {
  const metrics = useMetrics()
  const [metric, setMetric] = useState<string | undefined>(undefined)
  const [range, setRange] = useState<Range>("30")
  const selected = metric ?? (metrics.data ? pickDefaultMetric(metrics.data)?.code : undefined)
  const days = Number(range)
  const usage = useCustomerUsage(customerId, selected, days, days === 1 ? "hour" : "day")
  const selectId = useId()
  const items = (metrics.data ?? []).map((m) => ({ value: m.code, label: m.name }))

  return (
    <SectionCard
      title="Usage timeline"
      description={
        usage.data
          ? `${formatNumber(usage.data.total)} ${usage.data.metric.unit} · ${usage.data.metric.aggregation.replace("_", " ")}`
          : "Metered usage from hourly rollups"
      }
      action={
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={selectId} className="sr-only">
            Metric
          </label>
          <Select items={items} value={selected ?? null} onValueChange={(next) => next && setMetric(next)}>
            <SelectTrigger id={selectId} className="h-8 min-w-40 rounded-lg text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {items.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Segmented label="Time range" value={range} options={ranges} onChange={setRange} />
        </div>
      }
    >
      {metrics.error || usage.error ? (
        <InlineError
          error={metrics.error ?? usage.error ?? new Error("Unknown error")}
          retry={() => void (metrics.error ? metrics.refetch() : usage.refetch())}
        />
      ) : metrics.data && metrics.data.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No billable metrics"
          description="Usage appears once a metric is defined for this customer’s events."
        />
      ) : usage.data ? (
        <UsageChart usage={usage.data} />
      ) : (
        <Skeleton className="h-[260px] w-full" />
      )}
    </SectionCard>
  )
}
