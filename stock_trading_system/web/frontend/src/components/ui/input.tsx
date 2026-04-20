import * as React from "react"
import { cn } from "@/lib/utils"

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-10 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-input)] px-3 py-2 text-sm transition-colors",
        "placeholder:text-[var(--color-text-muted)]",
        "focus-visible:outline-none focus-visible:border-[var(--color-accent-blue)] focus-visible:ring-2 focus-visible:ring-[color-mix(in_oklch,var(--color-accent-blue)_30%,transparent)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
)
Input.displayName = "Input"

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-[64px] w-full rounded-md border border-[var(--color-border)] bg-[var(--color-input)] px-3 py-2 text-sm transition-colors resize-y",
        "placeholder:text-[var(--color-text-muted)]",
        "focus-visible:outline-none focus-visible:border-[var(--color-accent-blue)] focus-visible:ring-2 focus-visible:ring-[color-mix(in_oklch,var(--color-accent-blue)_30%,transparent)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
)
Textarea.displayName = "Textarea"
