import type { Mood } from "../types"

const MOOD_LABEL: Record<Mood, string> = {
  extreme_fear: "极度恐惧",
  fear:         "恐惧",
  neutral:      "中性",
  greed:        "贪婪",
  extreme_greed: "极度贪婪",
}

/** Half-circle mood gauge, score in -100..100. Color shifts fear→greed. */
export function MoodGauge({ mood, score }: { mood: Mood; score: number }) {
  // Map -100..100 → 0..180 degrees on a half circle.
  const clamped = Math.max(-100, Math.min(100, score))
  const angle = ((clamped + 100) / 200) * 180
  // Color: red (fear) → amber → emerald (greed)
  const color =
    clamped <= -50 ? "#ef4444" :
    clamped <=  -10 ? "#f97316" :
    clamped <=   10 ? "#a3a3a3" :
    clamped <=   50 ? "#10b981" :
    "#059669"
  // Needle endpoint on a half circle of radius 50 centered at (60, 60)
  const rad = ((angle - 180) * Math.PI) / 180
  const nx = 60 + Math.cos(rad) * 48
  const ny = 60 + Math.sin(rad) * 48
  return (
    <div className="inline-flex flex-col items-center gap-1">
      <svg width="120" height="70" viewBox="0 0 120 70">
        <path d="M 10 60 A 50 50 0 0 1 110 60" stroke="#3f3f46" strokeWidth="6" fill="none" strokeLinecap="round" />
        <line x1="60" y1="60" x2={nx} y2={ny} stroke={color} strokeWidth="3" strokeLinecap="round" />
        <circle cx="60" cy="60" r="3" fill={color} />
      </svg>
      <div className="text-xs text-muted-foreground">
        <span className="font-semibold" style={{ color }}>{MOOD_LABEL[mood]}</span>
        <span className="font-mono ml-2">{score > 0 ? `+${score}` : score}</span>
      </div>
    </div>
  )
}
