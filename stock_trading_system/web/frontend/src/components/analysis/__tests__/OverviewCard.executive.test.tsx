/**
 * v1.6 — OverviewCard "执行总结" sub-block regression.
 *
 * Forwards ``detail.executive_summary`` (the paper-trade v1.3 F3
 * LLM-extracted column on ``analysis_history``) into the Decision
 * banner, between ``action_direction`` and ``KpiRow``. The schema
 * layer (rendering.summary Pydantic) is intentionally untouched —
 * the value travels via prop, not via OverviewCardData.
 *
 * Verify:
 *   1. Block renders when prop has content.
 *   2. Block omits when prop is null / undefined / "" / whitespace.
 *   3. DOM order is action_direction → executive-summary → KpiRow.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import "@testing-library/jest-dom/vitest"
import { OverviewCard } from "../OverviewCard"
import type { OverviewCardData } from "../types"

const baseData: OverviewCardData = {
  rating: "Overweight",
  confidence: "medium",
  action_direction: "分批建仓",
  one_line_takeaway: "微软长期看好",
  key_metrics: [
    { label: "PE", value: "21.45", tone: "neutral" },
    { label: "MACD", value: "8.49", tone: "negative" },
  ],
  decision_drivers: [],
}

describe("OverviewCard executive summary block", () => {
  it("renders executive summary block when prop provided", () => {
    render(
      <OverviewCard
        data={baseData}
        executiveSummary="微软当前估值合理，AI 资本支出 645 亿美元支撑长期增长动能。"
      />,
    )
    expect(screen.getByTestId("executive-summary")).toBeInTheDocument()
    expect(screen.getByText("执行总结")).toBeInTheDocument()
    expect(screen.getByText(/微软当前估值合理/)).toBeInTheDocument()
  })

  it("omits executive summary block when prop empty/null/undefined", () => {
    const { rerender } = render(
      <OverviewCard data={baseData} executiveSummary={null} />,
    )
    expect(screen.queryByTestId("executive-summary")).toBeNull()
    rerender(<OverviewCard data={baseData} executiveSummary="" />)
    expect(screen.queryByTestId("executive-summary")).toBeNull()
    rerender(<OverviewCard data={baseData} executiveSummary={undefined} />)
    expect(screen.queryByTestId("executive-summary")).toBeNull()
  })

  it("falls back gracefully on whitespace-only string", () => {
    // ``nonEmptyStr`` trims before checking length, so a string of
    // spaces / tabs / newlines does NOT render the block. JSX
    // attribute strings don't interpret ``\n`` as an escape, so we
    // pass the value via an expression to get a real newline char.
    render(
      <OverviewCard data={baseData} executiveSummary={"   \n\t  "} />,
    )
    expect(screen.queryByTestId("executive-summary")).toBeNull()
  })

  it("positioned between action_direction and KpiRow", () => {
    const { container } = render(
      <OverviewCard
        data={baseData}
        executiveSummary="测试操作建议段落"
      />,
    )
    const html = container.innerHTML
    const dirIdx = html.indexOf("分批建仓")
    const execIdx = html.indexOf("执行总结")
    const kpiIdx = html.indexOf("21.45")  // KpiRow value cell
    expect(dirIdx).toBeGreaterThan(-1)
    expect(execIdx).toBeGreaterThan(-1)
    expect(kpiIdx).toBeGreaterThan(-1)
    expect(dirIdx).toBeLessThan(execIdx)  // action_direction comes first
    expect(execIdx).toBeLessThan(kpiIdx)  // execution summary before KpiRow
  })
})
