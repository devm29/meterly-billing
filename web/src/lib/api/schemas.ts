import { z } from "zod"

export const currencySchema = z.enum(["USD", "EUR", "GBP", "JPY"])
export type Currency = z.infer<typeof currencySchema>

export const moneySchema = z.object({ amount: z.string(), currency: currencySchema })
export type Money = z.infer<typeof moneySchema>

const decimal = z.string()

export const revenueMonthSchema = z.object({
  month: z.string(),
  fixed: moneySchema,
  usage: moneySchema,
  total: moneySchema,
  invoices: z.number().int(),
})

export const overviewSchema = z.object({
  currency: currencySchema,
  mrr: moneySchema,
  mrr_previous: moneySchema,
  contracted_mrr: moneySchema,
  usage_share: decimal,
  active_customers: z.number().int(),
  trialing_customers: z.number().int(),
  arpa: moneySchema,
  draft_invoices: z.number().int(),
  draft_total: moneySchema,
  revenue: z.array(revenueMonthSchema),
  top_customers: z.array(z.object({ customer_id: z.string(), name: z.string(), revenue: moneySchema })),
})
export type Overview = z.infer<typeof overviewSchema>

export const aggregationSchema = z.enum(["count", "sum", "max", "unique_count", "latest"])

export const metricSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  event_code: z.string(),
  aggregation: aggregationSchema,
  field: z.string().nullable(),
  group_by: z.array(z.string()),
  unit: z.string(),
})
export type Metric = z.infer<typeof metricSchema>

export const usageSeriesSchema = z.object({
  metric: metricSchema,
  granularity: z.enum(["hour", "day"]),
  start: z.string(),
  end: z.string(),
  series: z.array(z.string()),
  points: z.array(z.object({ t: z.string(), values: z.record(z.string(), decimal) })),
  total: decimal,
})
export type UsageSeries = z.infer<typeof usageSeriesSchema>

const tierSchema = z.object({
  up_to: decimal.nullable(),
  unit_price: decimal,
  flat_fee: decimal,
})
export type Tier = z.infer<typeof tierSchema>

export const priceModelSchema = z.discriminatedUnion("model", [
  z.object({ model: z.literal("flat"), amount: decimal }),
  z.object({ model: z.literal("per_unit"), unit_price: decimal, free_units: decimal }),
  z.object({
    model: z.literal("package"),
    package_size: decimal,
    package_price: decimal,
    free_units: decimal,
  }),
  z.object({ model: z.literal("volume"), tiers: z.array(tierSchema), free_units: decimal }),
  z.object({ model: z.literal("graduated"), tiers: z.array(tierSchema), free_units: decimal }),
])
export type PriceModel = z.infer<typeof priceModelSchema>

export const chargeSchema = z.object({
  key: z.string(),
  name: z.string(),
  metric_code: z.string().nullable(),
  price: priceModelSchema,
  minimum_amount: decimal.nullable(),
})
export type Charge = z.infer<typeof chargeSchema>

export const planTermsSchema = z.object({
  currency: currencySchema,
  interval: z.enum(["month", "year"]),
  trial_days: z.number().int(),
  minimum_commitment: decimal.nullable(),
  charges: z.array(chargeSchema),
  entitlements: z.array(
    z.object({
      feature: z.string(),
      name: z.string(),
      metric_code: z.string().nullable(),
      limit: decimal.nullable(),
    }),
  ),
})
export type PlanTerms = z.infer<typeof planTermsSchema>

export const planSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  versions: z.array(
    z.object({
      id: z.string(),
      version: z.number().int(),
      created_at: z.string(),
      terms: planTermsSchema,
      fixed_amount: moneySchema,
    }),
  ),
})
export type Plan = z.infer<typeof planSchema>

export const subscriptionStatusSchema = z.enum(["active", "trialing", "canceled", "scheduled"])
export type SubscriptionStatus = z.infer<typeof subscriptionStatusSchema>

export const subscriptionSchema = z.object({
  id: z.string(),
  customer_id: z.string(),
  status: subscriptionStatusSchema,
  interval: z.enum(["month", "year"]),
  billing_anchor: z.string(),
  started_on: z.string(),
  trial_ends_on: z.string().nullable(),
  ends_on: z.string().nullable(),
  billed_through: z.string(),
  current_period_start: z.string(),
  current_period_end: z.string(),
  phases: z.array(
    z.object({
      plan_version_id: z.string(),
      plan_code: z.string(),
      plan_name: z.string(),
      version: z.number().int(),
      starts_on: z.string(),
      ends_on: z.string().nullable(),
    }),
  ),
})
export type Subscription = z.infer<typeof subscriptionSchema>

