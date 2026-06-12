import { NextResponse } from "next/server"
import { AccuracyResponseSchema } from "@/lib/schemas"

export async function GET() {
  const baseUrl = process.env.API_BASE_URL
  if (!baseUrl) {
    return NextResponse.json({ error: "API not configured" }, { status: 500 })
  }

  // Accuracy is the public trust page (PRD) — no session required.
  let res: Response
  try {
    res = await fetch(`${baseUrl}/api/v1/accuracy`, {
      next: { revalidate: 3600 },
    })
  } catch {
    return NextResponse.json({ error: "Failed to reach upstream API" }, { status: 502 })
  }

  if (!res.ok) {
    return NextResponse.json({ error: `Upstream error: ${res.status}` }, { status: res.status })
  }

  const parsed = AccuracyResponseSchema.safeParse(await res.json())
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid response shape" }, { status: 502 })
  }

  return NextResponse.json(parsed.data)
}
