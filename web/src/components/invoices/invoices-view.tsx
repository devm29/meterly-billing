"use client"

import { FileText } from "lucide-react"
import { useState } from "react"

import { InvoiceTable } from "@/components/invoices/invoice-table"
import { Pager } from "@/components/common/pager"
import { Segmented } from "@/components/common/segmented"
import { EmptyState, ErrorState } from "@/components/common/states"
import { Card } from "@/components/ui/card"
import { useInvoices } from "@/lib/api/hooks"
import type { InvoiceStatus } from "@/lib/api/schemas"

const filters = [
  { value: "all", label: "All" },
  { value: "draft", label: "Drafts" },
  { value: "finalized", label: "Finalized" },
] as const satisfies readonly { value: InvoiceStatus | "all"; label: string }[]

const PAGE = 20

export function InvoicesView() {
  const [status, setStatus] = useState<InvoiceStatus | "all">("all")
  const [offset, setOffset] = useState(0)
  const invoices = useInvoices(status, offset, PAGE)

  return (
    <div className="space-y-4">
      <Segmented
        label="Filter by status"
        value={status}
        options={filters}
        onChange={(next) => {
          setStatus(next)
          setOffset(0)
        }}
      />
      <Card className="gap-0 py-0">
        {invoices.error ? (
          <ErrorState error={invoices.error} retry={() => void invoices.refetch()} />
        ) : invoices.data?.items.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={status === "draft" ? "No drafts to review" : "No invoices yet"}
            description="Invoices are drafted automatically when a billing period closes."
          />
        ) : (
          <>
            <InvoiceTable invoices={invoices.data?.items} />
            {invoices.data ? (
              <Pager offset={offset} limit={PAGE} total={invoices.data.total} onChange={setOffset} />
            ) : null}
          </>
        )}
      </Card>
    </div>
  )
}
