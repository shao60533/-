/**
 * Runtime smoke test for the structured analysis cards.
 *
 * Regression target: production /analysis/17 historically rendered the
 * per-tab fallback ("结构化摘要暂不可用，已显示完整论述。" /
 * "结构化卡片渲染失败") instead of the actual Overview card. Two root
 * causes were patched in this commit:
 *
 *   1. ``lazy-bundle.tsx`` no longer imports the analysis entry chunk
 *      back through the ``@/components/analysis`` barrel (the old
 *      circular import caused destructured helpers to resolve to
 *      ``undefined`` at lazy-load time, throwing inside the cards).
 *   2. ``AnalysisPage.tsx`` no longer imports ``defensive.ts``, which
 *      had pulled it onto the entry chunk side of the cycle.
 *
 * These tests render the dispatcher with the exact wire shape served
 * by ``/api/history/<id>`` and assert real card content shows up. If
 * either cycle (or any future runtime regression that throws inside a
 * card) returns, these assertions fail because the rendered DOM falls
 * back to either an empty fragment or — when wrapped — to the
 * fallback message.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import AnalysisCards from "../lazy-bundle"

/** The clean SNDK fixture that production /api/history/17 serves. */
const sndkSummary = {
  rating: "Sell",
  confidence: "high",
  action_direction: "Trim into strength; cap exposure ≤2%",
  key_metrics: [
    { label: "Price", value: "$36.10", tone: "neutral" },
    { label: "Target", value: "$30.00", tone: "negative" },
  ],
  decision_drivers: [
    { headline: "Margin compression", detail: "Q1 GM dropped 320bps." },
  ],
  debate_synthesis: null,
  one_line_takeaway: "Pricing pressure tips the balance toward Sell.",
}

const FALLBACK_PHRASES = [
  "结构化摘要暂不可用",
  "结构化卡片渲染失败",
] as const

function expectNoFallback() {
  for (const phrase of FALLBACK_PHRASES) {
    expect(document.body.textContent ?? "").not.toContain(phrase)
  }
}

describe("AnalysisCards — summary tab (Overview)", () => {
  it("renders OverviewCard content for the production SNDK shape", () => {
    render(<AnalysisCards tabKey="summary" data={sndkSummary} />)
    // Decision banner: rating chip + confidence label.
    expect(screen.getByText("Sell")).toBeInTheDocument()
    expect(screen.getByText(/高置信/)).toBeInTheDocument()
    // KPI row: both metrics rendered.
    expect(screen.getByText("$36.10")).toBeInTheDocument()
    expect(screen.getByText("$30.00")).toBeInTheDocument()
    // Decision driver: headline + detail.
    expect(screen.getByText("Margin compression")).toBeInTheDocument()
    expect(screen.getByText("Q1 GM dropped 320bps.")).toBeInTheDocument()
    // One-line takeaway.
    expect(screen.getByText(/Pricing pressure tips the balance/)).toBeInTheDocument()
    expectNoFallback()
  })

  it("renders OverviewCard with debate_synthesis as an array (malformed)", () => {
    // Production hypothesis: ``debate_synthesis`` came in as an array.
    // Pre-fix this threw inside StanceCard ("cannot read .claim of undefined").
    render(
      <AnalysisCards
        tabKey="summary"
        data={{
          ...sndkSummary,
          debate_synthesis: [
            { claim: "x", evidence: "y", limitation: "z" },
          ],
        }}
      />,
    )
    // The rating still renders — the malformed sub-field is collapsed
    // to ``null`` by ``normalizeCardForClient`` and the synthesis
    // section is silently skipped, but the rest of the card is intact.
    expect(screen.getByText("Sell")).toBeInTheDocument()
    expect(screen.getByText("Margin compression")).toBeInTheDocument()
    expectNoFallback()
  })

  it("renders OverviewCard when decision_drivers contains mixed item types", () => {
    render(
      <AnalysisCards
        tabKey="summary"
        data={{
          ...sndkSummary,
          decision_drivers: [
            "string-driver",                 // dropped
            null,                            // dropped
            { headline: "Real driver", detail: "Real detail" },
            ["nested", "array"],            // dropped
          ],
        }}
      />,
    )
    expect(screen.getByText("Real driver")).toBeInTheDocument()
    expect(screen.getByText("Real detail")).toBeInTheDocument()
    expect(screen.queryByText("string-driver")).not.toBeInTheDocument()
    expectNoFallback()
  })

  it("renders OverviewCard when key_metrics values are objects/arrays (React-unsafe)", () => {
    render(
      <AnalysisCards
        tabKey="summary"
        data={{
          ...sndkSummary,
          key_metrics: [
            { label: "PE", value: { nested: "obj" }, tone: "neutral" },
            { label: "Vol", value: ["a", "b"], tone: "neutral" },
          ],
        }}
      />,
    )
    expect(screen.getByText("PE")).toBeInTheDocument()
    expect(screen.getByText("Vol")).toBeInTheDocument()
    // Object/array values collapse to "—" via safeText — never throw.
    expectNoFallback()
  })

  it("returns empty (no fallback) when summary itself is malformed beyond repair", () => {
    // ``rendering.summary`` shaped as an array — normalizeCardForClient
    // returns null, dispatcher returns null, no DOM, no fallback message.
    const { container } = render(
      <AnalysisCards tabKey="summary" data={["not", "a", "record"]} />,
    )
    expect(container).toBeEmptyDOMElement()
    expectNoFallback()
  })
})

