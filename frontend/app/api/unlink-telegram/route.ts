import { NextResponse } from "next/server"
import { authRequired, buildAuthHeaders } from "@/lib/server-auth"

export const dynamic = "force-dynamic"

export async function DELETE() {
  const headers = await buildAuthHeaders()
  if (authRequired() && !("Authorization" in headers)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
  }

  const base = process.env.API_BASE_URL
  if (!base) return NextResponse.json({ error: "API not configured" }, { status: 500 })

  const res = await fetch(`${base}/api/v1/unlink-telegram`, {
    method: "DELETE",
    headers: headers as HeadersInit,
    cache: "no-store",
  })
  return NextResponse.json({}, { status: res.status })
}
