import type { Verdict } from "@/lib/schemas"
import SignalBadge from "./signal-badge"

function fmt(n: number | null): string {
  if (n === null) return "—"
  return n.toLocaleString("en-IN")
}

export default function VerdictCard({ verdict: v }: { verdict: Verdict }) {
  const symbol = v.symbol.replace(".NS", "")
  const hasSetup = v.signal !== "HOLD" && v.entry !== null

  return (
    <div className="flex flex-col rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-lg font-bold text-gray-900">{symbol}</p>
          <p className="text-sm text-gray-400">
            NSE · {(v.confidence * 100).toFixed(0)}% confidence
          </p>
        </div>
        <SignalBadge signal={v.signal} />
      </div>

      {/* Trade setup */}
      <div className="mt-4 rounded-md bg-gray-50 px-4 py-3 text-sm">
        {hasSetup ? (
          <span className="text-gray-700">
            Entry ₹{fmt(v.entry)}
            <span className="mx-2 text-gray-300">·</span>
            Stop ₹{fmt(v.stop_loss)}
            <span className="mx-2 text-gray-300">·</span>
            Target ₹{fmt(v.target)}
          </span>
        ) : (
          <span className="text-gray-400">No trade — wait for a clearer setup</span>
        )}
      </div>

      {/* Analysis sections */}
      <div className="mt-4 flex flex-col gap-3">
        {v.whats_happening && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              What&apos;s Happening
            </p>
            <p className="mt-1 text-sm leading-relaxed text-gray-700">{v.whats_happening}</p>
          </div>
        )}

        {v.why_it_matters && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              Why It Matters
            </p>
            <p className="mt-1 text-sm leading-relaxed text-gray-700">{v.why_it_matters}</p>
          </div>
        )}

        {v.watch_out_for && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-600">
              ⚠️ Watch Out For
            </p>
            <p className="mt-1 text-sm leading-relaxed text-gray-700">{v.watch_out_for}</p>
          </div>
        )}
      </div>

      {/* Trader / investor split */}
      {(v.trader_action || v.investor_action) && (
        <div className="mt-4 grid grid-cols-2 gap-3">
          {v.trader_action && (
            <div className="rounded-md bg-blue-50 p-3">
              <p className="text-xs font-semibold text-blue-700">For Traders</p>
              <p className="mt-1 text-xs leading-relaxed text-gray-700">{v.trader_action}</p>
            </div>
          )}
          {v.investor_action && (
            <div className="rounded-md bg-gray-50 p-3">
              <p className="text-xs font-semibold text-gray-600">For Investors</p>
              <p className="mt-1 text-xs leading-relaxed text-gray-700">{v.investor_action}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
