import { NextResponse } from "next/server"
import { auth } from "@/auth"

/**
 * POST /api/subscribe
 *
 * Creates a Razorpay subscription for the signed-in user with notes.user_id
 * set to the Google OAuth sub claim — the field the webhook handler reads to
 * link Razorpay events back to the DynamoDB user record.
 *
 * Returns { subscription_id, key_id } for the client to open Razorpay Checkout.
 */
export async function POST() {
  const session = await auth()

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Sign in required" }, { status: 401 })
  }

  const keyId = process.env.RAZORPAY_KEY_ID
  const keySecret = process.env.RAZORPAY_KEY_SECRET
  const planId = process.env.RAZORPAY_PLAN_ID

  if (!keyId || !keySecret || !planId) {
    return NextResponse.json({ error: "Payments not configured" }, { status: 503 })
  }

  const credentials = Buffer.from(`${keyId}:${keySecret}`).toString("base64")

  const res = await fetch("https://api.razorpay.com/v1/subscriptions", {
    method: "POST",
    headers: {
      Authorization: `Basic ${credentials}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      plan_id: planId,
      total_count: 12, // 12 monthly billing cycles
      quantity: 1,
      notes: { user_id: session.user.id },
    }),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const msg =
      (err as { error?: { description?: string } }).error?.description ??
      "Could not create subscription"
    return NextResponse.json({ error: msg }, { status: 502 })
  }

  const sub = (await res.json()) as { id: string }
  return NextResponse.json({ subscription_id: sub.id, key_id: keyId })
}
