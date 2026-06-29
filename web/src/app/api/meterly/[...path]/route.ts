import { NextResponse, type NextRequest } from "next/server"

import { serverEnv } from "@/lib/server-env"

// The browser never sees the admin key: every console request goes through this handler,
// which only forwards to the versioned API and attaches the key server-side.
const SEGMENT = /^[A-Za-z0-9._:-]+$/
const PASSTHROUGH_HEADERS = ["content-type", "content-disposition", "x-request-id"] as const

type Context = { params: Promise<{ path: string[] }> }

async function forward(request: NextRequest, { params }: Context): Promise<Response> {
  const { path } = await params
  if (path[0] !== "v1" || !path.every((segment) => SEGMENT.test(segment))) {
    return NextResponse.json({ error: { code: "not_found", message: "unknown API route" } }, { status: 404 })
  }
  const env = serverEnv()
  if (env.adminKey === null) {
    return NextResponse.json(
      { error: { code: "misconfigured", message: "METERLY_ADMIN_API_KEY is not set" } },
      { status: 500 },
    )
  }

  const target = new URL(path.map(encodeURIComponent).join("/"), `${env.apiUrl}/`)
  target.search = request.nextUrl.search
  const headers = new Headers({ "x-api-key": env.adminKey })
  const contentType = request.headers.get("content-type")
  if (contentType) headers.set("content-type", contentType)

  let upstream: Response
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "POST" ? await request.arrayBuffer() : null,
      cache: "no-store",
    })
  } catch {
    return NextResponse.json(
      { error: { code: "api_unreachable", message: "The billing API is not reachable" } },
      { status: 502 },
    )
  }

  const responseHeaders = new Headers()
  for (const name of PASSTHROUGH_HEADERS) {
    const value = upstream.headers.get(name)
    if (value) responseHeaders.set(name, value)
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders })
}

export const GET = forward
export const POST = forward
export const dynamic = "force-dynamic"
