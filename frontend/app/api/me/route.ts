import { NextResponse } from "next/server"
import { buildAuthHeaders, authRequired } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

export async function GET() {
  const headers = await buildAuthHeaders()

  if (authRequired() && !("Authorization" in headers)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const base = process.env.API_BASE_URL
  const res = await fetch(`${base}/me`, {
    headers: headers as HeadersInit,
    cache: "no-store",
  })

  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
