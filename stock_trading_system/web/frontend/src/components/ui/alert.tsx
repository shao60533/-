import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const alertVariants = cva(
  "relative w-full rounded-md border px-4 py-3 text-sm [&>svg]:absolute [&>svg]:left-4 [&>svg]:top-3.5 [&>svg]:text-current [&>svg~*]:pl-7",
  {
    variants: {
      variant: {
        default:
          "border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-primary)]",
        info:
          "border-[color-mix(in_oklch,var(--color-accent-blue)_40%,transparent)] bg-[color-mix(in_oklch,var(--color-accent-blue)_10%,transparent)] text-[var(--color-accent-blue)] [&>*:not(svg)]:text-[var(--color-text-primary)]",
        success:
          "border-[color-mix(in_oklch,var(--color-accent-green)_40%,transparent)] bg-[color-mix(in_oklch,var(--color-accent-green)_10%,transparent)] text-[var(--color-accent-green)] [&>*:not(svg)]:text-[var(--color-text-primary)]",
        warning:
          "border-[color-mix(in_oklch,var(--color-accent-yellow)_40%,transparent)] bg-[color-mix(in_oklch,var(--color-accent-yellow)_10%,transparent)] text-[var(--color-accent-yellow)] [&>*:not(svg)]:text-[var(--color-text-primary)]",
        destructive:
          "border-[color-mix(in_oklch,var(--color-accent-red)_40%,transparent)] bg-[color-mix(in_oklch,var(--color-accent-red)_10%,transparent)] text-[var(--color-accent-red)] [&>*:not(svg)]:text-[var(--color-text-primary)]",
      },
    },
    defaultVariants: { variant: "default" },
  }
)

export const Alert = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>>(
  ({ className, variant, ...props }, ref) => (
    <div ref={ref} role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
  )
)
Alert.displayName = "Alert"

export const AlertTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h5 ref={ref} className={cn("mb-1 font-semibold leading-none tracking-tight", className)} {...props} />
  )
)
AlertTitle.displayName = "AlertTitle"

export const AlertDescription = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("text-sm leading-relaxed [&_p]:leading-relaxed", className)} {...props} />
  )
)
AlertDescription.displayName = "AlertDescription"
