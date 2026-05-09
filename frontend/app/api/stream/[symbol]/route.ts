// SSE proxy — forwards the FastAPI /stream/{symbol} SSE stream to the browser.
// The browser's EventSource connects here (same origin); we relay upstream events.

export const dynamic = "force-dynamic"

import { authRequired, buildAuthHeaders } from "@/lib/server-auth"

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ symbol: string }> },
) {
  const { symbol } = await params
  const baseUrl = process.env.API_BASE_URL
  if (!baseUrl) {
    return new Response("API not configured", { status: 500 })
  }

  const authHeaders = await buildAuthHeaders()
  if (!Object.keys(authHeaders).length && authRequired()) {
    return new Response("Unauthorized", { status: 401 })
  }

  let upstream: Response
  try {
    upstream = await fetch(
      `${baseUrl}/api/v1/stream/${encodeURIComponent(symbol)}`,
      {
        headers: { ...authHeaders, Accept: "text/event-stream" },
        // @ts-expect-error — Next.js fetch supports duplex
        duplex: "half",
      },
    )
  } catch {
    return new Response("Failed to reach upstream API", { status: 502 })
  }

  if (!upstream.ok || !upstream.body) {
    return new Response(`Upstream error: ${upstream.status}`, { status: upstream.ok ? 502 : upstream.status })
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  })
}
