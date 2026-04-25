import * as React from "react"
import { cn } from "@/lib/utils"

interface AvatarProps extends React.HTMLAttributes<HTMLDivElement> {
  initials: string
  color?: string
  size?: "sm" | "md" | "lg"
}

export function Avatar({ initials, color, size = "md", className, ...props }: AvatarProps) {
  const sizes = {
    sm: "h-8 w-8 text-xs",
    md: "h-10 w-10 text-sm",
    lg: "h-12 w-12 text-base",
  }
  return (
    <div
      className={cn(
        "inline-flex items-center justify-center rounded-full font-semibold text-white select-none",
        sizes[size],
        className
      )}
      style={{ background: color ?? "linear-gradient(135deg, oklch(56% 0.12 255), oklch(40% 0.1 250))" }}
      {...props}
    >
      {initials.slice(0, 2).toUpperCase()}
    </div>
  )
}
