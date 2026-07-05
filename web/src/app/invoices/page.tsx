import type { Metadata } from "next"

import { InvoicesView } from "@/components/invoices/invoices-view"
import { Page } from "@/components/shell/page"

export const metadata: Metadata = { title: "Invoices" }

export default function InvoicesPage() {
  return (
    <Page title="Invoices" subtitle="Drafts stay open for re-rating until they are finalized">
      <InvoicesView />
    </Page>
  )
}
