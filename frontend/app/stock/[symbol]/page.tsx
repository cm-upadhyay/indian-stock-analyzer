"use client"

import { use, useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { fetchStock } from "@/lib/api"
import SignalBadge from "@/components/signal-badge"
import type { Verdict } from "@/lib/schemas"

function fmt(n: number | null): string {
  if (n === null) return "—"
  return n.toLocaleString("en-IN")
}

// ── Live analysis stream ──────────────────────────────────────────────────────

type StreamEvent = { event: string; symbol?: string; message?: string }

function useAnalysisStream(symbol: string) {
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [streaming, setStreaming] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const es = new EventSource(`/api/stream/${encodeURIComponent(symbol)}`)
    esRef.current = es
    setStreaming(true)

    es.onmessage = (e) => {
      try {
        const data: StreamEvent = JSON.parse(e.data)
        setEvents((prev) => [...prev, data])
        if (data.event === "done" || data.event === "timeout") {
          es.close()
          setStreaming(false)
        }
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      es.close()
      setStreaming(false)
    }

    return () => {
      es.close()
    }
  }, [symbol])

  return { events, streaming }
}

// ── Stock detail page ─────────────────────────────────────────────────────────

export default function StockPage({
  params,
}: {
  params: Promise<{ symbol: string }>
}) {
  const { symbol } = use(params)
  const decodedSymbol = decodeURIComponent(symbol)

  const { data, isLoading, isError } = useQuery({
    queryKey: ["stock", decodedSymbol],
    queryFn: () => fetchStock(decodedSymbol),
    staleTime: 5 * 60 * 1000,
  })

  const { events, streaming } = useAnalysisStream(decodedSymbol)
  const displaySymbol = decodedSymbol.replace(".NS", "")

  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <p className="text-gray-400" role="status" aria-live="polite">Loading…</p>
      </div>
    )
  }

  if (isError || !data?.found || !data?.verdict) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <Link href="/" className="text-sm text-blue-600 hover:underline">← Back</Link>
        <p className="mt-4 text-gray-500">
          No analysis found for <strong>{displaySymbol}</strong> today.
          The screener runs at 4:30 PM IST on weekdays.
        </p>
        {streaming && events.length > 0 && (
          <div className="mt-6" aria-live="polite">
            <p className="text-sm font-semibold text-gray-700 mb-2">Live analysis in progress…</p>
            <ul className="space-y-1">
              {events.map((e, i) => (
                <li key={i} className="text-sm text-gray-500">{e.event}{e.message ? `: ${e.message}` : ""}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    )
  }

  const v: Verdict = data.verdict
  const hasSetup = v.signal !== "HOLD" && v.entry !== null

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-gray-400">
        <Link href="/" className="hover:text-gray-600">Evening Analysis</Link>
        <span className="mx-2" aria-hidden="true">/</span>
        <span className="text-gray-700 font-medium">{displaySymbol}</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{displaySymbol}</h1>
          <p className="text-sm text-gray-400">{data.date} · NSE</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <SignalBadge signal={v.signal} />
          <span className="text-xs text-gray-400">{(v.confidence * 100).toFixed(0)}% confidence</span>
        </div>
      </div>

      {/* Trade setup */}
      {hasSetup && (
        <div className="mt-6 rounded-lg bg-gray-50 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
            Trade Setup
          </p>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-xs text-gray-400">Entry</p>
              <p className="text-lg font-bold text-gray-900">₹{fmt(v.entry)}</p>
            </div>
            <div>
              <p className="text-xs text-red-400">Stop Loss</p>
              <p className="text-lg font-bold text-red-600">₹{fmt(v.stop_loss)}</p>
            </div>
            <div>
              <p className="text-xs text-green-400">Target</p>
              <p className="text-lg font-bold text-green-600">₹{fmt(v.target)}</p>
            </div>
          </div>
        </div>
      )}

      {/* Analysis narrative */}
      <div className="mt-8 space-y-6">
        {v.whats_happening && (
          <section aria-labelledby="whats-happening">
            <h2 id="whats-happening" className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">
              What&apos;s Happening
            </h2>
            <p className="text-sm leading-relaxed text-gray-700">{v.whats_happening}</p>
          </section>
        )}
        {v.why_it_matters && (
          <section aria-labelledby="why-matters">
            <h2 id="why-matters" className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">
              Why It Matters
            </h2>
            <p className="text-sm leading-relaxed text-gray-700">{v.why_it_matters}</p>
          </section>
        )}
        {v.watch_out_for && (
          <section aria-labelledby="watch-out">
            <h2 id="watch-out" className="text-xs font-semibold uppercase tracking-wide text-amber-600 mb-1">
              ⚠️ Watch Out For
            </h2>
            <p className="text-sm leading-relaxed text-gray-700">{v.watch_out_for}</p>
          </section>
        )}
      </div>

      {/* Trader / investor split */}
      {(v.trader_action || v.investor_action) && (
        <div className="mt-8 grid grid-cols-2 gap-4">
          {v.trader_action && (
            <div className="rounded-lg bg-blue-50 p-4">
              <p className="text-xs font-semibold text-blue-700 mb-1">For Traders</p>
              <p className="text-sm leading-relaxed text-gray-700">{v.trader_action}</p>
            </div>
          )}
          {v.investor_action && (
            <div className="rounded-lg bg-gray-50 p-4">
              <p className="text-xs font-semibold text-gray-600 mb-1">For Investors</p>
              <p className="text-sm leading-relaxed text-gray-700">{v.investor_action}</p>
            </div>
          )}
        </div>
      )}

      {/* Live stream events (shown while pipeline is running) */}
      {streaming && events.length > 0 && (
        <div className="mt-8 rounded-lg border border-blue-200 bg-blue-50 p-4" aria-live="polite">
          <p className="text-sm font-semibold text-blue-700 mb-2">Live analysis running…</p>
          <ul className="space-y-1">
            {events.map((e, i) => (
              <li key={i} className="text-xs text-blue-600">{e.event}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
