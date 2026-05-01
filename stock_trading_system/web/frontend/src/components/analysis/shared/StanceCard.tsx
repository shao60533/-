import type { ReactNode } from "react"
import type { Stance } from "../types"
import { nonEmptyStr } from "./defensive"

const RING: Record<string, string> = {
  aggressive:   "border-orange-500/40",
  conservative: "border-blue-500/40",
  neutral:      "border-zinc-500/30",
}

/**
 * Defensive: ``stance`` may be undefined / null / partial when the
 * upstream LLM JSON dropped a sub-key. We render the title + an empty
 * notice instead of crashing on ``stance.claim`` access. This keeps
 * the rest of the parent card usable even if one stance is bad.
 */
export function StanceCard({
  title, icon, stance, accent,
}: {
  title: string
  icon?: ReactNode
  stance?: Stance | null
  accent: "aggressive" | "conservative" | "neutral"
}) {
  const ring = RING[accent] ?? RING.neutral
  const claim = stance && nonEmptyStr(stance.claim) ? stance.claim : null
  const evidence = stance && nonEmptyStr(stance.evidence) ? stance.evidence : null
  const limitation = stance && nonEmptyStr(stance.limitation) ? stance.limitation : null
  const empty = !claim && !evidence && !limitation
  return (
    <div className={`rounded border bg-card/40 p-3 space-y-2 ${ring}`}>
      <div className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </div>
      {empty ? (
        <div className="text-xs text-muted-foreground">暂无数据</div>
      ) : (
        <>
          {claim && (
            <div>
              <div className="text-[10px] uppercase opacity-60">论点</div>
              <div className="text-xs leading-relaxed">{claim}</div>
            </div>
          )}
          {evidence && (
            <div>
              <div className="text-[10px] uppercase opacity-60">证据</div>
              <div className="text-xs leading-relaxed">{evidence}</div>
            </div>
          )}
          {limitation && (
            <div>
              <div className="text-[10px] uppercase opacity-60">局限</div>
              <div className="text-xs leading-relaxed opacity-80">{limitation}</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
