import type { Rating } from "../types"

const RATING_TONE: Record<string, string> = {
  "Strong Buy":  "bg-emerald-600 text-emerald-50",
  "Buy":         "bg-emerald-500 text-emerald-50",
  "Overweight":  "bg-emerald-400 text-emerald-950",
  "Hold":        "bg-zinc-500 text-zinc-50",
  "Underweight": "bg-orange-500 text-orange-50",
  "Sell":        "bg-red-500 text-red-50",
  "Strong Sell": "bg-red-700 text-red-50",
}

export function RatingBadge({ rating }: { rating: Rating | string }) {
  return (
    <span
      className={`inline-flex items-center px-3 py-1 rounded-md text-sm font-bold ${
        RATING_TONE[rating] ?? "bg-zinc-500 text-zinc-50"
      }`}
    >
      {rating}
    </span>
  )
}
