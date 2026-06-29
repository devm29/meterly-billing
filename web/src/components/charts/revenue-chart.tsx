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
import { seriesLabel } from "@/components/charts/series-label"
import type { Currency, Overview } from "@/lib/api/schemas"
import { formatAmount, formatMonth } from "@/lib/format"

const config = {
  fixed: { label: "Subscriptions", color: "var(--chart-1)" },
  usage: { label: "Usage", color: "var(--chart-2)" },
} satisfies ChartConfig

export function RevenueChart({ revenue, currency }: { revenue: Overview["revenue"]; currency: Currency }) {
  // Gradient ids are document-global; scope them so two charts never share one.
  const gradient = `g${useId().replace(/[^A-Za-z0-9]/g, "")}`
  // The current month is still accruing; plotting it would read as a revenue drop.
  const currentMonth = new Date().toISOString().slice(0, 7)
  const complete = revenue.filter((m) => m.month.slice(0, 7) < currentMonth)
  const firstActive = complete.findIndex((m) => Number(m.total.amount) > 0)
  const months = complete.slice(Math.max(0, firstActive - 1))
  const data = months.map((m) => ({
    month: m.month,
    fixed: Number(m.fixed.amount),
    usage: Number(m.usage.amount),
  }))

  return (
    <figure>
      <ChartContainer config={config} className="aspect-auto h-[280px] w-full">
        <AreaChart data={data} margin={{ left: 4, right: 8, top: 8 }}>
          <defs>
            {(["fixed", "usage"] as const).map((key) => (
              <linearGradient key={key} id={`${gradient}-${key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.22} />
                <stop offset="100%" stopColor={`var(--color-${key})`} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
          <XAxis
            dataKey="month"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            tickFormatter={formatMonth}
            className="text-[11px]"
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={56}
            tickFormatter={(v: number) => formatAmount(v, currency, true)}
            className="text-[11px]"
          />
          <ChartTooltip
            cursor={{ strokeDasharray: "3 3" }}
            content={
              <ChartTooltipContent
                className="rounded-xl bg-popover/80 tabular-nums backdrop-blur-2xl"
                labelFormatter={(value) => formatMonth(String(value))}
                formatter={(value, name) => (
                  <div className="flex w-full justify-between gap-4">
                    <span className="text-muted-foreground">{seriesLabel(config, name)}</span>
                    <span className="font-medium">{formatAmount(Number(value), currency)}</span>
                  </div>
                )}
              />
            }
          />
          <Area
            dataKey="fixed"
            type="monotone"
            stackId="revenue"
            stroke="var(--color-fixed)"
            strokeWidth={2}
            fill={`url(#${gradient}-fixed)`}
            isAnimationActive={false}
          />
          <Area
            dataKey="usage"
            type="monotone"
            stackId="revenue"
            stroke="var(--color-usage)"
            strokeWidth={2}
            fill={`url(#${gradient}-usage)`}
            isAnimationActive={false}
          />
          <ChartLegend content={<ChartLegendContent />} />
        </AreaChart>
      </ChartContainer>
      <table className="sr-only">
        <caption>Billed revenue by month</caption>
        <thead>
          <tr>
            <th>Month</th>
            <th>Subscriptions</th>
            <th>Usage</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={row.month}>
              <td>{formatMonth(row.month)}</td>
              <td>{formatAmount(row.fixed, currency)}</td>
              <td>{formatAmount(row.usage, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
