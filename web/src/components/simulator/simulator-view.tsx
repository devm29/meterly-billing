"use client"

import { Calculator, ChevronRight } from "lucide-react"
import { useDeferredValue, useId, useMemo, useState } from "react"
import { toast } from "sonner"

import { SimulationChart } from "@/components/charts/simulation-chart"
import { PriceEditor } from "@/components/pricing/price-editor"
import { describePrice, isValidPrice } from "@/lib/pricing"
import { KpiTile } from "@/components/common/kpi-tile"
import { Segmented } from "@/components/common/segmented"
import { SectionCard } from "@/components/common/section-card"
import { EmptyState } from "@/components/common/states"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useCustomers, usePlans, useSimulation, type SimulationInput } from "@/lib/api/hooks"
import type { Charge, Currency, Customer, Plan, PlanTerms, PriceModel, Simulation } from "@/lib/api/schemas"
import { formatMoney, formatPercent, formatPeriod } from "@/lib/format"
import { cn } from "@/lib/utils"

type Mode = "plan" | "custom"

const modes = [
  { value: "plan", label: "Existing plan" },
  { value: "custom", label: "Custom pricing" },
] as const satisfies readonly { value: Mode; label: string }[]

const periodOptions = [
  { value: "3", label: "3 periods" },
  { value: "6", label: "6 periods" },
] as const

function versionOptions(plans: Plan[]) {
  return plans.flatMap((plan) =>
    plan.versions.map((v) => ({ value: v.id, label: `${plan.name} v${v.version}`, terms: v.terms })),
  )
}

type CustomerOption = { value: string; label: string; subscription: Customer["subscription"] }

const CUSTOMER_RESULTS = 25

