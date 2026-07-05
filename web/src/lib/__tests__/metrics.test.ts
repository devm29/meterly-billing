import { describe, expect, it } from "vitest"

import type { Metric } from "@/lib/api/schemas"
import { pickDefaultMetric } from "@/lib/metrics"

const metric = (code: string, aggregation: Metric["aggregation"], groupBy: string[] = []): Metric => ({
  id: code,
  code,
  name: code,
  description: null,
  event_code: code,
  aggregation,
  field: aggregation === "count" ? null : "value",
  group_by: groupBy,
  unit: "units",
})

describe("pickDefaultMetric", () => {
  it("prefers a summed metric with a breakdown", () => {
    const picked = pickDefaultMetric([
      metric("calls", "count"),
      metric("storage", "sum"),
      metric("tokens", "sum", ["model"]),
    ])
    expect(picked?.code).toBe("tokens")
  })

  it("falls back to any metric, and to nothing for an empty catalog", () => {
    expect(pickDefaultMetric([metric("calls", "count")])?.code).toBe("calls")
    expect(pickDefaultMetric([])).toBeUndefined()
  })
})
