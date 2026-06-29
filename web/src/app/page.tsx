import { OverviewView } from "@/components/overview/overview-view"
import { Page } from "@/components/shell/page"

export default function OverviewPage() {
  return (
    <Page title="Overview" subtitle="Revenue, usage and billing health at a glance">
      <OverviewView />
    </Page>
  )
}
