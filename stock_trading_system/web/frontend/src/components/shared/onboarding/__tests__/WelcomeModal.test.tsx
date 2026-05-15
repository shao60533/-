import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, test, vi } from "vitest"

import { WelcomeModal } from "../WelcomeModal"

/**
 * <WelcomeModal> contract — 3 cases per docs/design/onboarding.md §6.2.
 *  1. open=true renders, open=false renders nothing
 *  2. clicking Skip fires onSkip
 *  3. clicking Start Tour fires onStartTour
 */

describe("<WelcomeModal>", () => {
  test("renders only when open=true", () => {
    const { unmount } = render(
      <WelcomeModal open={false} onSkip={() => undefined} onStartTour={() => undefined} />,
    )
    expect(screen.queryByText(/欢迎使用 StockAI Terminal/)).toBeNull()
    unmount()
    render(
      <WelcomeModal open={true} onSkip={() => undefined} onStartTour={() => undefined} />,
    )
    expect(screen.getByText(/欢迎使用 StockAI Terminal/)).toBeInTheDocument()
    // Risk-warning footer must be present (compliance requirement).
    expect(screen.getByText(/不构成投资建议/)).toBeInTheDocument()
  })

  test("Skip button fires onSkip", () => {
    const onSkip = vi.fn()
    render(
      <WelcomeModal open={true} onSkip={onSkip} onStartTour={() => undefined} />,
    )
    fireEvent.click(screen.getByRole("button", { name: /稍后再说/ }))
    expect(onSkip).toHaveBeenCalledOnce()
  })

  test("Start Tour button fires onStartTour", () => {
    const onStart = vi.fn()
    render(
      <WelcomeModal open={true} onSkip={() => undefined} onStartTour={onStart} />,
    )
    fireEvent.click(screen.getByRole("button", { name: /开始 60 秒导览/ }))
    expect(onStart).toHaveBeenCalledOnce()
  })
})
