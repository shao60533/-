/**
 * Section-order contract for /analysis/<id> detail view.
 *
 * v1.4 reordered the detail view so the AI analysis card surfaces above
 * the fold:
 *
 *   Header → PipelineDAG (running) → 8-tab report → K-line → Quick-info
 *
 * The legacy Stats 3-card row (分析日期 / 信号 / 风险等级) was deleted
 * because the same information is already visible via the Header badge,
 * the Provenance "创建于" line, and the OverviewCard rating + confidence
 * meter.
 *
 * These tests lock the order via `data-testid` anchors so a future
 * refactor cannot silently regress the layout.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen } from "@testing-library/react"
import "@testing-library/jest-dom/vitest"
import { AnalysisPage } from "../AnalysisPage"

const detailPayload = {
  id: 1,
  ticker: "MSFT",
  signal: "BUY",
  date: "2026-05-02",
  created_at: "2026-05-02 13:05:01",
  market_report: "trend up",
  sentiment_report: "positive",
  news_report: "quiet",
  fundamentals_report: "strong",
  investment_debate: "",
  risk_assessment: "",
  trade_decision: "",
  rendering: {
    summary: {
      rating: "Overweight",
      confidence: "medium",
      action_direction: "分批建仓",
      key_metrics: [],
      decision_drivers: [],
      one_line_takeaway: "稳健加仓窗口",
    },
  },
}

const originalLocation = window.location

function mockApi(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string"
      ? input
      : input instanceof URL ? input.toString() : (input as Request).url
    const ok = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    if (url.match(/\/api\/history\/\d+(\?|$)/)) return ok(overrides.detail ?? detailPayload)
    if (url.includes("/quick-info")) return ok(overrides.quickInfo ?? { news: [], fundamentals: null })
    if (url.includes("/api/quote/history")) return ok({ bars: [] })
    if (url.includes("/api/chart/")) return ok({ data: [] })
    if (url.includes("/api/history?")) return ok({ items: [], running: [], total: 0 })
    return ok({})
  }))
}

beforeEach(() => {
  // Mount AnalysisPage on the detail route so AnalysisDetailView is rendered.
  Object.defineProperty(window, "location", {
    value: { ...originalLocation, pathname: "/analysis/1", search: "", hash: "" },
    writable: true,
    configurable: true,
  })
  mockApi()
})

afterEach(() => {
  vi.unstubAllGlobals()
  Object.defineProperty(window, "location", {
    value: originalLocation,
    writable: true,
    configurable: true,
  })
})

function expectOrdered(first: Element, second: Element) {
  // first must precede second in document order.
  const cmp = first.compareDocumentPosition(second)
  expect(cmp & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
}

describe("AnalysisDetailView section order (v1.4)", () => {
  it("renders 8-tab report before the K-line container", async () => {
    const { container } = render(<AnalysisPage />)
    await screen.findByTestId("analysis-tabs")
    await screen.findByTestId("kline-section")
    const tabs = container.querySelector('[data-testid="analysis-tabs"]')!
    const kline = container.querySelector('[data-testid="kline-section"]')!
    expectOrdered(tabs, kline)
  })

  it("renders K-line container before the quick-info row", async () => {
    const { container } = render(<AnalysisPage />)
    await screen.findByTestId("kline-section")
    await screen.findByTestId("quickinfo-row")
    const kline = container.querySelector('[data-testid="kline-section"]')!
    const quick = container.querySelector('[data-testid="quickinfo-row"]')!
    expectOrdered(kline, quick)
  })

  it("does not render the legacy Stats 3-card row (分析日期 / 风险等级)", async () => {
    render(<AnalysisPage />)
    await screen.findByTestId("analysis-tabs")
    // The legacy Stats row carried CardTitle 分析日期 + CardTitle 风险等级.
    // The submit form (separate component, not on the detail route) uses
    // a <label> rather than a <CardTitle> for 分析日期, so any match here
    // would mean the deleted row leaked back in.
    //
    // We grep for these labels appearing as a CardTitle (h3-ish element)
    // within the detail view container only.
    const detail = screen.getByTestId("analysis-tabs").closest("div") ?? document.body
    const titles = Array.from(detail.querySelectorAll("h3, [class*='CardTitle']"))
      .map(el => el.textContent?.trim() ?? "")
    expect(titles).not.toContain("分析日期")
    expect(titles).not.toContain("风险等级")
  })
})
