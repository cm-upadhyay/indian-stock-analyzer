import type { Verdict } from "@/lib/schemas"

const STYLES: Record<Verdict["signal"], string> = {
  BUY: "bg-green-600 text-white",
  HOLD: "bg-gray-500 text-white",
  SELL: "bg-red-600 text-white",
}

const ICON: Record<Verdict["signal"], string> = {
  BUY: "↑",
  HOLD: "→",
  SELL: "↓",
}

export default function SignalBadge({ signal }: { signal: Verdict["signal"] }) {
  return (
    <span
      aria-label={`Signal: ${signal}`}
      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${STYLES[signal]}`}
    >
      {signal} {ICON[signal]}
    </span>
  )
}
