import type { ReactNode } from "react"

import type { ChartConfig } from "@/components/ui/chart"

export function seriesLabel(config: ChartConfig, name: unknown): ReactNode {
  const key = String(name)
  return (Object.hasOwn(config, key) ? config[key]?.label : undefined) ?? key
}
