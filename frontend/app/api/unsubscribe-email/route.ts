import { NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("token")
  if (!token) {
    return NextResponse.json({ error: "Missing token" }, { status: 400 })
  }

  const baseUrl = process.env.API_BASE_URL
  if (!baseUrl) {
    return NextResponse.json({ error: "API not configured" }, { status: 500 })
  }

  let res: Response
  try {
    res = await fetch(`${baseUrl}/api/v1/unsubscribe-email?token=${encodeURIComponent(token)}`, {
      cache: "no-store",
    })
  } catch {
    return NextResponse.json({ error: "Failed to reach upstream API" }, { status: 502 })
  }

  if (!res.ok) {
    return NextResponse.json({ error: `Unsubscribe failed: ${res.status}` }, { status: res.status })
  }

  return NextResponse.json({ status: "unsubscribed" })
}
