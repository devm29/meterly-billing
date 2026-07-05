import type { Metadata } from "next"

import { CustomersView } from "@/components/customers/customers-view"
import { Page } from "@/components/shell/page"

export const metadata: Metadata = { title: "Customers" }

export default function CustomersPage() {
  return (
    <Page title="Customers" subtitle="Everyone with a billing relationship">
      <CustomersView />
    </Page>
  )
}
