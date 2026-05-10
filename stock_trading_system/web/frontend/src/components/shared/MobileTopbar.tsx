import { LLMSwitcher } from "./LLMSwitcher"

interface MobileTopbarProps {
  pageTitle?: string
}

export function MobileTopbar({ pageTitle }: MobileTopbarProps) {
  return (
    <header
      data-mobile-topbar=""
      className="md:hidden sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85"
    >
      <div className="flex min-w-0 items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 flex-col">
          <a href="/" className="truncate text-sm font-bold text-primary">
            ⚡ StockAI Terminal
          </a>
          {pageTitle && (
            <span
              data-mobile-topbar-subtitle=""
              className="max-w-[200px] truncate text-[11px] text-muted-foreground"
            >
              {pageTitle}
            </span>
          )}
        </div>
        {/* mobile-ui-v1.3.1 fixup #2: render LLMSwitcher in compact
            blue-pill mode to match the demo `.provider` tag. The
            dropdown menu and provider/preset radio groups inside are
            identical to the desktop sidebar version. */}
        <div className="shrink-0">
          <LLMSwitcher variant="pill" />
        </div>
      </div>
    </header>
  )
}
