import type { Metric } from "@/lib/api/schemas"

/** The metric dashboards open on: a summed metric with a breakdown makes the richest chart. */
export function pickDefaultMetric(metrics: readonly Metric[]): Metric | undefined {
  const sums = metrics.filter((m) => m.aggregation === "sum")
  return sums.find((m) => m.group_by.length > 0) ?? sums[0] ?? metrics[0]
}
