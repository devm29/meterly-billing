import type { Money } from "@/lib/api/schemas"

const moneyFormatters = new Map<string, Intl.NumberFormat>()

function moneyFormatter(currency: string, compact: boolean): Intl.NumberFormat {
  const key = `${currency}:${compact}`
  let formatter = moneyFormatters.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      ...(compact ? { notation: "compact", maximumFractionDigits: 1 } : {}),
    })
    moneyFormatters.set(key, formatter)
  }
  return formatter
}

export function formatMoney(money: Money, options: { compact?: boolean } = {}): string {
  return moneyFormatter(money.currency, options.compact ?? false).format(Number(money.amount))
}

export function formatAmount(value: number, currency: string, compact = false): string {
  return moneyFormatter(currency, compact).format(value)
}

const priceFormatters = new Map<string, Intl.NumberFormat>()

/** Unit prices go below the minor unit ($0.002 per call), so they keep their own precision. */
export function formatPrice(value: string | number, currency: string): string {
  let formatter = priceFormatters.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 10,
    })
    priceFormatters.set(currency, formatter)
  }
  return formatter.format(typeof value === "number" ? value : Number(value))
}

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 })
const compactFormat = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumFractionDigits: 1,
})

export function formatNumber(value: string | number, compact = false): string {
  const n = typeof value === "number" ? value : Number(value)
  return (compact ? compactFormat : numberFormat).format(n)
}

export function formatPercent(ratio: number, signed = false): string {
  const formatted = new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
    signDisplay: signed ? "exceptZero" : "auto",
  }).format(ratio)
  return formatted
}

function parseDay(iso: string): Date {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number)
  return new Date(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1))
}

const dayFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
})
const shortDayFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
})
const monthFormat = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" })
const hourFormat = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  timeZone: "UTC",
})

export const formatDay = (iso: string) => dayFormat.format(parseDay(iso))
export const formatShortDay = (iso: string) => shortDayFormat.format(parseDay(iso))
export const formatMonth = (iso: string) => monthFormat.format(parseDay(iso))
export const formatHour = (iso: string) => hourFormat.format(new Date(iso))

export function formatPeriod(start: string, endExclusive: string): string {
  const end = parseDay(endExclusive)
  end.setUTCDate(end.getUTCDate() - 1)
  return `${shortDayFormat.format(parseDay(start))} – ${dayFormat.format(end)}`
}

export function formatPeriodShort(start: string, endExclusive: string): string {
  const end = parseDay(endExclusive)
  end.setUTCDate(end.getUTCDate() - 1)
  return `${shortDayFormat.format(parseDay(start))} – ${shortDayFormat.format(end)}`
}
