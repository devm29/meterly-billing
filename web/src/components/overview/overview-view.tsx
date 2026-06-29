"use client"

import { BarChart3, ChevronRight, FileText } from "lucide-react"
import Link from "next/link"

import { RevenueChart } from "@/components/charts/revenue-chart"
import { UsageChart } from "@/components/charts/usage-chart"
import { InvoiceTable } from "@/components/invoices/invoice-table"
import { KpiTile } from "@/components/common/kpi-tile"
import { SectionCard } from "@/components/common/section-card"
import { EmptyState, ErrorState, InlineError } from "@/components/common/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useDefaultMetric, useInvoices, useMetricUsage, useOverview } from "@/lib/api/hooks"
import { formatMoney, formatNumber, formatPercent } from "@/lib/format"

export function OverviewView() {
  const overview = useOverview()
  const featured = useDefaultMetric()
  const usage = useMetricUsage(featured.metric?.code, 30)
  const invoices = useInvoices("all", 0, 6)
  const data = overview.data

  if (overview.error) return <ErrorState error={overview.error} retry={() => void overview.refetch()} />

  const previous = data ? Number(data.mrr_previous.amount) : 0
  const delta = data && previous ? Number(data.mrr.amount) / previous - 1 : null

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Key metrics">
        <KpiTile
          label="Billed MRR"
          loading={!data}
          value={data ? formatMoney(data.mrr) : null}
          delta={delta}
          hint="vs. prior month"
        />
        <KpiTile
          label="Contracted MRR"
          loading={!data}
          value={data ? formatMoney(data.contracted_mrr) : null}
          hint={data ? `${formatPercent(Number(data.usage_share))} of billings from usage` : null}
        />
        <KpiTile
          label="Active customers"
          loading={!data}
          value={data ? formatNumber(data.active_customers) : null}
          hint={data ? `ARPA ${formatMoney(data.arpa)} · ${data.trialing_customers} trialing` : null}
        />
        <KpiTile
          label="Drafts awaiting review"
          loading={!data}
          value={data ? formatNumber(data.draft_invoices) : null}
          hint={data ? `${formatMoney(data.draft_total)} unbilled` : null}
        />
      </section>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <SectionCard
          className="xl:col-span-2"
          title="Revenue"
          description="Billed per month, split into subscription fees and metered usage"
        >
          {data ? (
            <RevenueChart revenue={data.revenue} currency={data.currency} />
          ) : (
            <Skeleton className="h-[280px] w-full" />
          )}
        </SectionCard>
        <SectionCard title="Top customers" description="Billed over the last three months" flush>
          {data ? (
            <ol className="divide-y divide-border/70">
              {data.top_customers.map((customer, index) => (
                <li key={customer.customer_id}>
                  <Link
                    href={`/customers/${customer.customer_id}`}
                    className="flex min-h-12 items-center gap-3 px-5 transition-colors hover:bg-accent/50 focus-visible:bg-accent/60 focus-visible:outline-none"
                  >
                    <span className="w-4 text-[13px] text-muted-foreground tabular-nums">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{customer.name}</span>
                    <span className="text-[14px] tabular-nums">{formatMoney(customer.revenue)}</span>
                    <ChevronRight className="size-4 text-muted-foreground/70" aria-hidden />
                  </Link>
                </li>
              ))}
            </ol>
          ) : (
            <div className="space-y-3 px-5">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <SectionCard
          className="xl:col-span-3"
          title={featured.metric?.name ?? "Usage"}
          description={
            usage.data
              ? `${formatNumber(usage.data.total, true)} ${usage.data.metric.unit} in the last 30 days`
              : "Last 30 days"
          }
        >
          {featured.error || usage.error ? (
            <InlineError
              error={featured.error ?? usage.error ?? new Error("Unknown error")}
              retry={() => void usage.refetch()}
            />
          ) : featured.loaded && !featured.metric ? (
            <EmptyState
              icon={BarChart3}
              title="No billable metrics"
              description="Define a metric to chart its usage here."
            />
          ) : usage.data ? (
            <UsageChart usage={usage.data} />
          ) : (
            <Skeleton className="h-[260px] w-full" />
          )}
        </SectionCard>
        <SectionCard
          className="xl:col-span-2"
          title="Recent invoices"
          action={
            <Link href="/invoices" className="text-[13px] font-medium text-primary hover:underline">
              View all
            </Link>
          }
          flush
        >
          {invoices.error ? (
            <InlineError error={invoices.error} retry={() => void invoices.refetch()} />
          ) : invoices.data && invoices.data.items.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No invoices yet"
              description="Invoices appear here once the first billing period closes."
            />
          ) : (
            <InvoiceTable invoices={invoices.data?.items} compact />
          )}
        </SectionCard>
      </div>
    </div>
  )
}
