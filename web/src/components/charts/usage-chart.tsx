"use client"

import { useId } from "react"
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import type { UsageSeries } from "@/lib/api/schemas"
import { formatHour, formatNumber, formatShortDay } from "@/lib/format"

const PALETTE = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)"] as const
const MAX_SERIES = 4

function slug(label: string, index: number): string {
  return `s${index}_${label.replace(/[^a-zA-Z0-9]/g, "")}`
}

export function UsageChart({ usage, height = 260 }: { usage: UsageSeries; height?: number }) {
  // Gradient ids are document-global; scope them so two charts never share one.
  const gradient = `g${useId().replace(/[^A-Za-z0-9]/g, "")}`
  const visible = usage.series.slice(0, MAX_SERIES - (usage.series.length > MAX_SERIES ? 1 : 0))
  const folded = usage.series.slice(visible.length)
  const labels = folded.length ? [...visible, "Other"] : visible
  const keys = labels.map(slug)

  const config: ChartConfig = Object.fromEntries(
    labels.map((label, i) => [
      keys[i] ?? label,
      { label: label === "total" ? usage.metric.name : label, color: PALETTE[i] ?? PALETTE[0] },
    ]),
  )
  const data = usage.points.map((point) => {
    const row: Record<string, number | string> = { t: point.t }
    visible.forEach((label, i) => {
      row[keys[i] ?? label] = Number(point.values[label] ?? 0)
    })
    if (folded.length) {
      row[keys[visible.length] ?? "other"] = folded.reduce(
        (sum, label) => sum + Number(point.values[label] ?? 0),
        0,
      )
    }
    return row
  })
  const tick = usage.granularity === "hour" ? formatHour : formatShortDay
  const stacked = usage.metric.aggregation === "sum" || usage.metric.aggregation === "count"

  return (
    <figure>
      <ChartContainer config={config} className="aspect-auto w-full" style={{ height }}>
        <AreaChart data={data} margin={{ left: 4, right: 8, top: 8 }}>
          <defs>
            {keys.map((key) => (
              <linearGradient key={key} id={`${gradient}-${key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.2} />
                <stop offset="100%" stopColor={`var(--color-${key})`} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            dataKey="t"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            minTickGap={28}
            tickFormatter={(value: string) => tick(value)}
            className="text-[11px]"
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={48}
            tickFormatter={(v: number) => formatNumber(v, true)}
            className="text-[11px]"
          />
          <ChartTooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={
              <ChartTooltipContent
                className="rounded-xl bg-popover/80 tabular-nums backdrop-blur-2xl"
                labelFormatter={(value) =>
                  usage.granularity === "hour"
                    ? `${formatShortDay(String(value))}, ${formatHour(String(value))}`
                    : formatShortDay(String(value))
                }
              />
            }
          />
          {keys.map((key) => (
            <Area
              key={key}
              dataKey={key}
              type="monotone"
              {...(stacked ? { stackId: "usage" } : {})}
              stroke={`var(--color-${key})`}
              strokeWidth={2}
              fill={`url(#${gradient}-${key})`}
              isAnimationActive={false}
            />
          ))}
          {labels.length > 1 ? <ChartLegend content={<ChartLegendContent />} /> : null}
        </AreaChart>
      </ChartContainer>
      <figcaption className="sr-only">
        {usage.metric.name}: {formatNumber(usage.total)} {usage.metric.unit} over the selected range
      </figcaption>
    </figure>
  )
}
