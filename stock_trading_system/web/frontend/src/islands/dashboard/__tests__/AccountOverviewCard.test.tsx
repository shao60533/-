import { render, screen } from "@testing-library/react"
import { describe, expect, test } from "vitest"

import { AccountOverviewCard } from "../DashboardPage"

/**
 * v1.3.1 R-MUI-21 Account-overview hero contract
 *
 * 1. ≥ 5 finite history points  → embedded sparkline visible
 * 2. < 5 points (sparse)        → sparkline hidden, layout still works
 * 3. Hero card uses the demo-aligned visual chrome
 *    (bg-card/95 ring-1 ring-primary/10 shadow-sm)
 */

const PNL = {
  total_value: 12_345.67,
  total_pnl: 678.9,
  total_pnl_pct: 5.81,
}
const SUMMARY = {
  total_value: 12_345.67,
  total_pnl: 678.9,
  total_pnl_pct: 5.81,
  today_pnl: 12.34,
  today_pnl_pct: 0.1,
  holdings_count: 3,
}

describe("<AccountOverviewCard> — v1.3.1 R-MUI-21", () => {
  test("renders an embedded sparkline when ≥ 5 history values are present", () => {
    const { container } = render(
      <AccountOverviewCard
        pnl={PNL}
        summary={SUMMARY}
        alertsCount={0}
        sparklineValues={[100, 105, 108, 112, 120]}
      />,
    )
    expect(container.querySelector("svg[data-sparkline]")).not.toBeNull()
  })

  test("hides the sparkline when fewer than 5 history values exist", () => {
    const { container } = render(
      <AccountOverviewCard
        pnl={PNL}
        summary={SUMMARY}
        alertsCount={0}
        sparklineValues={[100, 105, 108]}
      />,
    )
    expect(container.querySelector("svg[data-sparkline]")).toBeNull()
    // Card itself still renders — the metric strip + headline must
    // still be visible so a fresh-DB user sees the layout, not a hole.
    expect(screen.getByText("账户总值")).toBeInTheDocument()
  })

  test("hero card uses the demo-aligned chrome (bg-card/95 + ring + shadow)", () => {
    const { container } = render(
      <AccountOverviewCard
        pnl={PNL}
        summary={SUMMARY}
        alertsCount={0}
        sparklineValues={[]}
      />,
    )
    const card = container.querySelector("[data-ui-card]") ?? container.firstChild
    // The Card primitive forwards className. Spec-required tokens:
    const cls = (card as HTMLElement).className
    expect(cls).toMatch(/\bbg-card\/95\b/)
    expect(cls).toMatch(/\bring-1\b/)
    expect(cls).toMatch(/\bring-primary\/10\b/)
    expect(cls).toMatch(/\bshadow-sm\b/)
  })
})
