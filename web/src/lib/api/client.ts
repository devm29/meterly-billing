import type { z } from "zod"

import { apiErrorSchema } from "@/lib/api/schemas"

const API_BASE = "/api/meterly"

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

type Query = Record<string, string | number | boolean | undefined>

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, String(value))
  }
  const search = params.toString()
  return `${API_BASE}${path}${search ? `?${search}` : ""}`
}

export function segment(value: string): string {
  return encodeURIComponent(value)
}

export async function request<T extends z.ZodType>(
  schema: T,
  path: string,
  init: { method?: "GET" | "POST"; body?: unknown; query?: Query; signal?: AbortSignal } = {},
): Promise<z.infer<T>> {
  const response = await fetch(buildUrl(path, init.query), {
    method: init.method ?? "GET",
    headers: init.body === undefined ? {} : { "Content-Type": "application/json" },
    body: init.body === undefined ? null : JSON.stringify(init.body),
    signal: init.signal ?? null,
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(payload)
    throw new ApiError(
      response.status,
      parsed.success ? parsed.data.error.code : "http_error",
      parsed.success ? parsed.data.error.message : `Request failed with ${response.status}`,
    )
  }
  return schema.parse(payload)
}

export function apiUrl(path: string): string {
  return buildUrl(path)
}
