"use client"

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { seriesLabel } from "@/components/charts/series-label"
import type { Simulation } from "@/lib/api/schemas"
import { formatAmount, formatShortDay } from "@/lib/format"

const config = {
  actual: { label: "Current plan", color: "var(--chart-1)" },
  candidate: { label: "Candidate", color: "var(--chart-2)" },
} satisfies ChartConfig

export function SimulationChart({ simulation }: { simulation: Simulation }) {
  const data = simulation.periods.map((p) => ({
    period: p.in_progress ? `${formatShortDay(p.period_start)} (so far)` : formatShortDay(p.period_start),
    actual: Number(p.actual.amount),
    candidate: Number(p.candidate.amount),
  }))
  return (
    <ChartContainer config={config} className="aspect-auto h-[260px] w-full">
      <BarChart data={data} margin={{ left: 4, right: 8, top: 8 }} barGap={2} barCategoryGap="28%">
        <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="period" tickLine={false} axisLine={false} tickMargin={8} className="text-[11px]" />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={56}
          tickFormatter={(v: number) => formatAmount(v, simulation.currency, true)}
          className="text-[11px]"
        />
        <ChartTooltip
          cursor={{ className: "fill-accent/50" }}
          content={
            <ChartTooltipContent
              className="rounded-xl bg-popover/80 tabular-nums backdrop-blur-2xl"
              formatter={(value, name) => (
                <div className="flex w-full justify-between gap-4">
                  <span className="text-muted-foreground">{seriesLabel(config, name)}</span>
                  <span className="font-medium">{formatAmount(Number(value), simulation.currency)}</span>
                </div>
              )}
            />
          }
        />
        <Bar dataKey="actual" fill="var(--color-actual)" radius={[4, 4, 0, 0]} />
        <Bar dataKey="candidate" fill="var(--color-candidate)" radius={[4, 4, 0, 0]} />
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  )
}