describe("AnalysisCards — Market tab", () => {
  it("renders MarketCard with mixed support_resistance items", () => {
    render(
      <AnalysisCards
        tabKey="Market"
        data={{
          trend: "bearish",
          indicators: [
            { name: "RSI(14)", value: "31.2", signal: "bearish" },
          ],
          support_resistance: [
            { price: 32.5, kind: "support", strength: "strong" },
            { price: "—", kind: "resistance" },          // bad price → dropped
            "string-level",                                 // bad item → dropped
            null,                                           // bad item → dropped
            { price: 38.4, kind: "resistance" },
          ],
          patterns: ["lower-high", null, "rising-wedge-break"],
          summary: "Lower highs + 20DMA cross = bearish swing.",
        }}
      />,
    )
    expect(screen.getByText(/看跌/)).toBeInTheDocument()
    expect(screen.getByText("RSI(14)")).toBeInTheDocument()
    // Both finite-priced levels render; the "—" / null entries don't.
    expect(screen.getByText("$38.40")).toBeInTheDocument()
    expect(screen.getByText("$32.50")).toBeInTheDocument()
    expectNoFallback()
  })
})

describe("AnalysisCards — Decision tab", () => {
  it("renders DecisionCard with bad structural_stop and entry_zone", () => {
    render(
      <AnalysisCards
        tabKey="Decision"
        data={{
          final_action: "SELL",
          conviction: "high",
          time_horizon: "short",
          entry_zone: null,
          structural_stop: "n/a",
          take_profit_levels: [
            { price: 30.0, weight_pct: 60, rationale: "Q1 low retest" },
          ],
          preconditions: ["volume confirms"],
          exit_conditions: ["close above 38"],
          alternative_scenarios: [
            { condition: "guidance raise", action: "cover and wait" },
          ],
          one_line_summary: "Sell on rallies; manage risk tight.",
        }}
      />,
    )
    expect(screen.getByText(/卖出/)).toBeInTheDocument()
    expect(screen.getByText(/高确信/)).toBeInTheDocument()
    expect(screen.getByText(/Sell on rallies/)).toBeInTheDocument()
    expect(screen.getByText("$30.00")).toBeInTheDocument()
    expectNoFallback()
  })
})

describe("AnalysisCards — unknown tab returns null", () => {
  it("renders nothing without throwing for an unknown tab key", () => {
    const { container } = render(
      <AnalysisCards tabKey="bogus" data={{ anything: 1 }} />,
    )
    expect(container).toBeEmptyDOMElement()
    expectNoFallback()
  })
})
