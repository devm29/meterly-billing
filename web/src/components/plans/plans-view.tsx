"use client"

import { Layers } from "lucide-react"
import { useState } from "react"

import { describePrice } from "@/lib/pricing"
import { Segmented } from "@/components/common/segmented"
import { SectionCard } from "@/components/common/section-card"
import { EmptyState, ErrorState } from "@/components/common/states"
import { Skeleton } from "@/components/ui/skeleton"
import { usePlans } from "@/lib/api/hooks"
import type { Currency, Plan, Tier } from "@/lib/api/schemas"
import { formatDay, formatMoney, formatNumber, formatPrice } from "@/lib/format"

export function PlansView() {
  const plans = usePlans()
  if (plans.error) return <ErrorState error={plans.error} retry={() => void plans.refetch()} />
  if (!plans.data) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-[520px] rounded-xl" />
        ))}
      </div>
    )
  }
  if (plans.data.length === 0) {
    return (
      <EmptyState
        icon={Layers}
        title="No plans yet"
        description="Create a plan through the API to start billing customers."
      />
    )
  }
  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
      {plans.data.map((plan) => (
        <PlanCard key={plan.id} plan={plan} />
      ))}
    </div>
  )
}

// Token-style prices are fractions of a cent, so they read better per thousand units.
function tierPriceFormatter(tiers: Tier[], currency: Currency): (unitPrice: string) => string {
  const subCent = tiers.every((tier) => Number(tier.unit_price) < 0.01)
  return subCent
    ? (unitPrice) => `${formatPrice(Number(unitPrice) * 1000, currency)} / 1K`
    : (unitPrice) => `${formatPrice(unitPrice, currency)} each`
}

function TierList({ tiers, currency }: { tiers: Tier[]; currency: Currency }) {
  const format = tierPriceFormatter(tiers, currency)
  return (
    <ol className="mt-1.5 space-y-0.5 text-xs text-muted-foreground tabular-nums">
      {tiers.map((tier, i) => (
        <li key={i} className="flex justify-between">
          <span>{tier.up_to ? `Up to ${formatNumber(tier.up_to, true)}` : "Beyond"}</span>
          <span>{format(tier.unit_price)}</span>
        </li>
      ))}
    </ol>
  )
}

function PlanCard({ plan }: { plan: Plan }) {
  const [versionId, setVersionId] = useState(plan.versions[0]?.id ?? "")
  const version = plan.versions.find((v) => v.id === versionId) ?? plan.versions[0]
  if (!version) return null
  const { terms } = version
  const options = plan.versions.map((v) => ({ value: v.id, label: `v${v.version}` }))

  return (
    <SectionCard
      title={plan.name}
      description={plan.description}
      action={
        options.length > 1 ? (
          <Segmented label="Plan version" value={versionId} options={options} onChange={setVersionId} />
        ) : null
      }
      flush
    >
      <div className="px-5 pb-4">
        <div className="flex items-baseline gap-1">
          <span className="text-[34px] leading-[41px] font-bold tracking-tight tabular-nums">
            {formatMoney(version.fixed_amount)}
          </span>
          <span className="text-[13px] text-muted-foreground">/ {terms.interval}</span>
        </div>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Published {formatDay(version.created_at)}
          {terms.trial_days ? ` · ${terms.trial_days}-day trial` : ""}
          {terms.minimum_commitment
            ? ` · ${formatMoney({ amount: terms.minimum_commitment, currency: terms.currency })} minimum`
            : ""}
        </p>
      </div>
      <div className="border-t border-border/70">
        <h3 className="px-5 pt-4 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Charges
        </h3>
        <ul className="divide-y divide-border/70">
          {terms.charges.map((charge) => (
            <li key={charge.key} className="px-5 py-2.5">
              <div className="flex items-center justify-between gap-3 text-[14px]">
                <span className="font-medium">{charge.name}</span>
                <span className="font-mono text-[11px] text-muted-foreground">
                  {charge.metric_code ?? "recurring"}
                </span>
              </div>
              <div className="text-[13px] text-muted-foreground">
                {describePrice(charge.price, terms.currency)}
              </div>
              {charge.price.model === "graduated" || charge.price.model === "volume" ? (
                <TierList tiers={charge.price.tiers} currency={terms.currency} />
              ) : null}
            </li>
          ))}
        </ul>
      </div>
      {terms.entitlements.length ? (
        <div className="border-t border-border/70 pb-2">
          <h3 className="px-5 pt-4 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            Entitlements
          </h3>
          <ul>
            {terms.entitlements.map((e) => (
              <li key={e.feature} className="flex min-h-9 items-center justify-between px-5 text-[14px]">
                <span>{e.name}</span>
                <span className="text-[13px] text-muted-foreground tabular-nums">
                  {e.limit ? formatNumber(e.limit, true) : "Included"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </SectionCard>
  )
}
