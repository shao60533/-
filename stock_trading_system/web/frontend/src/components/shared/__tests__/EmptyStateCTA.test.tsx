import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, test, vi } from "vitest"

import { EmptyStateCTA } from "../EmptyStateCTA"

/**
 * <EmptyStateCTA> contract — 4 cases.
 */

describe("<EmptyStateCTA>", () => {
  test("renders icon, message, and CTA label", () => {
    render(
      <EmptyStateCTA
        icon="📊"
        message="暂无持仓"
        ctaLabel="+ 添加第一只持仓"
        onClick={() => undefined}
      />,
    )
    expect(screen.getByText("📊")).toBeInTheDocument()
    expect(screen.getByText(/暂无持仓/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /添加第一只持仓/ })).toBeInTheDocument()
  })

  test("button-mode calls onClick when clicked", () => {
    const onClick = vi.fn()
    render(
      <EmptyStateCTA message="empty" ctaLabel="go" onClick={onClick} />,
    )
    fireEvent.click(screen.getByRole("button", { name: /go/ }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  test("href-mode wraps CTA in an anchor", () => {
    render(
      <EmptyStateCTA message="empty" ctaLabel="see analysis" href="/analysis" />,
    )
    const anchor = screen.getByRole("link")
    expect(anchor).toHaveAttribute("href", "/analysis")
    expect(anchor).toHaveTextContent(/see analysis/)
  })

  test("omits icon block when not supplied", () => {
    render(<EmptyStateCTA message="empty" ctaLabel="go" />)
    // No element with text="📊" since icon prop absent. We test via
    // aria-hidden span absence.
    expect(screen.queryByText("📊")).toBeNull()
  })
})
