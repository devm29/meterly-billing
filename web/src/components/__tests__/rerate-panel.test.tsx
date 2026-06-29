// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { useState } from "react"
import { afterEach, describe, expect, it } from "vitest"

import { DiffTable, ReratePanel } from "@/components/invoices/rerate-panel"
import type { Rerate } from "@/lib/api/schemas"
import { draftInvoice, rerateDiff } from "@/test/fixtures"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

function Harness() {
  const [diff, setDiff] = useState<Rerate["diff"] | null>(null)
  return (
    <>
      <ReratePanel invoice={draftInvoice} diff={diff} onDiff={setDiff} />
      {diff ? <DiffTable diff={diff} /> : null}
    </>
  )
}

afterEach(cleanup)

describe("ReratePanel", () => {
  it("previews a diff for the edited usage charge before anything is applied", async () => {
    const bodies: unknown[] = []
    server.use(
      http.post("*/api/meterly/v1/invoices/inv-1/rerate", async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json(rerateDiff)
      }),
    )
    const user = userEvent.setup()
    renderWithClient(<Harness />)

    expect(screen.getByText(/Currently \$0\.01 per unit/)).toBeTruthy()
    const apply = screen.getByRole("button", { name: "Apply to draft" })
    expect(apply.hasAttribute("disabled")).toBe(true)

    const unitPrice = screen.getByLabelText("Unit price")
    await user.clear(unitPrice)
    await user.type(unitPrice, "0.005")
    await user.click(screen.getByRole("button", { name: "Preview diff" }))

    await waitFor(() => expect(screen.getByText("-$51.50", { selector: "tfoot td" })).toBeTruthy())
    expect(bodies).toEqual([
      {
        overrides: { api_calls: { model: "per_unit", unit_price: "0.005", free_units: "0" } },
        apply: false,
      },
    ])
    expect(apply.hasAttribute("disabled")).toBe(false)
  })

  it("keeps the preview button disabled while the price is not a number", async () => {
    const user = userEvent.setup()
    renderWithClient(<Harness />)
    const unitPrice = screen.getByLabelText("Unit price")
    await user.clear(unitPrice)
    await user.type(unitPrice, "abc")
    expect(screen.getByRole("button", { name: "Preview diff" }).hasAttribute("disabled")).toBe(true)
  })
})
