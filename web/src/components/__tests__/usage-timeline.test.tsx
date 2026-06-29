// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react"
import { http, HttpResponse } from "msw"
import { afterEach, describe, expect, it } from "vitest"

import { UsageTimeline } from "@/components/customers/usage-timeline"
import { renderWithClient } from "@/test/render"
import { server } from "@/test/server"

afterEach(cleanup)

describe("UsageTimeline", () => {
  it("shows an error with a retry instead of an endless skeleton", async () => {
    server.use(
      http.get("*/api/meterly/v1/metrics", () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "something went wrong on our side" } },
          { status: 500 },
        ),
      ),
    )
    renderWithClient(<UsageTimeline customerId="acme" />)

    const alert = await screen.findByRole("alert")
    expect(alert.textContent).toContain("something went wrong on our side")
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy()
  })

  it("explains an empty metric catalog", async () => {
    server.use(http.get("*/api/meterly/v1/metrics", () => HttpResponse.json([])))
    renderWithClient(<UsageTimeline customerId="acme" />)
    expect(await screen.findByText("No billable metrics")).toBeTruthy()
  })
})
