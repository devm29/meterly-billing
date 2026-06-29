import { describe, expect, it } from "vitest"

import { convertModel, describePrice, isValidPrice } from "@/lib/pricing"
import { invoiceSchema, priceModelSchema, type PriceModel } from "@/lib/api/schemas"

const graduated: PriceModel = {
  model: "graduated",
  free_units: "1000",
  tiers: [
    { up_to: "10000", unit_price: "0.01", flat_fee: "0" },
    { up_to: null, unit_price: "0.002", flat_fee: "0" },
  ],
}

describe("convertModel", () => {
  it("keeps tiers and free units when switching between tiered models", () => {
    expect(convertModel(graduated, "volume")).toEqual({ ...graduated, model: "volume" })
  })

  it("seeds a per-unit price from the first tier", () => {
    expect(convertModel(graduated, "per_unit")).toEqual({
      model: "per_unit",
      unit_price: "0.01",
      free_units: "1000",
    })
  })
})

describe("describePrice", () => {
  it("summarizes models in plain language", () => {
    expect(describePrice(graduated, "USD")).toBe("Graduated tiers · 2 tiers · 1,000 free")
    expect(
      describePrice({ model: "package", package_size: "1000", package_price: "2.5", free_units: "0" }, "USD"),
    ).toBe("$2.50 per 1,000 units")
    expect(describePrice({ model: "per_unit", unit_price: "0.002", free_units: "0" }, "EUR")).toBe(
      "€0.002 per unit",
    )
    expect(describePrice({ model: "flat", amount: "1200" }, "JPY")).toBe("¥1,200 per period")
  })
})

describe("schemas", () => {
  it("rejects unknown price models at the boundary", () => {
    expect(priceModelSchema.safeParse({ model: "magic", amount: "1" }).success).toBe(false)
  })

  it("parses an API invoice payload", () => {
    const parsed = invoiceSchema.safeParse({
      id: "1",
      number: null,
      status: "draft",
      customer_id: "acme",
      customer_name: "Acme",
      currency: "USD",
      period_start: "2026-03-01",
      period_end: "2026-04-01",
      total: { amount: "49.00", currency: "USD" },
      created_at: "2026-04-01T02:00:00Z",
      finalized_at: null,
      subtotal: { amount: "49.00", currency: "USD" },
      price_overrides: {},
      charges: [],
      lines: [],
    })
    expect(parsed.success).toBe(true)
  })
})

describe("isValidPrice", () => {
  it("accepts well-formed prices and rejects what the API would reject", () => {
    expect(isValidPrice(graduated)).toBe(true)
    expect(isValidPrice({ model: "per_unit", unit_price: "abc", free_units: "0" })).toBe(false)
    expect(isValidPrice({ model: "package", package_size: "0", package_price: "1", free_units: "0" })).toBe(
      false,
    )
    const unordered = {
      ...graduated,
      tiers: [
        { up_to: "100", unit_price: "1", flat_fee: "0" },
        { up_to: "50", unit_price: "1", flat_fee: "0" },
        { up_to: null, unit_price: "1", flat_fee: "0" },
      ],
    }
    expect(isValidPrice(unordered)).toBe(false)
  })
})
