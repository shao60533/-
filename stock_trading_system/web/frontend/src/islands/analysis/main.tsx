import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import "@/styles/index.css"
import { AppShell } from "@/components/shared/AppShell"
import { ErrorBoundary } from "@/components/shared/ErrorBoundary"
import { AnalysisPage } from "./AnalysisPage"

document.documentElement.classList.add("dark")

/** Page-level fallback. Production /analysis/17 used to white-screen
 *  whenever a structured rendering card field threw — a single bad
 *  ``data.support_resistance.sort`` was enough to take out the whole
 *  React root. The boundary here keeps the AppShell chrome around and
 *  gives the user a path back. */
function PageFallback({ error }: { error: Error }) {
  return (
    <div className="p-6 max-w-2xl mx-auto space-y-4">
      <h1 className="text-lg font-semibold">分析记录加载失败</h1>
      <p className="text-sm text-muted-foreground">
        渲染时遇到未预期的错误，已捕获以避免整页白屏：
      </p>
      <pre className="rounded border border-border/60 bg-muted/30 p-3 text-xs whitespace-pre-wrap break-words">
        {error.message || String(error)}
      </pre>
      <div className="flex gap-2">
        <a
          href="/analysis"
          className="inline-flex items-center rounded border border-border px-3 py-1.5 text-sm hover:bg-muted/50"
        >
          返回分析记录
        </a>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="inline-flex items-center rounded border border-border px-3 py-1.5 text-sm hover:bg-muted/50"
        >
          重新加载
        </button>
      </div>
    </div>
  )
}

createRoot(document.getElementById("react-root")!).render(
  <StrictMode>
    <ErrorBoundary fallback={({ error }) => <PageFallback error={error} />}>
      <AppShell pageTitle="分析 · Inbox 与命令">
        <AnalysisPage />
      </AppShell>
    </ErrorBoundary>
  </StrictMode>,
)
