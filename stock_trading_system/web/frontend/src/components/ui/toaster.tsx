import { Toaster as SonnerToaster } from "sonner"

export function Toaster() {
  return (
    <SonnerToaster
      theme="dark"
      position="top-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast: "group toast group-[.toaster]:bg-[var(--color-bg-elevated)] group-[.toaster]:text-[var(--color-text-primary)] group-[.toaster]:border-[var(--color-border)] group-[.toaster]:shadow-[0_16px_40px_-12px_rgba(0,0,0,0.6)]",
          description: "group-[.toast]:text-[var(--color-text-secondary)]",
          actionButton: "group-[.toast]:bg-[var(--color-accent-blue)] group-[.toast]:text-white",
          cancelButton: "group-[.toast]:bg-[var(--color-bg-secondary)] group-[.toast]:text-[var(--color-text-secondary)]",
        },
      }}
    />
  )
}

export { toast } from "sonner"
