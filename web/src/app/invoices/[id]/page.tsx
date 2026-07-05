import type { Metadata } from "next"

import { InvoiceView } from "@/components/invoices/invoice-view"
import { Page } from "@/components/shell/page"

export const metadata: Metadata = { title: "Invoice" }

export default async function InvoicePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return (
    <Page title="Invoice" toolbarTitle="Invoices">
      <InvoiceView id={id} />
    </Page>
  )
}
