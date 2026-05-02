"use client"

import { useQuery } from "@tanstack/react-query"
import { fetchAccuracy } from "@/lib/api"

function StatCard({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 text-center shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-400">{sub}</p>}
    </div>
  )
}

export default function AccuracyPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["accuracy"],
    queryFn: fetchAccuracy,
    staleTime: 60 * 60 * 1000, // accuracy updates once per day
  })

  if (isLoading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-10">
        <p className="text-gray-400" role="status" aria-live="polite">Loading accuracy stats…</p>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-10">
        <p className="text-red-500" role="alert">Failed to load accuracy stats.</p>
      </div>
    )
  }

  const bySignal = data.by_signal

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-2xl font-bold text-gray-900">Accuracy · Last {data.period_days} days</h1>
      <p className="mt-1 text-sm text-gray-400">
        Directional accuracy measured against actual NSE price movement 5 trading days after signal.
      </p>

      {/* Top-line stats */}
      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Overall accuracy"
          value={`${data.accuracy_pct.toFixed(1)}%`}
          sub={`${data.correct} / ${data.total} signals`}
        />
        <StatCard
          label="Target hit rate"
          value={`${data.target_hit_pct.toFixed(1)}%`}
          sub="Price reached stated target"
        />
        <StatCard
          label="Stop triggered"
          value={`${data.stop_triggered_pct.toFixed(1)}%`}
          sub="Price breached stop-loss"
        />
      </div>

      {/* By signal breakdown */}
      {Object.keys(bySignal).length > 0 && (
        <section aria-labelledby="by-signal" className="mt-10">
          <h2
            id="by-signal"
            className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-500"
          >
            Breakdown by signal
          </h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {(["BUY", "HOLD", "SELL"] as const).map((sig) => {
              const s = bySignal[sig]
              if (!s) return null
              return (
                <div
                  key={sig}
                  className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
                >
                  <p className="text-xs font-bold uppercase tracking-wide text-gray-400">{sig}</p>
                  <p className="mt-1 text-2xl font-bold text-gray-900">
                    {s.accuracy_pct.toFixed(1)}%
                  </p>
                  <p className="text-xs text-gray-400">
                    {s.correct} correct of {s.total}
                  </p>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* No data state */}
      {data.total === 0 && (
        <div className="mt-10 rounded-lg bg-amber-50 p-6 text-center">
          <p className="text-sm text-amber-700">
            Not enough outcome data yet. Accuracy tracking starts after the first 5-day outcome
            window completes. Check back next week.
          </p>
        </div>
      )}

      <p className="mt-10 text-xs text-gray-400">
        Not financial advice. Past accuracy does not guarantee future results.
      </p>
    </div>
  )
}
