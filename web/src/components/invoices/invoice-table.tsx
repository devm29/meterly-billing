"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"

import { StatusBadge } from "@/components/common/status-badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { InvoiceSummary } from "@/lib/api/schemas"
import { formatMoney, formatPeriod } from "@/lib/format"
import { cn } from "@/lib/utils"

export function InvoiceTable({
  invoices,
  compact = false,
  showCustomer = true,
}: {
  invoices: InvoiceSummary[] | undefined
  compact?: boolean
  showCustomer?: boolean
}) {
  const router = useRouter()
  return (
    <Table>
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          <TableHead className="pl-5 text-xs font-medium text-muted-foreground">Invoice</TableHead>
          {showCustomer && !compact ? (
            <TableHead className="text-xs font-medium text-muted-foreground">Customer</TableHead>
          ) : null}
          {compact ? null : (
            <TableHead className="text-xs font-medium text-muted-foreground">Service period</TableHead>
          )}
          <TableHead className="text-xs font-medium text-muted-foreground">Status</TableHead>
          <TableHead className="pr-5 text-right text-xs font-medium text-muted-foreground">Total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {invoices
          ? invoices.map((invoice) => (
              <TableRow
                key={invoice.id}
                className="h-11 cursor-pointer hover:bg-accent/50"
                onClick={() => router.push(`/invoices/${encodeURIComponent(invoice.id)}`)}
              >
                <TableCell className={cn("pl-5", compact && "w-full max-w-0")}>
                  <Link
                    href={`/invoices/${encodeURIComponent(invoice.id)}`}
                    onClick={(event) => event.stopPropagation()}
                    className="block truncate font-medium tabular-nums hover:underline focus-visible:underline focus-visible:outline-none"
                  >
                    {compact ? invoice.customer_name : (invoice.number ?? "Draft")}
                  </Link>
                  {compact ? (
                    <div className="truncate text-xs text-muted-foreground tabular-nums">
                      {invoice.number ?? "Draft"} · {formatPeriod(invoice.period_start, invoice.period_end)}
                    </div>
                  ) : null}
                </TableCell>
                {showCustomer && !compact ? (
                  <TableCell className="max-w-[200px] truncate">{invoice.customer_name}</TableCell>
                ) : null}
                {compact ? null : (
                  <TableCell className="text-muted-foreground tabular-nums">
                    {formatPeriod(invoice.period_start, invoice.period_end)}
                  </TableCell>
                )}
                <TableCell>
                  <StatusBadge status={invoice.status} />
                </TableCell>
                <TableCell className="pr-5 text-right font-medium tabular-nums">
                  {formatMoney(invoice.total)}
                </TableCell>
              </TableRow>
            ))
          : Array.from({ length: 6 }, (_, i) => (
              <TableRow key={i}>
                <TableCell colSpan={5} className="px-5">
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            ))}
      </TableBody>
    </Table>
  )
}
