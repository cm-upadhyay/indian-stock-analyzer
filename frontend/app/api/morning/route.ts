import { NextResponse } from "next/server"
import { MorningResponseSchema } from "@/lib/schemas"
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
    res = await fetch(`${baseUrl}/morning`, {
      headers: authHeaders,
      next: { revalidate: 300 },
    })
  } catch {
    return NextResponse.json({ error: "Failed to reach upstream API" }, { status: 502 })
  }

  if (!res.ok) {
    return NextResponse.json({ error: `Upstream error: ${res.status}` }, { status: res.status })
  }

  const parsed = MorningResponseSchema.safeParse(await res.json())
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid response shape" }, { status: 502 })
  }

  return NextResponse.json(parsed.data)
}
