import { render } from "@testing-library/react"
import { describe, test, expect } from "vitest"
import {
  TabIconDashboard, TabIconAnalysis, TabIconDiscover, TabIconPaper, TabIconMore,
} from "../TabIcons"

describe("TabIcons v1", () => {
  test("TabIconDashboard: 4 rect + 1 polyline (portfolio grid + sparkline)", () => {
    const { container } = render(<TabIconDashboard className="w-5 h-5" />)
    expect(container.querySelectorAll("rect")).toHaveLength(4)
    expect(container.querySelectorAll("polyline")).toHaveLength(1)
    expect(container.querySelector("svg")?.classList.contains("w-5")).toBe(true)
  })

  test("TabIconAnalysis: center candle (rect) + 4 probe circles", () => {
    const { container } = render(<TabIconAnalysis />)
    expect(container.querySelectorAll("circle")).toHaveLength(4)
    expect(container.querySelector("rect")).toBeTruthy()
  })

  test("TabIconDiscover: funnel + 4 filled circles (3 candidates + 1 top pick)", () => {
    const { container } = render(<TabIconDiscover />)
    const filled = container.querySelectorAll('circle[fill="currentColor"]')
    expect(filled).toHaveLength(4)
  })

  test("TabIconPaper: paper path + dog-ear path + 2 mini candle rects", () => {
    const { container } = render(<TabIconPaper />)
    expect(container.querySelectorAll("rect")).toHaveLength(2)
    expect(container.querySelectorAll("path")).toHaveLength(2)
  })

  test("TabIconMore: 9 circles + 1 center filled accent", () => {
    const { container } = render(<TabIconMore />)
    expect(container.querySelectorAll("circle")).toHaveLength(9)
    expect(container.querySelectorAll('circle[fill="currentColor"]')).toHaveLength(1)
  })

  test("All icons spread arbitrary props (aria-label, data-*)", () => {
    const { container } = render(<TabIconDashboard aria-label="首页" data-testid="x" />)
    const svg = container.querySelector("svg")!
    expect(svg.getAttribute("aria-label")).toBe("首页")
    expect(svg.getAttribute("data-testid")).toBe("x")
  })
})
