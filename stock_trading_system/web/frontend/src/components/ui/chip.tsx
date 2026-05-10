import * as React from "react"
import { cn } from "@/lib/utils"

interface ChipProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean
  size?: "sm" | "md"
}

export const Chip = React.forwardRef<HTMLButtonElement, ChipProps>(
  ({ className, active, size = "md", ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      data-ui-chip=""
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border transition-all whitespace-nowrap",
        size === "sm" ? "h-7 px-3 text-xs" : "h-9 px-4 text-sm",
        active
          ? "bg-[color-mix(in_oklch,var(--color-accent-blue)_16%,transparent)] border-[var(--color-accent-blue)] text-[var(--color-accent-blue)] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
          : "bg-transparent border-[var(--color-border)] text-[var(--color-text-secondary)] hover:border-[var(--color-border-bright)] hover:text-[var(--color-text-primary)]",
        className
      )}
      {...props}
    />
  )
)
Chip.displayName = "Chip"

export function ChipRow({ children, className }: { children: React.ReactNode; className?: string }) {
  // 2026-05-04: `min-w-0 max-w-full flex-nowrap` are non-negotiable —
  // without them, flex children stretch the parent and overflow-x-auto
  // never fires (the regression that blew out the dashboard time-range
  // row at 320px). The shared `.mobile-scroll-row` rule pins
  // `flex-shrink: 0` on each child so chips keep their natural width.
  return (
    <div
      className={cn(
        "mobile-scroll-row flex flex-nowrap gap-2 min-w-0 max-w-full overflow-x-auto pb-1",
        "[&::-webkit-scrollbar]:hidden [scrollbar-width:none]",
        className
      )}
    >
      {children}
    </div>
  )
}
