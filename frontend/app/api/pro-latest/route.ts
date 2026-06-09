import { NextResponse } from "next/server"
import { LatestResponseSchema } from "@/lib/schemas"
import { authRequired, buildAuthHeaders } from "@/lib/server-auth"

export async function GET() {
  const baseUrl = process.env.API_BASE_URL
  if (!baseUrl) {
    return NextResponse.json({ error: "API not configured" }, { status: 500 })
  }

  const authHeaders = await buildAuthHeaders()
  if (!Object.keys(authHeaders).length && authRequired()) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  let res: Response
  try {
    res = await fetch(`${baseUrl}/api/v1/pro/latest`, {
      headers: authHeaders,
      cache: "no-store",
    })
  } catch {
    return NextResponse.json({ error: "Failed to reach upstream API" }, { status: 502 })
  }

  if (!res.ok) {
    return NextResponse.json({ error: `Upstream error: ${res.status}` }, { status: res.status })
  }

  const parsed = LatestResponseSchema.safeParse(await res.json())
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid response shape from upstream" }, { status: 502 })
  }

  return NextResponse.json(parsed.data)
}
