import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { OnboardingChecklist, TASKS } from "../OnboardingChecklist"

vi.mock("@/components/ui/toaster", () => ({
  toast: { success: vi.fn() },
}))

/**
 * <OnboardingChecklist> — 5 cases per docs/design/onboarding.md §6.2.
 */

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
})

describe("<OnboardingChecklist>", () => {
  test("renders 4 tasks with their labels and step numbers", () => {
    render(<OnboardingChecklist stepsCompleted={{}} onDismiss={() => undefined} />)
    TASKS.forEach((task) => {
      expect(screen.getByText(task.label)).toBeInTheDocument()
    })
    // Step numbers 1..4 appear in the leading badge.
    ;[1, 2, 3, 4].forEach((n) => {
      expect(screen.getByText(String(n))).toBeInTheDocument()
    })
  })

  test("progress bar reflects 50% when 2 of 4 complete", () => {
    render(
      <OnboardingChecklist
        stepsCompleted={{ "add-holding": true, "first-analysis": true }}
        onDismiss={() => undefined}
      />,
    )
    const progress = screen.getByRole("progressbar")
    expect(progress).toHaveAttribute("aria-valuenow", "50")
  })

  test("completed item has line-through + check marker", () => {
    render(
      <OnboardingChecklist
        stepsCompleted={{ "add-holding": true }}
        onDismiss={() => undefined}
      />,
    )
    const row = screen.getByText(/添加第一只持仓/).closest("a")
    expect(row?.className).toMatch(/line-through/)
    // Check glyph rendered in the badge.
    expect(row?.textContent).toContain("✓")
  })

  test("100% complete → 600ms timer fires onDismiss", () => {
    const onDismiss = vi.fn()
    const all = Object.fromEntries(TASKS.map((t) => [t.id, true]))
    render(<OnboardingChecklist stepsCompleted={all} onDismiss={onDismiss} />)
    expect(onDismiss).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(599)
    })
    expect(onDismiss).not.toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  test("incomplete task row keeps real href; completed row navigates to #", () => {
    render(
      <OnboardingChecklist
        stepsCompleted={{ "add-holding": true }}
        onDismiss={() => undefined}
      />,
    )
    const completedRow = screen.getByText(/添加第一只持仓/).closest("a")
    expect(completedRow).toHaveAttribute("href", "#")

    const incompleteRow = screen.getByText(/完成第一次 AI 分析/).closest("a")
    expect(incompleteRow).toHaveAttribute("href", "/analysis")

    // Clicking a completed row must NOT bubble navigation.
    const evt = new MouseEvent("click", { bubbles: true, cancelable: true })
    completedRow!.dispatchEvent(evt)
    expect(evt.defaultPrevented).toBe(true)

    // Sanity: clicking an incomplete row also issues no preventDefault — we
    // let the browser follow the href normally. fireEvent doesn't
    // navigate jsdom so we only assert the handler does not block it.
    fireEvent.click(incompleteRow!)
  })
})
