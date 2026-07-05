import { z } from "zod"

import type { Currency, PriceModel, Tier } from "@/lib/api/schemas"
import { formatPrice } from "@/lib/format"

export type Model = PriceModel["model"]

export const modelLabels: Record<Model, string> = {
  flat: "Flat fee",
  per_unit: "Per unit",
  package: "Package",
  volume: "Volume tiers",
  graduated: "Graduated tiers",
}

export const usageModels: Model[] = ["per_unit", "package", "volume", "graduated"]

function freeUnits(model: PriceModel): string {
  return model.model === "flat" ? "0" : model.free_units
}

export function convertModel(current: PriceModel, next: Model): PriceModel {
  const free = freeUnits(current)
  const tiers: Tier[] =
    current.model === "volume" || current.model === "graduated"
      ? current.tiers
      : [
          { up_to: "100000", unit_price: "0.01", flat_fee: "0" },
          { up_to: null, unit_price: "0.005", flat_fee: "0" },
        ]
  switch (next) {
    case "flat":
      return { model: "flat", amount: current.model === "flat" ? current.amount : "0" }
    case "per_unit":
      return {
        model: "per_unit",
        unit_price: current.model === "per_unit" ? current.unit_price : (tiers[0]?.unit_price ?? "0"),
        free_units: free,
      }
    case "package":
      return { model: "package", package_size: "1000", package_price: "1", free_units: free }
    case "volume":
    case "graduated":
      return { model: next, tiers, free_units: free }
  }
}

export function isModel(value: unknown): value is Model {
  return typeof value === "string" && value in modelLabels
}

export function describePrice(model: PriceModel, currency: Currency): string {
  const fmt = (v: string) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 10 })
  const free =
    model.model !== "flat" && Number(model.free_units) > 0 ? ` · ${fmt(model.free_units)} free` : ""
  switch (model.model) {
    case "flat":
      return `${formatPrice(model.amount, currency)} per period`
    case "per_unit":
      return `${formatPrice(model.unit_price, currency)} per unit${free}`
    case "package":
      return `${formatPrice(model.package_price, currency)} per ${fmt(model.package_size)} units${free}`
    case "volume":
    case "graduated":
      return `${modelLabels[model.model]} · ${model.tiers.length} ${model.tiers.length === 1 ? "tier" : "tiers"}${free}`
  }
}

const amount = z.string().regex(/^\d+(\.\d+)?$/)
const positive = amount.refine((v) => Number(v) > 0)
const tierInput = z.object({ up_to: positive.nullable(), unit_price: amount, flat_fee: amount })
const tiersInput = z
  .array(tierInput)
  .min(1)
  .refine((tiers) => tiers.at(-1)?.up_to === null, "the last tier must be open-ended")
  .refine(
    (tiers) => tiers.slice(1, -1).every((t, i) => Number(t.up_to) > Number(tiers[i]?.up_to)),
    "tier bounds must increase",
  )

const priceInputSchema = z.discriminatedUnion("model", [
  z.object({ model: z.literal("flat"), amount }),
  z.object({ model: z.literal("per_unit"), unit_price: amount, free_units: amount }),
  z.object({
    model: z.literal("package"),
    package_size: positive,
    package_price: amount,
    free_units: amount,
  }),
  z.object({ model: z.literal("volume"), tiers: tiersInput, free_units: amount }),
  z.object({ model: z.literal("graduated"), tiers: tiersInput, free_units: amount }),
])

/** Mirrors the API's price validation so the editor can disable submit on bad input. */
export function isValidPrice(model: PriceModel): boolean {
  return priceInputSchema.safeParse(model).success
}
