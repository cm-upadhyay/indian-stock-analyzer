import { NextResponse } from "next/server"
import { LatestResponseSchema } from "@/lib/schemas"

export async function GET() {
  const baseUrl = process.env.API_BASE_URL
  const apiKey = process.env.API_KEY

  if (!baseUrl || !apiKey) {
    return NextResponse.json({ error: "API not configured" }, { status: 500 })
  }

  let res: Response
  try {
    res = await fetch(`${baseUrl}/latest`, {
      headers: { "X-API-Key": apiKey },
      next: { revalidate: 300 }, // cache for 5 min on the Vercel edge
    })
  } catch {
    return NextResponse.json({ error: "Failed to reach upstream API" }, { status: 502 })
  }

  if (!res.ok) {
    return NextResponse.json({ error: `Upstream error: ${res.status}` }, { status: res.status })
  }

  const raw = await res.json()
  const parsed = LatestResponseSchema.safeParse(raw)

  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid response shape from upstream" }, { status: 502 })
  }

  return NextResponse.json(parsed.data)
}
