import type { KeyMetric } from "../types"
import { safeArray, safeText } from "./defensive"

const TONE: Record<string, string> = {
  positive: "border-emerald-500/40 text-emerald-400",
  negative: "border-red-500/40 text-red-400",
  neutral:  "border-zinc-500/30 text-zinc-300",
}

export function KpiRow({ items }: { items?: KeyMetric[] | null }) {
  const list = safeArray<KeyMetric>(items)
  if (list.length === 0) return null
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
      {list.map((m, i) => {
        // ``safeText`` collapses anything non-scalar (objects / arrays
        // from a malformed LLM payload) to the fallback so React never
        // sees an object as a child. Was previously ``String(m.value)``
        // which produced the cosmetic but ugly ``"[object Object]"``.
        const label = safeText(m?.label)
        const value = safeText(m?.value, "—")
        const tone = TONE[m?.tone ?? "neutral"] ?? TONE.neutral
        return (
          <div
            key={i}
            className={`rounded border bg-card/50 px-3 py-2 ${tone}`}
            title={typeof m?.hint === "string" ? m.hint : undefined}
          >
            <div className="text-[10px] uppercase tracking-wider opacity-70">{label}</div>
            <div className="font-mono text-sm mt-0.5">{value}</div>
          </div>
        )
      })}
    </div>
  )
}
