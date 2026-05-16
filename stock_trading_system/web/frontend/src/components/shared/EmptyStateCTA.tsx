/**
 * <EmptyStateCTA> — shared empty-state component used across the 4
 * post-register surfaces (holdings / analysis / screener / paper).
 *
 * Spec: docs/design/onboarding.md §4.10.
 */
import { Button } from "@/components/ui/button"

interface EmptyStateCTAProps {
  icon?: React.ReactNode
  message: string
  ctaLabel: string
  onClick?: () => void
  href?: string
}

export function EmptyStateCTA({
  icon,
  message,
  ctaLabel,
  onClick,
  href,
}: EmptyStateCTAProps) {
  const button = (
    <Button onClick={onClick} className="mt-1">
      {ctaLabel}
    </Button>
  )
  return (
    <div className="border border-dashed border-white/15 bg-white/2 rounded-lg p-6 text-center">
      {icon && (
        <div className="text-3xl opacity-55 mb-2" aria-hidden="true">
          {icon}
        </div>
      )}
      <p className="text-xs text-muted-foreground mb-3 leading-relaxed">
        {message}
      </p>
      {href ? (
        <a href={href} className="inline-block">
          {button}
        </a>
      ) : (
        button
      )}
    </div>
  )
}
