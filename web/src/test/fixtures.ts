import type { Invoice, Rerate } from "@/lib/api/schemas"

const usd = (amount: string) => ({ amount, currency: "USD" as const })

export const draftInvoice: Invoice = {
  id: "inv-1",
  number: null,
  status: "draft",
  customer_id: "acme",
  customer_name: "Acme Corp",
  currency: "USD",
  period_start: "2026-03-01",
  period_end: "2026-04-01",
  total: usd("152.00"),
  created_at: "2026-04-01T03:00:00Z",
  finalized_at: null,
  subtotal: usd("152.00"),
  price_overrides: {},
  charges: [
    {
      key: "platform",
      name: "Platform fee",
      metric_code: null,
      price: { model: "flat", amount: "49" },
      minimum_amount: null,
    },
    {
      key: "api_calls",
      name: "API calls",
      metric_code: "api_calls",
      price: { model: "per_unit", unit_price: "0.01", free_units: "0" },
      minimum_amount: null,
    },
  ],
  lines: [],
}

export const rerateDiff: Rerate = {
  applied: false,
  diff: {
    lines: [
      {
        key: "2026-03-01:api_calls:usage",
        description: "API calls",
        before: usd("103.00"),
        after: usd("51.50"),
        delta: usd("-51.50"),
      },
    ],
    subtotal_before: usd("152.00"),
    subtotal_after: usd("100.50"),
    delta: usd("-51.50"),
  },
}
