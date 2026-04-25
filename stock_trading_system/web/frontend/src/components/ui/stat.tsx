import * as React from "react"
import { cn } from "@/lib/utils"
import { Card, CardContent } from "./card"
import { ArrowUpRight, ArrowDownRight } from "lucide-react"

interface StatProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string
  value: React.ReactNode
  delta?: number           // percent change
  hint?: string
  icon?: React.ReactNode
}

export function Stat({ label, value, delta, hint, icon, className, ...props }: StatProps) {
  const positive = (delta ?? 0) >= 0
  return (
    <Card className={cn("h-full", className)} {...props}>
      <CardContent className="pt-5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
            {label}
          </span>
          {icon && <span className="text-[var(--color-text-muted)]">{icon}</span>}
        </div>
        <div
          className="mt-3 font-mono font-semibold tracking-tight truncate overflow-hidden"
          style={{ fontSize: "var(--fs-stat)", fontVariantNumeric: "tabular-nums" }}
        >
          {value}
        </div>
        <div className="mt-2 flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
          {delta !== undefined && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 font-medium font-mono tabular-nums",
                positive ? "text-[var(--color-accent-green)]" : "text-[var(--color-accent-red)]"
              )}
            >
              {positive ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {(positive ? "+" : "") + delta.toFixed(2) + "%"}
            </span>
          )}
          {hint && <span className="truncate">{hint}</span>}
        </div>
      </CardContent>
    </Card>
  )
}
