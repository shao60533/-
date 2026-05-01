import type { ReactNode } from "react"
import type { Stance } from "../types"

const RING: Record<string, string> = {
  aggressive:   "border-orange-500/40",
  conservative: "border-blue-500/40",
  neutral:      "border-zinc-500/30",
}

export function StanceCard({
  title, icon, stance, accent,
}: {
  title: string
  icon?: ReactNode
  stance: Stance
  accent: "aggressive" | "conservative" | "neutral"
}) {
  return (
    <div className={`rounded border bg-card/40 p-3 space-y-2 ${RING[accent]}`}>
      <div className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </div>
      <div>
        <div className="text-[10px] uppercase opacity-60">论点</div>
        <div className="text-xs leading-relaxed">{stance.claim}</div>
      </div>
      <div>
        <div className="text-[10px] uppercase opacity-60">证据</div>
        <div className="text-xs leading-relaxed">{stance.evidence}</div>
      </div>
      <div>
        <div className="text-[10px] uppercase opacity-60">局限</div>
        <div className="text-xs leading-relaxed opacity-80">{stance.limitation}</div>
      </div>
    </div>
  )
}
