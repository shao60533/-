import type { KeyMetric } from "../types"

const TONE: Record<string, string> = {
  positive: "border-emerald-500/40 text-emerald-400",
  negative: "border-red-500/40 text-red-400",
  neutral:  "border-zinc-500/30 text-zinc-300",
}

export function KpiRow({ items }: { items: KeyMetric[] | undefined }) {
  if (!items?.length) return null
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
      {items.map((m, i) => (
        <div
          key={i}
          className={`rounded border bg-card/50 px-3 py-2 ${TONE[m.tone ?? "neutral"]}`}
          title={m.hint || undefined}
        >
          <div className="text-[10px] uppercase tracking-wider opacity-70">{m.label}</div>
          <div className="font-mono text-sm mt-0.5">{m.value}</div>
        </div>
      ))}
    </div>
  )
}
