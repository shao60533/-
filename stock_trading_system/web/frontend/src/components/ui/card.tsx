import * as React from "react"
import { cn } from "@/lib/utils"

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-card-foreground)] shadow-[0_1px_0_rgba(255,255,255,0.02)_inset,0_8px_24px_-16px_rgba(0,0,0,0.5)] transition-colors hover:border-[var(--color-border-bright)]",
        className
      )}
      {...props}
    />
  )
)
Card.displayName = "Card"

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex flex-col gap-1 px-5 py-4", className)} {...props} />
  )
)
CardHeader.displayName = "CardHeader"

export const CardTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn("text-base font-semibold tracking-tight", className)} {...props} />
  )
)
CardTitle.displayName = "CardTitle"

export const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn("text-xs text-[var(--color-text-secondary)]", className)} {...props} />
  )
)
CardDescription.displayName = "CardDescription"

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("px-5 pb-5", className)} {...props} />
  )
)
CardContent.displayName = "CardContent"

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("flex items-center gap-2 px-5 pb-5 pt-2", className)} {...props} />
  )
)
CardFooter.displayName = "CardFooter"