export function SimulatorView() {
  const [customerQuery, setCustomerQuery] = useState("")
  const deferredQuery = useDeferredValue(customerQuery.trim())
  const customers = useCustomers(deferredQuery, 0, CUSTOMER_RESULTS)
  const plans = usePlans()
  const simulation = useSimulation()
  const [picked, setPicked] = useState<CustomerOption | null>(null)
  const customerId = picked?.value ?? null
  const [mode, setMode] = useState<Mode>("plan")
  const [versionId, setVersionId] = useState<string | null>(null)
  const [periods, setPeriods] = useState<(typeof periodOptions)[number]["value"]>("3")
  const [customTerms, setCustomTerms] = useState<PlanTerms | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const customerSelect = useId()
  const customerSearch = useId()
  const planSelect = useId()

  const customerItems = useMemo(() => {
    const found: CustomerOption[] = (customers.data?.items ?? [])
      .filter((c) => c.subscription)
      .map((c) => ({ value: c.external_id, label: c.name, subscription: c.subscription }))
    // Keep the chosen customer selectable even when a new search no longer matches it.
    return picked && !found.some((c) => c.value === picked.value) ? [picked, ...found] : found
  }, [customers.data, picked])
  const versions = useMemo(() => versionOptions(plans.data ?? []), [plans.data])
  const customer = picked
  const currentVersionId = customer?.subscription?.phases.at(-1)?.plan_version_id

  const selectCustomer = (next: string) => {
    const option = customerItems.find((c) => c.value === next)
    if (!option) return
    setPicked(option)
    const current = option.subscription?.phases.at(-1)?.plan_version_id
    const terms = versions.find((v) => v.value === current)?.terms
    setCustomTerms(terms ?? null)
    setEditing(null)
    simulation.reset()
  }

  const updateCharge = (key: string, price: PriceModel) => {
    if (!customTerms) return
    setCustomTerms({
      ...customTerms,
      charges: customTerms.charges.map((c) => (c.key === key ? { ...c, price } : c)),
    })
  }

  const run = () => {
    if (!customerId) return
    const base = { customer_id: customerId, periods: Number(periods) }
    let input: SimulationInput
    if (mode === "plan") {
      if (!versionId) return
      input = { ...base, plan_version_id: versionId }
    } else {
      if (!customTerms) return
      input = { ...base, terms: customTerms }
    }
    simulation.mutate(input, { onError: (error) => toast.error(error.message) })
  }

  const ready =
    Boolean(customerId) &&
    (mode === "plan" ? Boolean(versionId) : Boolean(customTerms?.charges.every((c) => isValidPrice(c.price))))

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
      <SectionCard
        title="Scenario"
        description="Replay a customer’s real metered usage through different pricing."
        className="self-start"
      >
        <div className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor={customerSearch} className="text-[13px] font-medium">
              Customer
            </Label>
            <Input
              id={customerSearch}
              type="search"
              placeholder="Search by name or ID"
              value={customerQuery}
              onChange={(event) => setCustomerQuery(event.target.value)}
              className="h-9 rounded-lg text-[14px]"
            />
            <label htmlFor={customerSelect} className="sr-only">
              Matching customers
            </label>
            <Select
              items={customerItems}
              value={customerId}
              onValueChange={(next) => next && selectCustomer(next)}
            >
              <SelectTrigger id={customerSelect} className="h-9 w-full rounded-lg text-[14px]">
                <SelectValue
                  placeholder={
                    customers.isFetching
                      ? "Searching…"
                      : customerItems.length
                        ? "Choose a customer"
                        : "No subscribed customers match"
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {customerItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {customer?.subscription ? (
              <p className="text-xs text-muted-foreground">
                Currently on {customer.subscription.phases.at(-1)?.plan_name} v
                {customer.subscription.phases.at(-1)?.version}
              </p>
            ) : null}
          </div>

          <Segmented label="Candidate source" value={mode} options={modes} onChange={setMode} />

          {mode === "plan" ? (
            <div className="space-y-1.5">
              <Label htmlFor={planSelect} className="text-[13px] font-medium">
                Candidate plan
              </Label>
              <Select items={versions} value={versionId} onValueChange={(next) => setVersionId(next)}>
                <SelectTrigger id={planSelect} className="h-9 w-full rounded-lg text-[14px]">
                  <SelectValue placeholder="Choose a plan version" />
                </SelectTrigger>
                <SelectContent>
                  {versions.map((v) => (
                    <SelectItem key={v.value} value={v.value} disabled={v.value === currentVersionId}>
                      {v.label}
                      {v.value === currentVersionId ? " (current)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : customTerms ? (
            <ChargeList
              charges={customTerms.charges}
              currency={customTerms.currency}
              editing={editing}
              onEdit={setEditing}
              onChange={updateCharge}
            />
          ) : (
            <p className="text-[13px] text-muted-foreground">
              Choose a customer to start from their current prices.
            </p>
          )}

          <Segmented label="History" value={periods} options={periodOptions} onChange={setPeriods} />

          <Button className="w-full" disabled={!ready || simulation.isPending} onClick={run}>
            <Calculator className="size-4" strokeWidth={1.75} />
            {simulation.isPending ? "Simulating…" : "Simulate"}
          </Button>
        </div>
      </SectionCard>

      <div className="min-w-0">
        {simulation.data ? (
          <SimulationResult simulation={simulation.data} />
        ) : (
          <SectionCard title="Results">
            <EmptyState
              icon={Calculator}
              title="See what a customer would pay"
              description="Pick a customer and a candidate plan. Their actual usage is re-priced period by period."
            />
          </SectionCard>
        )}
      </div>
    </div>
  )
}

function ChargeList({
  charges,
  currency,
  editing,
  onEdit,
  onChange,
}: {
  charges: Charge[]
  currency: Currency
  editing: string | null
  onEdit: (key: string | null) => void
  onChange: (key: string, price: PriceModel) => void
}) {
  return (
    <div className="space-y-1.5">
      <span className="text-[13px] font-medium">Charges</span>
      <ul className="divide-y divide-border/70 overflow-hidden rounded-xl ring-1 ring-border/70">
        {charges.map((charge) => {
          const open = editing === charge.key
          return (
            <li key={charge.key}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => onEdit(open ? null : charge.key)}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-accent/50 focus-visible:bg-accent/60 focus-visible:outline-none"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium">{charge.name}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {describePrice(charge.price, currency)}
                  </div>
                </div>
                <ChevronRight
                  className={cn(
                    "size-4 text-muted-foreground transition-transform duration-200",
                    open && "rotate-90",
                  )}
                  aria-hidden
                />
              </button>
              {open ? (
                <div className="border-t border-border/70 bg-secondary/40 px-3 py-3">
                  <PriceEditor
                    value={charge.price}
                    currency={currency}
                    onChange={(price) => onChange(charge.key, price)}
                  />
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function SimulationResult({ simulation }: { simulation: Simulation }) {
  const ratio = simulation.delta_ratio ? Number(simulation.delta_ratio) : null
  const latest = simulation.periods.at(-1)
  return (
    <div className="space-y-6" aria-live="polite">
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiTile
          label={`On ${simulation.current_plan}`}
          value={formatMoney(simulation.total_actual)}
          hint={`${simulation.periods.length} periods`}
        />
        <KpiTile
          label={`On ${simulation.candidate_plan}`}
          value={formatMoney(simulation.total_candidate)}
          hint="same usage"
        />
        <KpiTile
          label="Difference"
          value={formatMoney(simulation.delta)}
          hint={ratio !== null ? `${formatPercent(ratio, true)} for the customer` : null}
        />
      </section>
      <SectionCard
        title="Per period"
        description="Actual billings next to the candidate price for the same usage"
      >
        <SimulationChart simulation={simulation} />
      </SectionCard>
      <SectionCard title="Period detail" flush>
        <table className="w-full text-[14px] tabular-nums">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border/70">
              <th className="px-5 py-2.5 text-left font-medium">Period</th>
              <th className="px-3 py-2.5 text-right font-medium">Actual</th>
              <th className="px-3 py-2.5 text-right font-medium">Candidate</th>
              <th className="px-5 py-2.5 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">
            {simulation.periods.map((p) => (
              <tr key={p.period_start} className="h-11">
                <td className="px-5">
                  {formatPeriod(p.period_start, p.period_end)}
                  {p.in_progress ? (
                    <span className="ml-2 text-xs text-muted-foreground">in progress</span>
                  ) : null}
                </td>
                <td className="px-3 text-right text-muted-foreground">{formatMoney(p.actual)}</td>
                <td className="px-3 text-right">{formatMoney(p.candidate)}</td>
                <td
                  className={cn(
                    "px-5 text-right font-medium",
                    Number(p.delta.amount) > 0
                      ? "text-destructive"
                      : Number(p.delta.amount) < 0
                        ? "text-success-foreground"
                        : "",
                  )}
                >
                  {formatMoney(p.delta)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
      {latest ? (
        <SectionCard
          title="Candidate invoice"
          description={`Lines for ${formatPeriod(latest.period_start, latest.period_end)}`}
          flush
        >
          <ul className="divide-y divide-border/70 text-[14px]">
            {latest.candidate_lines.map((line) => (
              <li key={line.key} className="flex min-h-11 items-center justify-between gap-3 px-5">
                <span className="truncate">{line.description}</span>
                <span className="tabular-nums">{formatMoney(line.amount)}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      ) : null}
    </div>
  )
}
