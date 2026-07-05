import type { Metadata } from "next"

import { Page } from "@/components/shell/page"
import { SimulatorView } from "@/components/simulator/simulator-view"

export const metadata: Metadata = { title: "Pricing simulator" }

export default function SimulatorPage() {
  return (
    <Page title="Pricing simulator" subtitle="What would this customer have paid under a different plan?">
      <SimulatorView />
    </Page>
  )
}
