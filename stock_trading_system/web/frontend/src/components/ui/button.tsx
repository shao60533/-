import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-all active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--color-accent-blue)] text-[var(--color-primary-foreground)] shadow-[0_1px_0_0_rgba(255,255,255,0.1)_inset,0_6px_18px_-8px_color-mix(in_oklch,var(--color-accent-blue)_60%,transparent)] hover:brightness-110",
        secondary:
          "bg-[var(--color-bg-card)] text-[var(--color-text-primary)] border border-[var(--color-border)] hover:border-[var(--color-border-bright)] hover:bg-[var(--color-bg-elevated)]",
        outline:
          "border border-[var(--color-border)] bg-transparent hover:bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]",
        ghost:
          "bg-transparent hover:bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]",
        destructive:
          "bg-[var(--color-accent-red)] text-white hover:brightness-110",
        link:
          "text-[var(--color-accent-blue)] underline-offset-4 hover:underline",
      },
      size: {
        sm:   "h-8 px-3 text-xs",
        md:   "h-10 px-4 text-sm",
        lg:   "h-11 px-6 text-base",
        icon: "h-10 w-10",
        // 2026-05-04: `wrap` allows long labels (e.g. "复制配置重跑",
        // "保存设置并立即生效") to break across two lines instead of
        // overflowing the parent flex row at 320px. Use inside
        // `mobile-action-row` / Card footers; never inside icon-only
        // toolbars where wrap would distort the icon column.
        wrap: "min-h-10 px-4 py-2 text-sm whitespace-normal text-center leading-snug",
      },
    },
    defaultVariants: { variant: "default", size: "md" },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        ref={ref}
        data-ui-button=""
        className={cn(buttonVariants({ variant, size, className }))}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { buttonVariants }
