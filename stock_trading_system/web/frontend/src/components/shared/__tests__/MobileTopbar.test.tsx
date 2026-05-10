import { render, screen } from "@testing-library/react"
import { describe, expect, test, vi } from "vitest"

import { MobileTopbar } from "../MobileTopbar"

/**
 * v1.3.1 R-MUI-19 MobileTopbar contract
 *
 * Tests pin the surface (brand, optional pageTitle, LLMSwitcher slot,
 * sticky+md:hidden classes) without depending on the full LLMSwitcher
 * implementation — that one talks to /api/llm/active and would force
 * us to wire a fetch mock for an unrelated test. Instead we mock it
 * to a tiny marker and verify it gets composed into the header.
 */

vi.mock("../LLMSwitcher", () => ({
  LLMSwitcher: () => (
    <div data-testid="mock-llm-switcher">switcher</div>
  ),
}))

describe("<MobileTopbar> — v1.3.1 R-MUI-19", () => {
  test("renders brand text always", () => {
    render(<MobileTopbar />)
    // The leading ⚡ glyph is part of the brand string.
    expect(screen.getByText(/StockAI Terminal/)).toBeInTheDocument()
  })

  test("renders pageTitle when provided", () => {
    render(<MobileTopbar pageTitle="首页 · 资产与持仓" />)
    expect(screen.getByText("首页 · 资产与持仓")).toBeInTheDocument()
  })

  test("omits pageTitle when not provided (no empty subtitle slot)", () => {
    const { container } = render(<MobileTopbar />)
    // Header should have exactly one text element (brand) under the
    // left-side flex column.
    const subtitles = container.querySelectorAll("span.text-\\[11px\\]")
    expect(subtitles.length).toBe(0)
  })

  test("composes LLMSwitcher slot + uses sticky + md:hidden classes", () => {
    const { container } = render(<MobileTopbar pageTitle="X" />)
    // LLMSwitcher mock present
    expect(screen.getByTestId("mock-llm-switcher")).toBeInTheDocument()
    // Top-level <header> sticky-on-mobile, hidden on md+
    const header = container.querySelector("header")
    expect(header).not.toBeNull()
    expect(header!.className).toMatch(/\bmd:hidden\b/)
    expect(header!.className).toMatch(/\bsticky\b/)
    expect(header!.className).toMatch(/\btop-0\b/)
  })
})
