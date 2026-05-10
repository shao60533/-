import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { cn } from "@/lib/utils"

export const Tabs = TabsPrimitive.Root

/**
 * 2026-05-04: wrap Radix's primitive in an outer `mobile-tabs-scroll`
 * div so triggers horizontally scroll at narrow widths instead of
 * wrapping (wrap would break the active-tab indicator pill). Every
 * caller now gets scroll behaviour for free — pre-2026-05 each page
 * had to remember to add a custom `tabs-scrollable` wrapper, and the
 * 8-tab Analysis detail page kept forgetting.
 */
export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <div className="mobile-tabs-scroll">
    <TabsPrimitive.List
      ref={ref}
      data-ui-tabs-list=""
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-1 text-[var(--color-text-secondary)]",
        className
      )}
      {...props}
    />
  </div>
))
TabsList.displayName = "TabsList"

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    data-ui-tabs-trigger=""
    className={cn(
      "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition-all",
      "hover:text-[var(--color-text-primary)]",
      "data-[state=active]:bg-[var(--color-bg-card)] data-[state=active]:text-[var(--color-accent-blue)] data-[state=active]:shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_2px_8px_-2px_rgba(0,0,0,0.2)]",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]",
      "disabled:pointer-events-none disabled:opacity-50",
      className
    )}
    {...props}
  />
))
TabsTrigger.displayName = "TabsTrigger"

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn("mt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]", className)}
    {...props}
  />
))
TabsContent.displayName = "TabsContent"
