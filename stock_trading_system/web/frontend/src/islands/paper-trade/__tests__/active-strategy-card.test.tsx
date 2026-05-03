/**
 * paper-trade v1.4 — ActiveStrategyCard / AnalysisHistoryList contract.
 *
 * The /paper-trade/<ticker> page used to render
 *   • a regex-parsed thesis snippet plus a ``parse_method`` footer,
 *   • a separate "AI 最终决策" card with the trader's raw markdown,
 *   • a per-plan list whose only AI content was a ``<details>`` block
 *     containing the same raw markdown.
 *
 * v1.4 routes everything through the OverviewCard summary that
 * /analysis/<id> already renders. These tests pin:
 *   1. The ActiveStrategyCard shows tri-state signal + Rating +
 *      Executive Summary + a deep link to /analysis/<id>, and never
 *      surfaces ``parse_method`` / ``regex`` strings.
 *   2. The card falls back to the page-level
 *      ``latest_analysis_summary`` when ``active_plan`` is null.
 *   3. Both null → renders nothing (no empty stub).
 *   4. The AnalysisHistoryList rows are clickable links pointing to
 *      ``/analysis/<id>`` and the topmost row carries the ★ 当前
 *      flag.
 */

import { render, screen } from "@testing-library/react"
import { describe, test, expect } from "vitest"
import "@testing-library/jest-dom/vitest"

import {
  ActiveStrategyCard,
  AnalysisHistoryList,
} from "../PaperTradePage"

describe("ActiveStrategyCard v1.4", () => {
  test("rating + tri-state signal + executive summary + /analysis/<id> link", () => {
    const summary = {
      analysis_id: 42,
      signal_raw: "Overweight",
      signal_tri: "Buy" as const,
      rating: "买入",
      action_direction: "分批建仓",
      executive_summary: "公司 AI 资本支出可由现金流轻松覆盖",
      confidence_pct: 78,
      confidence_level: "high" as const,
    }
    render(
      <ActiveStrategyCard
        plan={{ id: 1, analysis_summary: summary } as any}
        fallback={null}
      />,
    )
    expect(screen.getByText("Buy")).toBeInTheDocument()
    expect(screen.getByText("买入")).toBeInTheDocument()
    expect(screen.getByText(/分批建仓/)).toBeInTheDocument()
    expect(screen.getByText(/AI 资本支出/)).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: /查看完整分析/ }),
    ).toHaveAttribute("href", "/analysis/42")
    // Pin the regression: legacy plan_parser surface MUST NOT leak.
    expect(screen.queryByText(/parse_method/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/regex/i)).not.toBeInTheDocument()
  })

  test("falls back to latest_analysis_summary when active_plan is null", () => {
    const fallback = {
      analysis_id: 7,
      signal_tri: "Hold" as const,
      signal_raw: "Hold",
      action_direction: "观望",
    }
    render(
      <ActiveStrategyCard plan={null} fallback={fallback as any} />,
    )
    expect(screen.getByText("Hold")).toBeInTheDocument()
    expect(screen.getByText(/观望/)).toBeInTheDocument()
  })

  test("renders nothing when both null", () => {
    const { container } = render(
      <ActiveStrategyCard plan={null} fallback={null} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe("AnalysisHistoryList v1.4", () => {
  test("first row marked ★ 当前 and links to /analysis/<id>", () => {
    const plans = [
      {
        id: 10,
        analysis_id: 42,
        created_at: "2026-05-04 10:00",
        analysis_summary: {
          analysis_id: 42,
          signal_raw: "Buy",
          action_direction: "建仓",
          created_at: "2026-05-04 10:00",
        },
      },
      {
        id: 9,
        analysis_id: 41,
        created_at: "2026-05-03 10:00",
        analysis_summary: {
          analysis_id: 41,
          signal_raw: "Hold",
          action_direction: "观望",
          created_at: "2026-05-03 10:00",
        },
      },
    ]
    render(<AnalysisHistoryList plans={plans as any} />)
    const links = screen.getAllByRole("link")
    expect(links[0]).toHaveAttribute("href", "/analysis/42")
    expect(links[1]).toHaveAttribute("href", "/analysis/41")
    expect(screen.getByText("★ 当前")).toBeInTheDocument()
  })
})
