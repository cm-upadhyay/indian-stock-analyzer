"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchLatest } from "@/lib/api"
import VerdictCard from "@/components/verdict-card"
import SignalBadge from "@/components/signal-badge"
import type { Verdict } from "@/lib/schemas"

function formatDate(iso: string): string {
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  const [, month, day] = iso.split("-")
  return `${parseInt(day)} ${months[parseInt(month) - 1]}`
}

function LoadingState() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-gray-400">Loading today&apos;s picks…</p>
    </div>
  )
}

function ErrorState() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-red-500">Failed to load. Try refreshing.</p>
    </div>
  )
}

function EmptyState({ date }: { date: string }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-2 text-center px-4">
      <p className="text-3xl">📊</p>
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
    <section className="mt-10">
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-sm font-bold uppercase tracking-widest text-gray-500">{label}</h2>
        <SignalBadge signal={signal} />
        <span className="text-sm text-gray-400">{verdicts.length} stocks</span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {verdicts.map((v) => (
          <VerdictCard key={v.symbol} verdict={v} />
        ))}
      </div>
    </section>
  )
}

export default function Home() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["latest"],
    queryFn: fetchLatest,
    staleTime: 5 * 60 * 1000,
  })

  if (isLoading) return <LoadingState />
  if (isError) return <ErrorState />

  const today = new Date().toISOString().slice(0, 10)
  if (!data || data.count === 0) return <EmptyState date={data?.date ?? today} />

  const buy = data.analyses.filter((v) => v.signal === "BUY")
  const hold = data.analyses.filter((v) => v.signal === "HOLD")
  const sell = data.analyses.filter((v) => v.signal === "SELL")

  return (
    <main className="mx-auto max-w-7xl px-4 py-10">
      {/* Header */}
      <div className="rounded-xl bg-[#1a1a2e] px-8 py-7 text-white">
        <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          Indian Stock Analyzer
        </p>
        <h1 className="mt-1 text-2xl font-bold">
          {formatDate(data.date)} · Evening Analysis
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
        </div>
      </div>

      {/* Verdict groups */}
      <VerdictGroup label="Buy" verdicts={buy} signal="BUY" />
      <VerdictGroup label="Hold" verdicts={hold} signal="HOLD" />
      <VerdictGroup label="Sell" verdicts={sell} signal="SELL" />

      {/* Footer */}
      <p className="mt-16 text-center text-xs text-gray-400">
        Indian Stock Analyzer · Not financial advice · For informational purposes only
      </p>
    </main>
  )
}
