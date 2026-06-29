"use client"

import { FileText } from "lucide-react"

import { InvoiceTable } from "@/components/invoices/invoice-table"
import { EntitlementsCard } from "@/components/customers/entitlements-card"
import { UsageTimeline } from "@/components/customers/usage-timeline"
import { KpiTile } from "@/components/common/kpi-tile"
import { SectionCard } from "@/components/common/section-card"
import { EmptyState, ErrorState, InlineError } from "@/components/common/states"
import { StatusBadge } from "@/components/common/status-badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useCustomer, useCustomerInvoices, useUpcomingInvoice } from "@/lib/api/hooks"
import { formatDay, formatMoney, formatNumber, formatPeriod, formatPeriodShort } from "@/lib/format"

export function CustomerView({ id }: { id: string }) {
  const customer = useCustomer(id)
  const subscription = customer.data?.subscription ?? undefined
  const active = subscription && subscription.status !== "canceled" ? subscription : undefined
  const upcoming = useUpcomingInvoice(active?.id)
  const invoices = useCustomerInvoices(id)

  if (customer.error) return <ErrorState error={customer.error} retry={() => void customer.refetch()} />
  const c = customer.data

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center gap-3">
        {c ? (
          <>
            <h1 className="text-[34px] leading-[41px] font-bold tracking-tight">{c.name}</h1>
            <StatusBadge status={c.status} />
            <span className="w-full text-[15px] text-muted-foreground">
              {c.external_id}
              {c.email ? ` · ${c.email}` : ""}
            </span>
          </>
        ) : (
          <Skeleton className="h-10 w-72" />
        )}
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Billing summary">
        <KpiTile
          label="Plan"
          loading={!c}
          value={c?.plan_name ?? "None"}
          hint={c?.fixed_monthly ? `${formatMoney(c.fixed_monthly)} base fee` : null}
        />
        <KpiTile
          label="Current period"
          loading={!c}
          value={active ? formatPeriodShort(active.current_period_start, active.current_period_end) : "—"}
          hint={
            subscription?.ends_on && !active
              ? `Ended ${formatDay(subscription.ends_on)}`
              : subscription?.status === "trialing" && subscription.trial_ends_on
                ? `Trial until ${formatDay(subscription.trial_ends_on)}`
                : null
          }
        />
        <KpiTile
          label="Accrued this period"
          loading={!c || (Boolean(active) && !upcoming.data && !upcoming.error)}
          value={upcoming.data ? formatMoney(upcoming.data.subtotal) : "—"}
          hint={
            upcoming.error
              ? "couldn’t price usage"
              : active
                ? "usage priced so far"
                : "no active subscription"
          }
        />
        <KpiTile
          label="Invoices"
          loading={!invoices.data && !invoices.error}
          value={invoices.data ? formatNumber(invoices.data.total) : "—"}
          hint={
            invoices.error
              ? "couldn’t load invoices"
              : invoices.data?.items[0]
                ? `last ${formatMoney(invoices.data.items[0].total)}`
                : null
          }
        />
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="min-w-0 xl:col-span-2">
          <UsageTimeline customerId={id} />
        </div>
        <EntitlementsCard customerId={id} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <SectionCard className="xl:col-span-2" title="Invoices" flush>
          {invoices.error ? (
            <InlineError error={invoices.error} retry={() => void invoices.refetch()} />
          ) : invoices.data && invoices.data.items.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No invoices yet"
              description="The first invoice is drafted when this customer’s period closes."
            />
          ) : (
            <InvoiceTable invoices={invoices.data?.items} showCustomer={false} />
          )}
        </SectionCard>
        <div className="space-y-6">
          {upcoming.error ? (
            <SectionCard title="Upcoming invoice" flush>
              <InlineError error={upcoming.error} retry={() => void upcoming.refetch()} />
            </SectionCard>
          ) : upcoming.data ? (
            <SectionCard
              title="Upcoming invoice"
              description={`So far for ${formatPeriod(upcoming.data.period_start, upcoming.data.period_end)}`}
              flush
            >
              <ul className="divide-y divide-border/70 text-[14px]">
                {upcoming.data.lines.map((line) => (
                  <li key={line.key} className="flex min-h-11 items-center justify-between gap-3 px-5">
                    <span className="truncate">{line.description}</span>
                    <span className="tabular-nums">{formatMoney(line.amount)}</span>
                  </li>
                ))}
                <li className="flex min-h-11 items-center justify-between px-5 font-semibold">
                  <span>Total so far</span>
                  <span className="tabular-nums">{formatMoney(upcoming.data.subtotal)}</span>
                </li>
              </ul>
            </SectionCard>
          ) : null}
          {subscription ? (
            <SectionCard title="Plan history" flush>
              <ol className="divide-y divide-border/70">
                {[...subscription.phases].reverse().map((phase) => (
                  <li
                    key={`${phase.plan_version_id}-${phase.starts_on}`}
                    className="flex min-h-11 items-center justify-between gap-3 px-5 text-[14px]"
                  >
                    <span className="font-medium">
                      {phase.plan_name}{" "}
                      <span className="font-normal text-muted-foreground">v{phase.version}</span>
                    </span>
                    <span className="text-[13px] text-muted-foreground tabular-nums">
                      {formatDay(phase.starts_on)} – {phase.ends_on ? formatDay(phase.ends_on) : "now"}
                    </span>
                  </li>
                ))}
              </ol>
            </SectionCard>
          ) : null}
        </div>
      </div>
    </div>
  )
}
