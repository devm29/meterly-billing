import { http, HttpResponse } from "msw"
import { NextRequest } from "next/server"
import { describe, expect, it } from "vitest"

import { GET } from "@/app/api/meterly/[...path]/route"
import { server } from "@/test/server"

function call(path: string[]) {
  const request = new NextRequest(`http://console.test/api/meterly/${path.join("/")}?limit=5`)
  return GET(request, { params: Promise.resolve({ path }) })
}

describe("/api/meterly proxy", () => {
  it("forwards v1 paths with the admin key and the query string", async () => {
    let seen: { url: string; key: string | null } | undefined
    server.use(
      http.get("http://localhost:8107/v1/invoices", ({ request }) => {
        seen = { url: request.url, key: request.headers.get("x-api-key") }
        return HttpResponse.json({ items: [] }, { headers: { "x-request-id": "req-1", "set-cookie": "a=b" } })
      }),
    )

    const response = await call(["v1", "invoices"])

    expect(response.status).toBe(200)
    expect(seen).toEqual({ url: "http://localhost:8107/v1/invoices?limit=5", key: "mtr_admin_dev_only" })
    expect(response.headers.get("x-request-id")).toBe("req-1")
    expect(response.headers.get("set-cookie")).toBeNull()
  })

  it.each([[["healthz"]], [["v1", "..", "docs"]], [["v1", ".", "plans"]], [["v1", "plans?x"]]])(
    "refuses %j without calling the API",
    async (path) => {
      const response = await call(path)
      expect(response.status).toBe(404)
    },
  )

  it("answers 502 when the API is unreachable", async () => {
    server.use(http.get("http://localhost:8107/v1/plans", () => HttpResponse.error()))
    const response = await call(["v1", "plans"])
    expect(response.status).toBe(502)
  })
})
