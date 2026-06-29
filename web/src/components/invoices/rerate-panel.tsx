"use client"

import { ArrowRight, RotateCcw } from "lucide-react"
import { useId, useMemo, useState } from "react"
import { toast } from "sonner"

import { PriceEditor } from "@/components/pricing/price-editor"
import { describePrice, isValidPrice } from "@/lib/pricing"
import { SectionCard } from "@/components/common/section-card"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useRerate } from "@/lib/api/hooks"
import type { Invoice, PriceModel, Rerate } from "@/lib/api/schemas"
import { formatMoney } from "@/lib/format"
import { cn } from "@/lib/utils"

export function ReratePanel({
  invoice,
  diff,
  onDiff,
}: {
  invoice: Invoice
  diff: Rerate["diff"] | null
  onDiff: (diff: Rerate["diff"] | null) => void
}) {
  const usageCharges = useMemo(() => invoice.charges.filter((c) => c.metric_code !== null), [invoice.charges])
  const [chargeKey, setChargeKey] = useState(usageCharges[0]?.key ?? "")
  const charge = usageCharges.find((c) => c.key === chargeKey)
  const [draft, setDraft] = useState<PriceModel | null>(charge?.price ?? null)
  const rerate = useRerate(invoice.id)
  const selectId = useId()

  if (!charge || !draft) return null

  const valid = isValidPrice(draft)
  const submit = (apply: boolean) =>
    rerate.mutate(
      { overrides: { [charge.key]: draft }, apply },
      {
        onSuccess: (result) => {
          onDiff(result.diff)
          if (apply) toast.success(`Draft re-rated · total now ${formatMoney(result.diff.subtotal_after)}`)
        },
        onError: (error) => toast.error(error.message),
      },
    )

  return (
    <SectionCard
      title="Re-rate this draft"
      description="Re-price the frozen usage snapshot with new prices. Nothing changes until you apply."
    >
      <div className="space-y-5">
        <div className="space-y-1.5">
          <Label htmlFor={selectId} className="text-[13px] font-medium">
            Charge
          </Label>
          <Select
            items={usageCharges.map((c) => ({ value: c.key, label: c.name }))}
            value={chargeKey}
            onValueChange={(next) => {
              const found = usageCharges.find((c) => c.key === next)
              if (!found) return
              setChargeKey(found.key)
              setDraft(found.price)
              onDiff(null)
            }}
          >
            <SelectTrigger id={selectId} className="h-9 w-full rounded-lg text-[14px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {usageCharges.map((c) => (
                <SelectItem key={c.key} value={c.key}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Currently {describePrice(charge.price, invoice.currency)}
          </p>
        </div>

        <PriceEditor
          currency={invoice.currency}
          value={draft}
          onChange={(next) => {
            setDraft(next)
            onDiff(null)
          }}
        />

        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => {
              setDraft(charge.price)
              onDiff(null)
            }}
          >
            <RotateCcw className="size-3.5" /> Reset
          </Button>
          <Button variant="secondary" disabled={!valid || rerate.isPending} onClick={() => submit(false)}>
            Preview diff
          </Button>
          <Button disabled={!valid || rerate.isPending || !diff} onClick={() => submit(true)}>
            Apply to draft
          </Button>
        </div>
      </div>
    </SectionCard>
  )
}

export function DiffTable({ diff }: { diff: Rerate["diff"] }) {
  const deltaClass = (amount: string) =>
    Number(amount) > 0
      ? "text-destructive"
      : Number(amount) < 0
        ? "text-success-foreground"
        : "text-muted-foreground"
  return (
    <div aria-live="polite" className="overflow-hidden rounded-xl ring-1 ring-border/70">
      <table className="w-full text-[13px] tabular-nums">
        <thead className="bg-secondary/60 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Line</th>
            <th className="px-3 py-2 text-right font-medium">Before</th>
            <th className="px-3 py-2 text-right font-medium">After</th>
            <th className="px-3 py-2 text-right font-medium">Change</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70">
          {diff.lines.map((line) => (
            <tr key={line.key} className={cn(Number(line.delta.amount) !== 0 && "bg-primary/5")}>
              <td className="max-w-[220px] truncate px-3 py-2">{line.description}</td>
              <td className="px-3 py-2 text-right text-muted-foreground">
                {line.before ? formatMoney(line.before) : "—"}
              </td>
              <td className="px-3 py-2 text-right">{line.after ? formatMoney(line.after) : "—"}</td>
              <td className={cn("px-3 py-2 text-right font-medium", deltaClass(line.delta.amount))}>
                {Number(line.delta.amount) === 0 ? "—" : formatMoney(line.delta)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot className="border-t border-border/70 font-semibold">
          <tr>
            <td className="px-3 py-2.5">Total</td>
            <td className="px-3 py-2.5 text-right text-muted-foreground">
              {formatMoney(diff.subtotal_before)}
            </td>
            <td className="px-3 py-2.5 text-right">
              <span className="inline-flex items-center gap-1">
                <ArrowRight className="size-3 text-muted-foreground" aria-hidden />
                {formatMoney(diff.subtotal_after)}
              </span>
            </td>
            <td className={cn("px-3 py-2.5 text-right", deltaClass(diff.delta.amount))}>
              {formatMoney(diff.delta)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