export const customerSchema = z.object({
  id: z.string(),
  external_id: z.string(),
  name: z.string(),
  email: z.string().nullable(),
  currency: currencySchema,
  created_at: z.string(),
  plan_name: z.string().nullable(),
  status: z.union([subscriptionStatusSchema, z.literal("none")]),
  fixed_monthly: moneySchema.nullable(),
  subscription: subscriptionSchema.nullable(),
})
export type Customer = z.infer<typeof customerSchema>

export const customerPageSchema = z.object({
  items: z.array(customerSchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
})

export const invoiceStatusSchema = z.enum(["draft", "finalized", "void"])
export type InvoiceStatus = z.infer<typeof invoiceStatusSchema>

export const invoiceSummarySchema = z.object({
  id: z.string(),
  number: z.string().nullable(),
  status: invoiceStatusSchema,
  customer_id: z.string(),
  customer_name: z.string(),
  currency: currencySchema,
  period_start: z.string(),
  period_end: z.string(),
  total: moneySchema,
  created_at: z.string(),
  finalized_at: z.string().nullable(),
})
export type InvoiceSummary = z.infer<typeof invoiceSummarySchema>

export const invoicePageSchema = z.object({
  items: z.array(invoiceSummarySchema),
  total: z.number().int(),
  limit: z.number().int(),
  offset: z.number().int(),
})

const componentSchema = z.object({
  label: z.string(),
  units: decimal,
  unit_price: decimal.nullable(),
  flat_fee: decimal,
  exact: decimal,
  amount: moneySchema,
})
export type PriceComponent = z.infer<typeof componentSchema>

export const lineKindSchema = z.enum(["fixed", "usage", "minimum"])

export const invoiceLineSchema = z.object({
  key: z.string(),
  kind: lineKindSchema,
  charge_key: z.string(),
  description: z.string(),
  metric_code: z.string().nullable(),
  phase_start: z.string(),
  phase_end: z.string(),
  quantity: decimal,
  billable_quantity: decimal,
  amount: moneySchema,
  details: z.object({
    exact: decimal,
    proration: decimal,
    components: z.array(componentSchema),
    groups: z.array(
      z.object({
        dimensions: z.record(z.string(), z.string().nullable()),
        quantity: decimal,
        amount: moneySchema,
      }),
    ),
  }),
})
export type InvoiceLine = z.infer<typeof invoiceLineSchema>

export const invoiceSchema = invoiceSummarySchema.extend({
  subtotal: moneySchema,
  lines: z.array(invoiceLineSchema),
  price_overrides: z.record(z.string(), priceModelSchema),
  charges: z.array(chargeSchema),
})
export type Invoice = z.infer<typeof invoiceSchema>

export const upcomingInvoiceSchema = z.object({
  subscription_id: z.string(),
  currency: currencySchema,
  period_start: z.string(),
  period_end: z.string(),
  as_of: z.string(),
  lines: z.array(invoiceLineSchema),
  subtotal: moneySchema,
})
export type UpcomingInvoice = z.infer<typeof upcomingInvoiceSchema>

export const entitlementSchema = z.object({
  feature: z.string(),
  name: z.string(),
  allowed: z.boolean(),
  reason: z.string(),
  metric_code: z.string().nullable(),
  limit: decimal.nullable(),
  used: decimal.nullable(),
  remaining: decimal.nullable(),
  period_start: z.string().nullable(),
  period_end: z.string().nullable(),
  plan_code: z.string().nullable(),
  cached: z.boolean(),
})
export type Entitlement = z.infer<typeof entitlementSchema>

export const entitlementsSchema = z.object({
  customer_id: z.string(),
  entitlements: z.array(entitlementSchema),
})

export const rerateSchema = z.object({
  applied: z.boolean(),
  diff: z.object({
    lines: z.array(
      z.object({
        key: z.string(),
        description: z.string(),
        before: moneySchema.nullable(),
        after: moneySchema.nullable(),
        delta: moneySchema,
      }),
    ),
    subtotal_before: moneySchema,
    subtotal_after: moneySchema,
    delta: moneySchema,
  }),
})
export type Rerate = z.infer<typeof rerateSchema>

export const simulationSchema = z.object({
  customer_id: z.string(),
  currency: currencySchema,
  current_plan: z.string(),
  candidate_plan: z.string(),
  periods: z.array(
    z.object({
      period_start: z.string(),
      period_end: z.string(),
      in_progress: z.boolean(),
      actual: moneySchema,
      candidate: moneySchema,
      delta: moneySchema,
      candidate_lines: z.array(invoiceLineSchema),
    }),
  ),
  total_actual: moneySchema,
  total_candidate: moneySchema,
  delta: moneySchema,
  delta_ratio: decimal.nullable(),
})
export type Simulation = z.infer<typeof simulationSchema>

export const apiErrorSchema = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
})
