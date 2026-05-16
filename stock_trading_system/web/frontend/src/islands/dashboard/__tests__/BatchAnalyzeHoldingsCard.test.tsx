import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { BatchAnalyzeHoldingsCard } from "../HoldingsSection"

/**
 * v1.1 BatchAnalyzeHoldingsCard contract
 *
 * Five surface contracts:
 *   1. holdingsCount=0  → button disabled, "暂无持仓" copy
 *   2. holdingsCount=3  → button enabled, "(3)" in label
 *   3. confirm cancelled → no API call made
 *   4. API success      → toast.success with the "查看任务" action
 *   5. API 400 no_holdings → friendly error toast (not the generic one)
 *
 * `apiPost` is the only external dependency the card has; we mock it at
 * the module boundary via vi.mock so the component never touches a real
 * fetch. window.confirm is replaced for every test to decouple the
 * suite from interactive prompts that vitest/jsdom would otherwise hang
 * on.
 */

const apiPostMock = vi.fn()
const toastSuccessMock = vi.fn()
const toastErrorMock = vi.fn()

vi.mock("@/lib/api", () => ({
  apiPost: (...args: unknown[]) => apiPostMock(...args),
  apiGet: vi.fn(),
  apiDel: vi.fn(),
  ApiError: class ApiError extends Error {
    status = 0
    body = {}
  },
}))

vi.mock("@/components/ui/toaster", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccessMock(...args),
    error: (...args: unknown[]) => toastErrorMock(...args),
  },
  Toaster: () => null,
}))

let originalConfirm: typeof window.confirm

beforeEach(() => {
  originalConfirm = window.confirm
  // Default: user clicks OK on the confirm dialog. Individual tests
  // override this when they need to assert the cancel path.
  window.confirm = vi.fn(() => true)
  apiPostMock.mockReset()
  toastSuccessMock.mockReset()
  toastErrorMock.mockReset()
})

afterEach(() => {
  window.confirm = originalConfirm
})


describe("<BatchAnalyzeHoldingsCard> — v1.1", () => {

  test("holdingsCount=0 → button disabled with 暂无持仓 label", () => {
    render(<BatchAnalyzeHoldingsCard holdingsCount={0} />)
    const btn = screen.getByRole("button", { name: /暂无持仓/ })
    expect(btn).toBeDisabled()
    // Sanity: no API call possible from a disabled button.
    fireEvent.click(btn)
    expect(apiPostMock).not.toHaveBeenCalled()
  })

  test("holdingsCount=3 → button enabled with (3) in label", () => {
    render(<BatchAnalyzeHoldingsCard holdingsCount={3} />)
    const btn = screen.getByRole("button", { name: /批量分析持仓 \(3\)/ })
    expect(btn).not.toBeDisabled()
  })

  test("confirm cancelled → API not called, no toast", () => {
    window.confirm = vi.fn(() => false)
    apiPostMock.mockResolvedValue({})
    render(<BatchAnalyzeHoldingsCard holdingsCount={3} />)
    fireEvent.click(screen.getByRole("button", { name: /批量分析持仓/ }))
    expect(window.confirm).toHaveBeenCalledTimes(1)
    expect(apiPostMock).not.toHaveBeenCalled()
    expect(toastSuccessMock).not.toHaveBeenCalled()
    expect(toastErrorMock).not.toHaveBeenCalled()
  })

  test("API 200 → toast.success carries the 查看任务 deep-link action", async () => {
    apiPostMock.mockResolvedValue({
      task_id: "tsk_abc",
      total_holdings: 3,
      status: "queued",
    })
    render(<BatchAnalyzeHoldingsCard holdingsCount={3} />)
    fireEvent.click(screen.getByRole("button", { name: /批量分析持仓/ }))

    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalledTimes(1)
    })
    const [message, opts] = toastSuccessMock.mock.calls[0]
    expect(message).toMatch(/3 只持仓/)
    expect(opts).toMatchObject({
      action: { label: "查看任务" },
    })
    // Confirm POST was made with the spec-required body.
    expect(apiPostMock).toHaveBeenCalledWith(
      "/api/batch/analyze",
      { skip_recent_hours: 4 },
    )
  })

  test("API 400 no_holdings → friendly error toast, not the generic one", async () => {
    apiPostMock.mockRejectedValue({
      status: 400,
      body: { reason: "no_holdings" },
    })
    render(<BatchAnalyzeHoldingsCard holdingsCount={3} />)
    fireEvent.click(screen.getByRole("button", { name: /批量分析持仓/ }))

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalledTimes(1)
    })
    expect(toastErrorMock).toHaveBeenCalledWith("暂无持仓,请先添加持仓")
    expect(toastSuccessMock).not.toHaveBeenCalled()
  })
})
