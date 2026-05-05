"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { signIn, useSession } from "next-auth/react"
import { fetchLatest, fetchMorning } from "@/lib/api"
import VerdictCard from "@/components/verdict-card"
import MorningCard from "@/components/morning-card"
import SignalBadge from "@/components/signal-badge"
import type { Verdict } from "@/lib/schemas"

function formatDate(iso: string): string {
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  const [, month, day] = iso.split("-")
  return `${parseInt(day)} ${months[parseInt(month) - 1]}`
}

function LoadingState() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <p className="text-gray-400" role="status" aria-live="polite">Loading today&apos;s picks…</p>
    </div>
  )
}

function ErrorState({ isAuth }: { isAuth?: boolean }) {
  if (isAuth) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4">
        <p className="text-lg font-semibold text-gray-700">Sign in to view today&apos;s picks</p>
        <button
          onClick={() => signIn("google")}
          className="rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-gray-700"
        >
          Sign in with Google
        </button>
      </div>
    )
  }
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <p className="text-red-500" role="alert">Failed to load. Try refreshing.</p>
    </div>
  )
}

function EmptyState({ date }: { date: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 text-center px-4">
      <p className="text-3xl" aria-hidden="true">📊</p>
      <p className="text-lg font-semibold text-gray-700">No picks yet for {formatDate(date)}</p>
      <p className="text-sm text-gray-400">
        The screener runs at 4:30 PM IST on weekdays. Check back then.
      </p>
    </div>
  )
}

function VerdictGroup({
  label,
  verdicts,
  signal,
}: {
  label: string
  verdicts: Verdict[]
  signal: Verdict["signal"]
}) {
  if (verdicts.length === 0) return null
  return (
    <section aria-labelledby={`group-${signal}`} className="mt-10">
      <div className="mb-4 flex items-center gap-3">
        <h2
          id={`group-${signal}`}
          className="text-sm font-bold uppercase tracking-widest text-gray-500"
        >
          {label}
        </h2>
        <SignalBadge signal={signal} />
        <span className="text-sm text-gray-400">{verdicts.length} stocks</span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {verdicts.map((v) => (
          <Link key={v.symbol} href={`/stock/${encodeURIComponent(v.symbol)}`}>
            <VerdictCard verdict={v} />
          </Link>
        ))}
      </div>
    </section>
  )
}

function MorningSection() {
  const { status } = useSession()
  const { data, isLoading } = useQuery({
    queryKey: ["morning"],
    queryFn: fetchMorning,
    enabled: status === "authenticated",
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading || !data || data.count === 0) return null

  const intact = data.notes.filter((n) => n.status === "INTACT")
  const strengthened = data.notes.filter((n) => n.status === "STRENGTHENED")
  const weakened = data.notes.filter((n) => n.status === "WEAKENED")

  return (
    <section aria-labelledby="morning-heading" className="mt-12">
      <h2 id="morning-heading" className="mb-1 text-lg font-semibold text-gray-800">
        Morning Follow-up · {formatDate(data.date)}
      </h2>
      <p className="mb-4 text-sm text-gray-400">How yesterday&apos;s picks opened</p>
      {strengthened.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-emerald-600">
            Strengthened ↑ ({strengthened.length})
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {strengthened.map((n) => <MorningCard key={n.symbol} note={n} />)}
          </div>
        </div>
      )}
      {intact.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-green-600">
            Intact → ({intact.length})
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {intact.map((n) => <MorningCard key={n.symbol} note={n} />)}
          </div>
        </div>
      )}
      {weakened.length > 0 && (
        <div className="mb-4">
          <p className="mb-2 text-xs font-bold uppercase tracking-widest text-amber-600">
            Weakened ↓ ({weakened.length})
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {weakened.map((n) => <MorningCard key={n.symbol} note={n} />)}
          </div>
        </div>
      )}
    </section>
  )
}

export default function Home() {
  const { status } = useSession()
  const { data, isLoading, isError } = useQuery({
    queryKey: ["latest"],
    queryFn: fetchLatest,
    enabled: status === "authenticated",
    staleTime: 5 * 60 * 1000,
  })

  if (status === "loading" || (status === "authenticated" && isLoading)) return <LoadingState />
  if (status === "unauthenticated") return <ErrorState isAuth={true} />
  if (isError) return <ErrorState />

  const today = new Date().toISOString().slice(0, 10)
  if (!data || data.count === 0) return <EmptyState date={data?.date ?? today} />

  const buy = data.analyses.filter((v) => v.signal === "BUY")
  const hold = data.analyses.filter((v) => v.signal === "HOLD")
  const sell = data.analyses.filter((v) => v.signal === "SELL")

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      {/* Morning follow-up — shown above evening analysis */}
      <MorningSection />

      {/* Header */}
      <div className="mt-10 rounded-xl bg-[#1a1a2e] px-8 py-7 text-white">
        <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          Evening Analysis
        </p>
        <h1 className="mt-1 text-2xl font-bold">
          {formatDate(data.date)} · {data.count} stocks
        </h1>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="rounded-full bg-green-600 px-4 py-1 text-sm font-semibold">
            {buy.length} BUY
          </span>
          <span className="rounded-full bg-gray-500 px-4 py-1 text-sm font-semibold">
            {hold.length} HOLD
          </span>
          <span className="rounded-full bg-red-600 px-4 py-1 text-sm font-semibold">
            {sell.length} SELL
          </span>
          <Link
            href="/accuracy"
            className="rounded-full border border-gray-400 px-4 py-1 text-sm font-semibold text-gray-300 hover:text-white"
          >
            View accuracy →
          </Link>
        </div>
      </div>

      {/* Verdict groups */}
      <VerdictGroup label="Buy" verdicts={buy} signal="BUY" />
      <VerdictGroup label="Hold" verdicts={hold} signal="HOLD" />
      <VerdictGroup label="Sell" verdicts={sell} signal="SELL" />
    </div>
  )
}
