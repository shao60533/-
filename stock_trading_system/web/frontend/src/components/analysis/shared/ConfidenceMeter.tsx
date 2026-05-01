import type { Confidence } from "../types"

const PCT: Record<Confidence, number> = { high: 0.85, medium: 0.5, low: 0.25 }
const TONE: Record<Confidence, string> = {
  high:   "stroke-emerald-500",
  medium: "stroke-amber-500",
  low:    "stroke-zinc-500",
}
const LABEL: Record<Confidence, string> = {
  high: "高置信", medium: "中置信", low: "低置信",
}

export function ConfidenceMeter({ level }: { level: Confidence }) {
  const r = 18
  const c = 2 * Math.PI * r
  const offset = c * (1 - PCT[level])
  return (
    <div className="inline-flex items-center gap-2">
      <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="22" cy="22" r={r} className="stroke-muted/30" strokeWidth="4" fill="none" />
        <circle
          cx="22" cy="22" r={r}
          className={TONE[level]}
          strokeWidth="4"
          strokeLinecap="round"
          fill="none"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 22 22)"
        />
      </svg>
      <span className="text-xs text-muted-foreground">{LABEL[level]}</span>
    </div>
  )
}
