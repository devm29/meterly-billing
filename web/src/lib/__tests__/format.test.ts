import { describe, expect, it } from "vitest"

import { formatMoney, formatPeriod, formatPeriodShort } from "@/lib/format"

describe("formatMoney", () => {
  it("formats decimal strings without float drift", () => {
    expect(formatMoney({ amount: "1234.50", currency: "USD" })).toBe("$1,234.50")
    expect(formatMoney({ amount: "-0.10", currency: "USD" })).toBe("-$0.10")
  })

  it("respects zero-decimal currencies", () => {
    expect(formatMoney({ amount: "1500", currency: "JPY" })).toBe("¥1,500")
  })
})

describe("formatPeriod", () => {
  it("renders the exclusive end date as the last billed day", () => {
    expect(formatPeriod("2026-03-01", "2026-04-01")).toBe("Mar 1 – Mar 31, 2026")
    expect(formatPeriodShort("2026-01-31", "2026-02-28")).toBe("Jan 31 – Feb 27")
  })
})
