import type { MorningNote } from "@/lib/schemas"

const statusColour: Record<MorningNote["status"], string> = {
  INTACT: "bg-green-100 text-green-800",
  STRENGTHENED: "bg-emerald-100 text-emerald-800",
  WEAKENED: "bg-amber-100 text-amber-800",
}

const statusIcon: Record<MorningNote["status"], string> = {
  INTACT: "→",
  STRENGTHENED: "↑",
  WEAKENED: "↓",
}

export default function MorningCard({ note: n }: { note: MorningNote }) {
  const symbol = n.symbol.replace(".NS", "")
  return (
    <article
      className="flex flex-col gap-2 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
      aria-label={`Morning update for ${symbol}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="font-semibold text-gray-900">{symbol}</p>
          <p className="text-xs text-gray-400">{n.company_name}</p>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-bold ${statusColour[n.status]}`}
          aria-label={`Status: ${n.status}`}
        >
          {statusIcon[n.status]} {n.status}
        </span>
      </div>
      <p className="text-sm leading-relaxed text-gray-700">{n.morning_text}</p>
      <p className="text-xs text-gray-400">Previous signal: {n.previous_signal}</p>
    </article>
  )
}
