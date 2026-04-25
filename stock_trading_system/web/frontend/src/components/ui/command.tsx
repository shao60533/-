import * as React from "react"
import { Command as CommandPrimitive } from "cmdk"
import { Search } from "lucide-react"
import { cn } from "@/lib/utils"
import { Dialog, DialogContent } from "./dialog"

export const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive
    ref={ref}
    className={cn(
      "flex h-full w-full flex-col overflow-hidden rounded-md bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)]",
      className
    )}
    {...props}
  />
))
Command.displayName = "Command"

export function CommandDialog({ children, open, onOpenChange }: { children: React.ReactNode; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 max-w-xl">
        <Command className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-[var(--color-text-muted)]">
          {children}
        </Command>
      </DialogContent>
    </Dialog>
  )
}

export const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="flex items-center border-b border-[var(--color-border)] px-3" cmdk-input-wrapper="">
    <Search className="mr-2 h-4 w-4 shrink-0 text-[var(--color-text-muted)]" />
    <CommandPrimitive.Input
      ref={ref}
      className={cn(
        "flex h-11 w-full bg-transparent py-3 text-sm outline-none placeholder:text-[var(--color-text-muted)] disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  </div>
))
CommandInput.displayName = "CommandInput"

export const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List ref={ref} className={cn("max-h-[360px] overflow-y-auto overflow-x-hidden p-1.5", className)} {...props} />
))
CommandList.displayName = "CommandList"

export const CommandEmpty = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>((props, ref) => (
  <CommandPrimitive.Empty ref={ref} className="py-8 text-center text-sm text-[var(--color-text-muted)]" {...props} />
))
CommandEmpty.displayName = "CommandEmpty"

export const CommandGroup = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Group ref={ref} className={cn("overflow-hidden p-1 text-[var(--color-text-primary)]", className)} {...props} />
))
CommandGroup.displayName = "CommandGroup"

export const CommandSeparator = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Separator ref={ref} className={cn("-mx-1 h-px bg-[var(--color-border)]", className)} {...props} />
))
CommandSeparator.displayName = "CommandSeparator"

export const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none",
      "data-[selected=true]:bg-[var(--color-bg-secondary)] data-[selected=true]:text-[var(--color-text-primary)]",
      "data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
      "[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-[var(--color-text-muted)]",
      className
    )}
    {...props}
  />
))
CommandItem.displayName = "CommandItem"

export const CommandShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
  <span className={cn("ml-auto text-[10px] font-mono tracking-wider text-[var(--color-text-muted)]", className)} {...props} />
)
