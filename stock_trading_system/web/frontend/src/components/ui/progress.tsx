import * as React from "react"
import * as ProgressPrimitive from "@radix-ui/react-progress"
import { cn } from "@/lib/utils"

interface Props extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
  value?: number
  tone?: "default" | "success" | "destructive"
}

export const Progress = React.forwardRef<React.ElementRef<typeof ProgressPrimitive.Root>, Props>(
  ({ className, value = 0, tone = "default", ...props }, ref) => {
    const toneBg = {
      default: "bg-[var(--color-accent-blue)]",
      success: "bg-[var(--color-accent-green)]",
      destructive: "bg-[var(--color-accent-red)]",
    }[tone]
    return (
      <ProgressPrimitive.Root
        ref={ref}
        className={cn(
          "relative h-1.5 w-full overflow-hidden rounded-full bg-[color-mix(in_oklch,var(--color-accent-blue)_8%,transparent)]",
          className
        )}
        {...props}
      >
        <ProgressPrimitive.Indicator
          className={cn("h-full w-full flex-1 transition-transform duration-500 ease-out", toneBg)}
          style={{ transform: `translateX(-${100 - Math.min(100, Math.max(0, value))}%)` }}
        />
      </ProgressPrimitive.Root>
    )
  }
)
Progress.displayName = "Progress"
