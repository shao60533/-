import { LLMSwitcher } from "./LLMSwitcher"

interface MobileTopbarProps {
  pageTitle?: string
}

export function MobileTopbar({ pageTitle }: MobileTopbarProps) {
  return (
    <header className="md:hidden sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85">
      <div className="flex min-w-0 items-center justify-between gap-3 px-4 py-2.5">
        <div className="flex min-w-0 flex-col">
          <a href="/" className="truncate text-sm font-bold text-primary">
            ⚡ StockAI Terminal
          </a>
          {pageTitle && (
            <span className="max-w-[200px] truncate text-[11px] text-muted-foreground">
              {pageTitle}
            </span>
          )}
        </div>
        <div className="shrink-0 max-w-[168px]">
          <LLMSwitcher />
        </div>
      </div>
    </header>
  )
}
