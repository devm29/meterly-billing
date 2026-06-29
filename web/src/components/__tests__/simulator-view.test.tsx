// @vitest-environment jsdom
import { cleanup, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { http, HttpResponse } from "msw"
import { afterEach, describe, expect, it } from "vitest"

import { SimulatorView } from "@/components/simulator/simulator-view"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

afterEach(cleanup)

describe("SimulatorView", () => {
  it("searches customers on the server instead of loading a fixed page", async () => {
    const queries: (string | null)[] = []
    server.use(
      http.get("*/api/meterly/v1/customers", ({ request }) => {
        queries.push(new URL(request.url).searchParams.get("q"))
        return HttpResponse.json({ items: [], total: 0, limit: 25, offset: 0 })
      }),
      http.get("*/api/meterly/v1/plans", () => HttpResponse.json([])),
    )
    const user = userEvent.setup()
    renderWithClient(<SimulatorView />)

    await user.type(screen.getByRole("searchbox", { name: "Customer" }), "northwind")

    await waitFor(() => expect(queries).toContain("northwind"))
    expect(queries[0]).toBeNull()
    expect(screen.getByRole("button", { name: "Simulate" }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByText("See what a customer would pay")).toBeTruthy()
  })
})
