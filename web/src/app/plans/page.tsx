import type { Metadata } from "next"

import { PlansView } from "@/components/plans/plans-view"
import { Page } from "@/components/shell/page"

export const metadata: Metadata = { title: "Plans" }

export default function PlansPage() {
  return (
    <Page title="Plans" subtitle="Versions are immutable; existing subscribers keep the version they signed">
      <PlansView />
    </Page>
  )
}
