import type { Metadata } from "next"

import { Page } from "@/components/shell/page"
import { UsageView } from "@/components/usage/usage-view"

export const metadata: Metadata = { title: "Usage" }

export default function UsagePage() {
  return (
    <Page title="Usage" subtitle="Declarative metrics aggregated from the event stream into hourly rollups">
      <UsageView />
    </Page>
  )
}
