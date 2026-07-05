"use client"

import { FileDown, Lock } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { InvoiceDocument } from "@/components/invoices/invoice-document"
import { DiffTable, ReratePanel } from "@/components/invoices/rerate-panel"
import { SectionCard } from "@/components/common/section-card"
import { ErrorState } from "@/components/common/states"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useFinalizeInvoice, useInvoice } from "@/lib/api/hooks"
import { apiUrl, segment } from "@/lib/api/client"
import type { Rerate } from "@/lib/api/schemas"
import { formatMoney } from "@/lib/format"

export function InvoiceView({ id }: { id: string }) {
  const invoice = useInvoice(id)
  const finalize = useFinalizeInvoice(id)
  const [confirming, setConfirming] = useState(false)
  const [diff, setDiff] = useState<Rerate["diff"] | null>(null)

  if (invoice.error) return <ErrorState error={invoice.error} retry={() => void invoice.refetch()} />
  if (!invoice.data) return <Skeleton className="h-[560px] w-full rounded-xl" />
  const data = invoice.data
  const isDraft = data.status === "draft"

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="min-w-0">
        <InvoiceDocument
          invoice={data}
          actions={
            <>
              <Button
                variant="secondary"
                nativeButton={false}
                render={
                  <a href={apiUrl(`/v1/invoices/${segment(id)}/pdf`)} target="_blank" rel="noreferrer" />
                }
              >
                <FileDown className="size-4" strokeWidth={1.75} /> {isDraft ? "Preview PDF" : "Download PDF"}
              </Button>
              {isDraft ? (
                <Button onClick={() => setConfirming(true)} disabled={finalize.isPending}>
                  <Lock className="size-4" strokeWidth={1.75} /> Finalize
                </Button>
              ) : null}
            </>
          }
        />
        {diff && isDraft ? (
          <SectionCard
            className="mt-6"
            title="Re-rating preview"
            description="Line-by-line effect of the new prices on this draft"
          >
            <DiffTable diff={diff} />
          </SectionCard>
        ) : null}
      </div>

      <aside className="space-y-6">
        {isDraft ? (
          <ReratePanel key={data.total.amount} invoice={data} diff={diff} onDiff={setDiff} />
        ) : (
          <SectionCard
            title="Finalized and immutable"
            description="A database trigger rejects any change to a finalized invoice or its lines."
          >
            <p className="text-[13px] text-muted-foreground">
              Correcting it requires a credit note. Credit notes aren’t supported yet, so finalize only after
              the re-rating review is done.
            </p>
          </SectionCard>
        )}
      </aside>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent className="rounded-2xl sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-[17px] font-semibold">Finalize this invoice?</DialogTitle>
            <DialogDescription>
              {data.customer_name} will be billed {formatMoney(data.total)}. A number is assigned and the
              invoice can no longer be re-rated.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="secondary" />}>Cancel</DialogClose>
            <Button
              disabled={finalize.isPending}
              onClick={() =>
                finalize.mutate(undefined, {
                  onSuccess: (result) => {
                    setConfirming(false)
                    toast.success(`Finalized as ${result.number ?? ""}`)
                  },
                  onError: (error) => toast.error(error.message),
                })
              }
            >
              Finalize
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
