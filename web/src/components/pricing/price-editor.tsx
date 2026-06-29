"use client"

import { Plus, X } from "lucide-react"
import { useId } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { Currency, PriceModel, Tier } from "@/lib/api/schemas"
import { convertModel, isModel, modelLabels, usageModels, type Model } from "@/lib/pricing"

function Field({
  label,
  value,
  onChange,
  suffix,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  suffix?: string
}) {
  const id = useId()
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-[13px] font-medium">
        {label}
      </Label>
      <div className="relative">
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-9 rounded-lg text-[14px] tabular-nums"
        />
        {suffix ? (
          <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted-foreground">
            {suffix}
          </span>
        ) : null}
      </div>
    </div>
  )
}

export function PriceEditor({
  value,
  onChange,
  currency,
}: {
  value: PriceModel
  onChange: (value: PriceModel) => void
  currency: Currency
}) {
  // A flat charge stays flat and a metered one stays metered; the API rejects swapping kinds.
  const models: readonly Model[] = value.model === "flat" ? ["flat"] : usageModels
  const items = models.map((m) => ({ value: m, label: modelLabels[m] }))
  const selectId = useId()

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor={selectId} className="text-[13px] font-medium">
          Pricing model
        </Label>
        <Select
          items={items}
          value={value.model}
          onValueChange={(next) => {
            if (isModel(next)) onChange(convertModel(value, next))
          }}
        >
          <SelectTrigger id={selectId} className="h-9 w-full rounded-lg text-[14px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {value.model === "flat" ? (
        <Field
          label="Amount per period"
          value={value.amount}
          onChange={(amount) => onChange({ ...value, amount })}
          suffix={currency}
        />
      ) : null}

      {value.model === "per_unit" ? (
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Unit price"
            value={value.unit_price}
            onChange={(unit_price) => onChange({ ...value, unit_price })}
            suffix={currency}
          />
          <Field
            label="Free units"
            value={value.free_units}
            onChange={(free_units) => onChange({ ...value, free_units })}
          />
        </div>
      ) : null}

      {value.model === "package" ? (
        <div className="grid grid-cols-3 gap-3">
          <Field
            label="Package size"
            value={value.package_size}
            onChange={(package_size) => onChange({ ...value, package_size })}
          />
          <Field
            label="Package price"
            value={value.package_price}
            onChange={(package_price) => onChange({ ...value, package_price })}
            suffix={currency}
          />
          <Field
            label="Free units"
            value={value.free_units}
            onChange={(free_units) => onChange({ ...value, free_units })}
          />
        </div>
      ) : null}

      {value.model === "volume" || value.model === "graduated" ? (
        <TierEditor
          tiers={value.tiers}
          freeUnits={value.free_units}
          onChange={(tiers, free_units) => onChange({ ...value, tiers, free_units })}
        />
      ) : null}
    </div>
  )
}

function TierEditor({
  tiers,
  freeUnits,
  onChange,
}: {
  tiers: Tier[]
  freeUnits: string
  onChange: (tiers: Tier[], freeUnits: string) => void
}) {
  const update = (index: number, patch: Partial<Tier>) =>
    onChange(
      tiers.map((tier, i) => (i === index ? { ...tier, ...patch } : tier)),
      freeUnits,
    )
  const addTier = () => {
    const last = tiers.at(-1)
    const previousBound = tiers.length > 1 ? Number(tiers.at(-2)?.up_to ?? 0) : 0
    const bound = String(Math.max(previousBound * 10, 1000))
    const closed = tiers.slice(0, -1)
    onChange(
      [
        ...closed,
        { up_to: bound, unit_price: last?.unit_price ?? "0", flat_fee: last?.flat_fee ?? "0" },
        { up_to: null, unit_price: last?.unit_price ?? "0", flat_fee: "0" },
      ],
      freeUnits,
    )
  }
  const removeTier = (index: number) => {
    const next = tiers.filter((_, i) => i !== index)
    const lastIndex = next.length - 1
    onChange(
      next.map((tier, i) => (i === lastIndex ? { ...tier, up_to: null } : tier)),
      freeUnits,
    )
  }

  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-xl ring-1 ring-border/70">
        <div className="grid grid-cols-[1.3fr_1.1fr_0.8fr_28px] gap-2 bg-secondary/60 px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>Up to</span>
          <span>Unit price</span>
          <span>Flat fee</span>
          <span className="sr-only">Remove</span>
        </div>
        <ul className="divide-y divide-border/70">
          {tiers.map((tier, index) => {
            const last = index === tiers.length - 1
            return (
              <li
                key={index}
                className="grid grid-cols-[1.3fr_1.1fr_0.8fr_28px] items-center gap-2 px-3 py-2"
              >
                {last ? (
                  <span className="text-[13px] text-muted-foreground">and beyond</span>
                ) : (
                  <Input
                    aria-label={`Tier ${index + 1} upper bound`}
                    inputMode="decimal"
                    value={tier.up_to ?? ""}
                    onChange={(event) => update(index, { up_to: event.target.value })}
                    className="h-8 rounded-md text-[13px] tabular-nums"
                  />
                )}
                <Input
                  aria-label={`Tier ${index + 1} unit price`}
                  inputMode="decimal"
                  value={tier.unit_price}
                  onChange={(event) => update(index, { unit_price: event.target.value })}
                  className="h-8 rounded-md text-[13px] tabular-nums"
                />
                <Input
                  aria-label={`Tier ${index + 1} flat fee`}
                  inputMode="decimal"
                  value={tier.flat_fee}
                  onChange={(event) => update(index, { flat_fee: event.target.value })}
                  className="h-8 rounded-md text-[13px] tabular-nums"
                />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove tier ${index + 1}`}
                  disabled={tiers.length === 1}
                  onClick={() => removeTier(index)}
                >
                  <X className="size-3.5" />
                </Button>
              </li>
            )
          })}
        </ul>
      </div>
      <div className="flex items-end justify-between gap-3">
        <Button variant="secondary" size="sm" onClick={addTier}>
          <Plus className="size-3.5" /> Add tier
        </Button>
        <div className="w-36">
          <Field label="Free units" value={freeUnits} onChange={(free) => onChange(tiers, free)} />
        </div>
      </div>
    </div>
  )
}
