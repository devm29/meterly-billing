import { beforeAll, describe, expect, it } from "vitest"
import { z } from "zod"

import {
  customerPageSchema,
  entitlementsSchema,
  invoicePageSchema,
  invoiceSchema,
  metricSchema,
  overviewSchema,
  planSchema,
  rerateSchema,
  simulationSchema,
  upcomingInvoiceSchema,
  usageSeriesSchema,
} from "@/lib/api/schemas"
import { server } from "@/test/server"

// Parses live API responses with the console's schemas, so drift between the Pydantic models
// and these hand-written Zod mirrors fails CI. Point it at a seeded API to run it:
//   METERLY_CONTRACT_API_URL=http://localhost:8107 pnpm test
const base = process.env.METERLY_CONTRACT_API_URL
const key = process.env.METERLY_ADMIN_API_KEY ?? "mtr_admin_dev_only"

async function call<T extends z.ZodType>(schema: T, path: string, body?: unknown): Promise<z.infer<T>> {
  const response = await fetch(`${base}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "x-api-key": key, "content-type": "application/json" },
    body: body === undefined ? null : JSON.stringify(body),
  })
  expect(response.status, path).toBeLessThan(300)
  const parsed = schema.safeParse(await response.json())
  if (!parsed.success) throw new Error(`${path}: ${z.prettifyError(parsed.error)}`)
  return parsed.data
}

describe.skipIf(!base)("API contract", () => {
  beforeAll(() => server.close())

  it("matches every payload the console reads", async () => {
    await call(overviewSchema, "/v1/analytics/overview")
    const plans = await call(z.array(planSchema), "/v1/plans")
    const metrics = await call(z.array(metricSchema), "/v1/metrics")
    const metric = metrics[0]
    if (metric) await call(usageSeriesSchema, `/v1/metrics/${metric.code}/usage?by_group=true`)

    const customers = await call(customerPageSchema, "/v1/customers?limit=10")
    const subscribed = customers.items.find((c) => c.subscription)
    expect(subscribed, "seed data with a subscribed customer").toBeDefined()
    if (!subscribed?.subscription) return
    await call(entitlementsSchema, `/v1/customers/${subscribed.external_id}/entitlements`)
    await call(upcomingInvoiceSchema, `/v1/subscriptions/${subscribed.subscription.id}/upcoming-invoice`)

    const invoices = await call(invoicePageSchema, "/v1/invoices?limit=5")
    for (const summary of invoices.items) await call(invoiceSchema, `/v1/invoices/${summary.id}`)

    const drafts = await call(invoicePageSchema, "/v1/invoices?status=draft&limit=1")
    const first = drafts.items[0]
    const draft = first ? await call(invoiceSchema, `/v1/invoices/${first.id}`) : null
    const usageCharge = draft?.charges.find((c) => c.metric_code !== null)
    if (draft && usageCharge) {
      await call(rerateSchema, `/v1/invoices/${draft.id}/rerate`, {
        overrides: { [usageCharge.key]: usageCharge.price },
        apply: false,
      })
    }

    const version = plans[0]?.versions[0]
    if (version) {
      await call(simulationSchema, "/v1/simulations", {
        customer_id: subscribed.external_id,
        plan_version_id: version.id,
        periods: 3,
      })
    }
  }, 30_000)
})
