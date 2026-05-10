import { render, screen } from "@testing-library/react"
import { describe, expect, test } from "vitest"

import { Sparkline } from "../Sparkline"

/**
 * v1.3.1 R-MUI-20 Sparkline contract
 *
 * 1. Empty input         → render nothing (downgrade-safe)
 * 2. <2 finite points    → render nothing (still degraded)
 * 3. Up-trend default    → stroke uses --color-accent-green
 * 4. Down-trend default  → stroke uses --color-accent-red
 * 5. positive override   → respected even when raw values trend down
 *
 * The path math itself is exercised by playwright visual regression;
 * these unit tests pin only the gating + color-direction policy.
 */

const SVG_SELECTOR = "svg[data-sparkline]"

describe("<Sparkline> — v1.3.1 R-MUI-20", () => {
  test("renders nothing for empty input", () => {
    const { container } = render(<Sparkline values={[]} />)
    expect(container.querySelector(SVG_SELECTOR)).toBeNull()
  })

  test("renders nothing for fewer than 2 finite values", () => {
    const { container } = render(<Sparkline values={[NaN, 100]} />)
    // Only one finite value → can't draw a line.
    expect(container.querySelector(SVG_SELECTOR)).toBeNull()
  })

  test("up-trend uses green stroke and sits in the document", () => {
    const { container } = render(
      <Sparkline values={[100, 110, 130, 150, 200]} />,
    )
    const svg = container.querySelector(SVG_SELECTOR)
    expect(svg).not.toBeNull()
    expect(svg).toHaveAttribute("aria-hidden", "true")
    const strokePath = svg!.querySelectorAll("path")[1]
    expect(strokePath.getAttribute("stroke"))
      .toContain("--color-accent-green")
  })

  test("down-trend uses red stroke", () => {
    const { container } = render(
      <Sparkline values={[200, 180, 150, 120, 90]} />,
    )
    const strokePath = container.querySelectorAll(`${SVG_SELECTOR} path`)[1]
    expect(strokePath.getAttribute("stroke"))
      .toContain("--color-accent-red")
  })

  test("positive=true override wins over derived direction", () => {
    // Raw values trend down, but we explicitly mark positive=true to
    // pin the color (use-case: caller wants to color by parent context,
    // not by sparkline direction).
    const { container } = render(
      <Sparkline values={[200, 180, 150, 120, 90]} positive />,
    )
    const strokePath = container.querySelectorAll(`${SVG_SELECTOR} path`)[1]
    expect(strokePath.getAttribute("stroke"))
      .toContain("--color-accent-green")
  })
})
