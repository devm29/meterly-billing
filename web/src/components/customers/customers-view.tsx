"use client"

import { Search, Users } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useDeferredValue, useState } from "react"

import { Pager } from "@/components/common/pager"
import { EmptyState, ErrorState } from "@/components/common/states"
import { StatusBadge } from "@/components/common/status-badge"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useCustomers } from "@/lib/api/hooks"
import { formatDay, formatMoney } from "@/lib/format"

const PAGE = 25

export function CustomersView() {
  const router = useRouter()
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const deferred = useDeferredValue(query.trim())
  const customers = useCustomers(deferred, offset, PAGE)

  return (
    <div className="space-y-4">
      <div className="relative max-w-sm">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          aria-label="Search customers"
          placeholder="Search by name or ID"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setOffset(0)
          }}
          className="h-9 rounded-full border-transparent bg-card pl-9 text-[14px] shadow-xs ring-1 ring-border/70"
        />
      </div>
      <Card className="gap-0 py-0">
        {customers.error ? (
          <ErrorState error={customers.error} retry={() => void customers.refetch()} />
        ) : customers.data?.items.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No matching customers"
            description="Try a different name or external ID."
          />
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="pl-5 text-xs font-medium text-muted-foreground">Customer</TableHead>
                  <TableHead className="text-xs font-medium text-muted-foreground">Plan</TableHead>
                  <TableHead className="text-xs font-medium text-muted-foreground">Status</TableHead>
                  <TableHead className="hidden text-xs font-medium text-muted-foreground md:table-cell">
                    Next invoice
                  </TableHead>
                  <TableHead className="pr-5 text-right text-xs font-medium text-muted-foreground">
                    Base fee
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {customers.data
                  ? customers.data.items.map((c) => (
                      <TableRow
                        key={c.id}
                        className="h-12 cursor-pointer hover:bg-accent/50"
                        onClick={() => router.push(`/customers/${encodeURIComponent(c.external_id)}`)}
                      >
                        <TableCell className="pl-5">
                          <Link
                            href={`/customers/${encodeURIComponent(c.external_id)}`}
                            onClick={(event) => event.stopPropagation()}
                            className="font-medium hover:underline focus-visible:underline focus-visible:outline-none"
                          >
                            {c.name}
                          </Link>
                          <div className="text-xs text-muted-foreground">{c.external_id}</div>
                        </TableCell>
                        <TableCell>{c.plan_name ?? "—"}</TableCell>
                        <TableCell>
                          <StatusBadge status={c.status} />
                        </TableCell>
                        <TableCell className="hidden text-muted-foreground tabular-nums md:table-cell">
                          {c.subscription && c.status !== "canceled"
                            ? formatDay(c.subscription.current_period_end)
                            : "—"}
                        </TableCell>
                        <TableCell className="pr-5 text-right tabular-nums">
                          {c.fixed_monthly ? formatMoney(c.fixed_monthly) : "—"}
                        </TableCell>
                      </TableRow>
                    ))
                  : Array.from({ length: 8 }, (_, i) => (
                      <TableRow key={i}>
                        <TableCell colSpan={5} className="px-5">
                          <Skeleton className="h-7 w-full" />
                        </TableCell>
                      </TableRow>
                    ))}
              </TableBody>
            </Table>
            {customers.data ? (
              <Pager offset={offset} limit={PAGE} total={customers.data.total} onChange={setOffset} />
            ) : null}
          </>
        )}
      </Card>
    </div>
  )
}
