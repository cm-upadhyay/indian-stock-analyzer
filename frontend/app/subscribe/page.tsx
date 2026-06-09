"use client"

import Script from "next/script"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { signIn, useSession } from "next-auth/react"
import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { fetchMe } from "@/lib/api"

declare global {
  interface Window {
    Razorpay: new (opts: Record<string, unknown>) => { open(): void }
  }
}

const FREE_FEATURES = [
  "Up to 10 daily picks on the web",
  "Full BUY / HOLD / SELL verdicts with reasoning",
  "5 stocks/day via Telegram (no account required)",
  "Accuracy history page",
]

const PRO_FEATURES = [
  "All 30+ daily picks on the web",
  "Morning follow-up notes every weekday",
  "Telegram — all verdicts + morning notes",
  "Live SSE streaming during analysis runs",
]

export default function SubscribePage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    enabled: status === "authenticated",
    retry: false,
  })

  const isPro = me?.subscription_status === "active"

  async function handleSubscribe() {
    if (status !== "authenticated") {
      signIn("google", { callbackUrl: "/subscribe" })
      return
    }
    if (!window.Razorpay) {
      setError("Payment system still loading — please try again in a moment.")
      return
    }
    setLoading(true)
    setError("")
    try {
      const res = await fetch("/api/subscribe", { method: "POST" })
      const data = (await res.json()) as {
        subscription_id?: string
        key_id?: string
        error?: string
      }
      if (!res.ok || !data.subscription_id) {
        setError(data.error ?? "Could not start subscription. Try again.")
        return
      }
      const rzp = new window.Razorpay({
        key: data.key_id,
        subscription_id: data.subscription_id,
        name: "Indian Stock Analyzer",
        description: "Pro Monthly — ₹499/month",
        handler: () => {
          router.push("/?subscribed=1")
        },
        prefill: {
          name: session?.user?.name ?? "",
          email: session?.user?.email ?? "",
        },
        theme: { color: "#111827" },
      })
      rzp.open()
    } catch {
      setError("Could not connect to payment service. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Script src="https://checkout.razorpay.com/v1/checkout.js" strategy="lazyOnload" />

      <div className="mx-auto max-w-3xl px-4 py-12">
        <h1 className="mb-2 text-2xl font-bold text-gray-900">Pricing</h1>
        <p className="mb-10 text-sm text-gray-500">
          Free forever for reading. Subscribe for delivery and live streaming.
        </p>

        <div className="grid gap-6 sm:grid-cols-2">
          {/* Free tier */}
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Free</p>
            <p className="mt-1 text-3xl font-bold text-gray-900">₹0</p>
            <p className="mt-0.5 text-sm text-gray-400">forever</p>
            <ul className="mt-6 space-y-2" aria-label="Free plan features">
              {FREE_FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-gray-600">
                  <span aria-hidden="true" className="mt-0.5 shrink-0 text-gray-400">
                    ✓
                  </span>
                  {f}
                </li>
              ))}
            </ul>
          </div>

          {/* Pro tier */}
          <div className="rounded-xl border-2 border-gray-900 bg-white p-6">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-900">Pro</p>
            <p className="mt-1 text-3xl font-bold text-gray-900">₹499</p>
            <p className="mt-0.5 text-sm text-gray-400">per month · billed monthly</p>
            <ul className="mt-6 space-y-2" aria-label="Pro plan features">
              {PRO_FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-2 text-sm text-gray-600">
                  <span aria-hidden="true" className="mt-0.5 shrink-0 text-gray-900">
                    ✓
                  </span>
                  {f}
                </li>
              ))}
            </ul>

            {isPro ? (
              <p className="mt-6 rounded-lg bg-gray-100 px-4 py-2.5 text-center text-sm font-medium text-gray-700">
                You&apos;re already on Pro
              </p>
            ) : (
              <button
                onClick={handleSubscribe}
                disabled={loading}
                className="mt-6 w-full rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
                aria-label={
                  status !== "authenticated" ? "Sign in to subscribe" : "Subscribe to Pro plan"
                }
              >
                {loading
                  ? "Opening payment…"
                  : status !== "authenticated"
                    ? "Sign in to Subscribe"
                    : "Subscribe Now"}
              </button>
            )}

            {error && (
              <p role="alert" className="mt-3 text-center text-xs text-red-600">
                {error}
              </p>
            )}
          </div>
        </div>

        <p className="mt-8 text-center text-xs text-gray-400">
          Payments processed by Razorpay · UPI, cards, net banking accepted · Cancel anytime ·{" "}
          <Link href="/privacy" className="underline hover:text-gray-600">
            Privacy
          </Link>{" "}
          · Not financial advice
        </p>
      </div>
    </>
  )
}
