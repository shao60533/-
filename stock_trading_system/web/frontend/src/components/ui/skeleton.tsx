import { cn } from "@/lib/utils"

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-[color-mix(in_oklch,var(--color-border-bright)_60%,transparent)]",
        className
      )}
      {...props}
    />
  )
}
