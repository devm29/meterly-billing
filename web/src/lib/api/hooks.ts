"use client"

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { z } from "zod"

import { request, segment } from "@/lib/api/client"
import { pickDefaultMetric } from "@/lib/metrics"
import {
  customerPageSchema,
  customerSchema,
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
  type InvoiceStatus,
  type Metric,
  type PlanTerms,
  type PriceModel,
} from "@/lib/api/schemas"

export const keys = {
  overview: ["overview"] as const,
  metrics: ["metrics"] as const,
  metricUsage: (code: string, days: number) => ["metric-usage", code, days] as const,
  customers: (q: string, offset: number) => ["customers", q, offset] as const,
  customer: (id: string) => ["customer", id] as const,
  customerUsage: (id: string, metric: string, days: number, granularity: string) =>
    ["customer-usage", id, metric, days, granularity] as const,
  customerInvoices: (id: string) => ["customer-invoices", id] as const,
  entitlements: (id: string) => ["entitlements", id] as const,
  upcoming: (subscriptionId: string) => ["upcoming", subscriptionId] as const,
  invoices: (status: string, offset: number) => ["invoices", status, offset] as const,
  invoice: (id: string) => ["invoice", id] as const,
  plans: ["plans"] as const,
}

export function useOverview() {
  return useQuery({
    queryKey: keys.overview,
    queryFn: ({ signal }) => request(overviewSchema, "/v1/analytics/overview", { signal }),
  })
}

export function useMetrics() {
  return useQuery({
    queryKey: keys.metrics,
    queryFn: ({ signal }) => request(z.array(metricSchema), "/v1/metrics", { signal }),
    staleTime: 5 * 60_000,
  })
}

export function useDefaultMetric(): {
  metric: Metric | undefined
  loaded: boolean
  error: Error | null
} {
  const metrics = useMetrics()
  return {
    metric: metrics.data ? pickDefaultMetric(metrics.data) : undefined,
    loaded: metrics.data !== undefined,
    error: metrics.error,
  }
}

export function useMetricUsage(code: string | undefined, days: number) {
  return useQuery({
    queryKey: keys.metricUsage(code ?? "", days),
    queryFn: ({ signal }) =>
      request(usageSeriesSchema, `/v1/metrics/${segment(code ?? "")}/usage`, {
        query: { days, by_group: true },
        signal,
      }),
    enabled: Boolean(code),
    placeholderData: keepPreviousData,
  })
}

export function useCustomers(q: string, offset: number, limit = 25) {
  return useQuery({
    queryKey: keys.customers(q, offset),
    queryFn: ({ signal }) =>
      request(customerPageSchema, "/v1/customers", {
        query: { q: q || undefined, offset, limit },
        signal,
      }),
    placeholderData: keepPreviousData,
  })
}

export function useCustomer(id: string) {
  return useQuery({
    queryKey: keys.customer(id),
    queryFn: ({ signal }) => request(customerSchema, `/v1/customers/${segment(id)}`, { signal }),
  })
}

export function useCustomerUsage(
  id: string,
  metric: string | undefined,
  days: number,
  granularity: "hour" | "day",
) {
  return useQuery({
    queryKey: keys.customerUsage(id, metric ?? "", days, granularity),
    queryFn: ({ signal }) =>
      request(usageSeriesSchema, `/v1/customers/${segment(id)}/usage`, {
        query: { metric, days, granularity, by_group: true },
        signal,
      }),
    enabled: Boolean(metric),
    placeholderData: keepPreviousData,
  })
}

export function useCustomerInvoices(id: string, limit = 12) {
  return useQuery({
    queryKey: keys.customerInvoices(id),
    queryFn: ({ signal }) =>
      request(invoicePageSchema, "/v1/invoices", {
        query: { customer_id: id, limit },
        signal,
      }),
  })
}

export function useEntitlements(id: string) {
  return useQuery({
    queryKey: keys.entitlements(id),
    queryFn: ({ signal }) =>
      request(entitlementsSchema, `/v1/customers/${segment(id)}/entitlements`, {
        signal,
      }),
    refetchInterval: 15_000,
  })
}

export function useUpcomingInvoice(subscriptionId: string | undefined) {
  return useQuery({
    queryKey: keys.upcoming(subscriptionId ?? ""),
    queryFn: ({ signal }) =>
      request(upcomingInvoiceSchema, `/v1/subscriptions/${segment(subscriptionId ?? "")}/upcoming-invoice`, {
        signal,
      }),
    enabled: Boolean(subscriptionId),
  })
}

export function useInvoices(status: InvoiceStatus | "all", offset: number, limit = 25) {
  return useQuery({
    queryKey: keys.invoices(status, offset),
    queryFn: ({ signal }) =>
      request(invoicePageSchema, "/v1/invoices", {
        query: { status: status === "all" ? undefined : status, offset, limit },
        signal,
      }),
    placeholderData: keepPreviousData,
  })
}

export function useInvoice(id: string) {
  return useQuery({
    queryKey: keys.invoice(id),
    queryFn: ({ signal }) => request(invoiceSchema, `/v1/invoices/${segment(id)}`, { signal }),
  })
}

export function usePlans() {
  return useQuery({
    queryKey: keys.plans,
    queryFn: ({ signal }) => request(z.array(planSchema), "/v1/plans", { signal }),
    staleTime: 60_000,
  })
}

export function useFinalizeInvoice(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => request(invoiceSchema, `/v1/invoices/${segment(id)}/finalize`, { method: "POST" }),
    onSuccess: (invoice) => {
      client.setQueryData(keys.invoice(id), invoice)
      void client.invalidateQueries({ queryKey: ["invoices"] })
      void client.invalidateQueries({ queryKey: keys.overview })
    },
  })
}

export function useRerate(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { overrides: Record<string, PriceModel>; apply: boolean }) =>
      request(rerateSchema, `/v1/invoices/${segment(id)}/rerate`, { method: "POST", body: input }),
    onSuccess: (result) => {
      if (result.applied) {
        void client.invalidateQueries({ queryKey: keys.invoice(id) })
        void client.invalidateQueries({ queryKey: ["invoices"] })
      }
    },
  })
}

export type SimulationInput =
  | { customer_id: string; periods: number; plan_version_id: string }
  | { customer_id: string; periods: number; terms: PlanTerms }

export function useSimulation() {
  return useMutation({
    mutationFn: (input: SimulationInput) =>
      request(simulationSchema, "/v1/simulations", { method: "POST", body: input }),
  })
}
