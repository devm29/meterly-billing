// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CustomerView } from "@/components/customers/customer-view"
import type { Customer } from "@/lib/api/schemas"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }))

afterEach(cleanup)

const canceled: Customer = {
  id: "cus-1",
  external_id: "ember",
  name: "Ember Energy",
  email: null,
  currency: "USD",
  created_at: "2026-04-01T00:00:00Z",
  plan_name: "Growth",
  status: "canceled",
  fixed_monthly: { amount: "249.00", currency: "USD" },
  subscription: {
    id: "sub-1",
    customer_id: "ember",
    status: "canceled",
    interval: "month",
    billing_anchor: "2026-04-28",
    started_on: "2026-04-28",
    trial_ends_on: "2026-05-12",
    ends_on: "2026-07-12",
    billed_through: "2026-07-12",
    current_period_start: "2026-07-12",
    current_period_end: "2026-08-12",
    phases: [
      {
        plan_version_id: "pv-1",
        plan_code: "growth",
        plan_name: "Growth",
        version: 2,
        starts_on: "2026-04-28",
        ends_on: "2026-07-12",
      },
    ],
  },
}

describe("CustomerView", () => {
  it("settles the billing summary for a canceled subscription instead of loading forever", async () => {
    server.use(
      http.get("*/api/meterly/v1/customers/ember", () => HttpResponse.json(canceled)),
      http.get("*/api/meterly/v1/invoices", () =>
        HttpResponse.json({ items: [], total: 0, limit: 12, offset: 0 }),
      ),
      http.get("*/api/meterly/v1/customers/ember/entitlements", () =>
        HttpResponse.json({ customer_id: "ember", entitlements: [] }),
      ),
      http.get("*/api/meterly/v1/metrics", () => HttpResponse.json([])),
    )
    renderWithClient(<CustomerView id="ember" />)

    const summary = await screen.findByRole("region", { name: "Billing summary" })
    expect(await within(summary).findByText("Ended Jul 12, 2026")).toBeTruthy()
    expect(within(summary).getByText("no active subscription")).toBeTruthy()
    expect(summary.querySelector('[data-slot="skeleton"]')).toBeNull()
  })
})
