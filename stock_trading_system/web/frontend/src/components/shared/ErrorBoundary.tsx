/**
 * Generic class-based ErrorBoundary.
 *
 * Two purposes:
 *
 *  1. **Page-level (main.tsx)** — wraps the whole AppShell + page so a
 *     single thrown render error doesn't blank the entire React root
 *     (the production /analysis/17 white-screen bug).
 *
 *  2. **Per-tab / per-component** — wraps a single lazy AnalysisCards
 *     instance per tab, so a malformed structured-card payload only
 *     hides that tab's cards, not the entire page; the markdown body
 *     below still renders.
 *
 * Usage:
 *
 *     <ErrorBoundary fallback={({error}) => <p>分析记录加载失败</p>}>
 *       <AnalysisCards ... />
 *     </ErrorBoundary>
 *
 * The fallback may be an element OR a render function. ``onError`` is
 * called once per caught error so callers can wire their own
 * telemetry (we always console.error in addition).
 */
import { Component, type ErrorInfo, type ReactNode } from "react"

interface ErrorBoundaryProps {
  children: ReactNode
  // Either a static element or a render function. Render functions get
  // the caught error + a ``reset()`` callback that re-mounts children.
  fallback:
    | ReactNode
    | ((info: { error: Error; reset: () => void }) => ReactNode)
  // Optional hook for telemetry. Errors are always logged to console
  // regardless of whether onError is supplied.
  onError?: (error: Error, info: ErrorInfo) => void
  // Resets the boundary state when this key changes (e.g. switching
  // analysis ids should re-attempt rendering rather than getting stuck
  // on the previous payload's error).
  resetKey?: unknown
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Always log — even when caller supplied onError. The browser
    // devtools surface is the first place an operator looks when a
    // user reports a white screen.
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary] caught render error:", error, info)
    this.props.onError?.(error, info)
  }

  componentDidUpdate(prev: ErrorBoundaryProps): void {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.reset()
    }
  }

  reset = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    if (this.state.error) {
      const fb = this.props.fallback
      return typeof fb === "function"
        ? fb({ error: this.state.error, reset: this.reset })
        : fb
    }
    return this.props.children
  }
}
