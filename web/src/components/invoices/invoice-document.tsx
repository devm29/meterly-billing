"use client"

import { ChevronRight } from "lucide-react"
import Link from "next/link"
import { Fragment, useState, type ReactNode } from "react"

import { StatusBadge } from "@/components/common/status-badge"
import { Card } from "@/components/ui/card"
import type { Invoice, InvoiceLine } from "@/lib/api/schemas"
import { formatDay, formatMoney, formatNumber, formatPeriod } from "@/lib/format"
import { cn } from "@/lib/utils"

function hasBreakdown(line: InvoiceLine): boolean {
  return line.details.components.length > 1 || line.details.groups.length > 0
}

function dimensionLabel(dimensions: Record<string, string | null>): string {
  return (
    Object.values(dimensions)
      .map((v) => v ?? "(none)")
      .join(" · ") || "All"
  )
}

export function InvoiceDocument({ invoice, actions }: { invoice: Invoice; actions?: ReactNode }) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <Card className="gap-0 py-0">
      <div className="flex flex-wrap items-start justify-between gap-4 px-6 pt-6 pb-5 sm:px-8 sm:pt-8">
        <div>
          <div className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Invoice</div>
          <div className="mt-1 flex items-center gap-3">
            <span className="text-[28px] leading-[34px] font-semibold tracking-tight tabular-nums">
              {invoice.number ?? "Draft"}
            </span>
            {invoice.status === "draft" ? null : <StatusBadge status={invoice.status} />}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>

      <dl className="grid grid-cols-1 gap-5 border-y border-border/70 px-6 py-5 sm:grid-cols-3 sm:px-8">
        <div>
          <dt className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Billed to</dt>
          <dd className="mt-1 text-[14px] font-medium">
            <Link href={`/customers/${invoice.customer_id}`} className="hover:underline">
              {invoice.customer_name}
            </Link>
          </dd>
          <dd className="text-[13px] text-muted-foreground">{invoice.customer_id}</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            Service period
          </dt>
          <dd className="mt-1 text-[14px] font-medium tabular-nums">
            {formatPeriod(invoice.period_start, invoice.period_end)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Issued</dt>
          <dd className="mt-1 text-[14px] font-medium tabular-nums">
            {invoice.finalized_at ? formatDay(invoice.finalized_at) : "Not yet issued"}
          </dd>
        </div>
      </dl>

      <div className="overflow-x-auto px-2 sm:px-4">
        <table className="w-full min-w-[520px] text-[14px] tabular-nums">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="px-4 py-3 font-medium">Description</th>
              <th className="px-4 py-3 text-right font-medium">Quantity</th>
              <th className="px-4 py-3 text-right font-medium">Amount</th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((line) => {
              const expandable = hasBreakdown(line)
              const expanded = open.has(line.key)
              return (
                <Fragment key={line.key}>
                  <tr className="border-t border-border/70">
                    <td className="px-4 py-3">
                      {expandable ? (
                        <button
                          type="button"
                          onClick={() => toggle(line.key)}
                          aria-expanded={expanded}
                          className="inline-flex items-center gap-1.5 rounded-md text-left font-medium hover:text-primary focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <ChevronRight
                            className={cn(
                              "size-3.5 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none",
                              expanded && "rotate-90",
                            )}
                            aria-hidden
                          />
                          {line.description}
                        </button>
                      ) : (
                        <span className="pl-5 font-medium">{line.description}</span>
                      )}
                      {line.kind === "minimum" ? (
                        <div className="pl-5 text-xs text-muted-foreground">
                          Brings usage spend up to the committed minimum
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground">
                      {line.kind === "usage" ? formatNumber(line.quantity) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">{formatMoney(line.amount)}</td>
                  </tr>
                  {expanded
                    ? line.details.components.length > 1
                      ? line.details.components.map((c) => (
                          <tr key={`${line.key}-${c.label}`} className="text-[13px] text-muted-foreground">
                            <td className="py-1.5 pr-4 pl-14">{c.label}</td>
                            <td className="px-4 py-1.5 text-right">{formatNumber(c.units)}</td>
                            <td className="px-4 py-1.5 text-right">{formatMoney(c.amount)}</td>
                          </tr>
                        ))
                      : null
                    : null}
                  {expanded && line.details.groups.length > 0 ? (
                    <>
                      <tr className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                        <td className="pt-2 pr-4 pb-1 pl-14" colSpan={3}>
                          By dimension
                        </td>
                      </tr>
                      {line.details.groups.map((g) => (
                        <tr
                          key={`${line.key}-${dimensionLabel(g.dimensions)}`}
                          className="text-[13px] text-muted-foreground"
                        >
                          <td className="py-1.5 pr-4 pl-14">{dimensionLabel(g.dimensions)}</td>
                          <td className="px-4 py-1.5 text-right">{formatNumber(g.quantity)}</td>
                          <td className="px-4 py-1.5 text-right">{formatMoney(g.amount)}</td>
                        </tr>
                      ))}
                    </>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="ml-auto w-full max-w-xs space-y-2 border-t border-border/70 px-6 pt-4 pb-6 text-[14px] tabular-nums sm:px-8">
        <div className="flex justify-between text-muted-foreground">
          <span>Subtotal</span>
          <span>{formatMoney(invoice.subtotal)}</span>
        </div>
        <div className="flex justify-between border-t border-foreground/80 pt-3 text-[17px] font-semibold">
          <span>Total due</span>
          <span>{formatMoney(invoice.total)}</span>
        </div>
      </div>
    </Card>
  )
}
