import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { cn } from "@/lib/utils"

export const Tabs = TabsPrimitive.Root

export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex items-center gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] p-1 text-[var(--color-text-secondary)]",
      className
    )}
    {...props}
  />
))
TabsList.displayName = "TabsList"

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
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
