import { render, screen, waitFor, act } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { AnalysisPage } from "../AnalysisPage"

/**
 * v1.3.1 R-MUI-22 — Analysis page layout order
 *
 * 1. DOM order: 发起分析 form Card sits BEFORE 分析记录 inbox Card
 * 2. The inbox empty-state copy still nudges the user toward the form
 *    above (regression check: copy was flipped from "下方" to "上方"
 *    when the cards swapped).
 *
 * apiGet/apiPost are mocked at the module boundary so the page mounts
 * with a deterministic empty state — no real fetch / Socket.IO traffic.
 */

vi.mock("@/lib/api", () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.startsWith("/api/inbox")) return { rows: [], running_total: 0 }
    if (path.startsWith("/api/history/")) return null
    if (path.startsWith("/api/tasks/")) return null
    return null
  }),
  apiPost: vi.fn(async () => ({})),
  apiDel: vi.fn(async () => ({})),
  ApiError: class ApiError extends Error {
    status = 0
    body = {}
  },
}))

vi.mock("@/lib/socket", () => ({
  subscribeTaskStream: vi.fn(() => ({ destroy: () => undefined })),
}))

beforeEach(() => {
  // Reset URL between tests so taskAnchor / urlId never leak.
  window.history.replaceState({}, "", "/")
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("<AnalysisPage> — v1.3.1 R-MUI-22 layout order", () => {
  test("发起分析 Card sits BEFORE 分析记录 Card in DOM order", async () => {
    await act(async () => {
      render(<AnalysisPage />)
    })
    const formTitle = await screen.findByText("发起分析")
    const inboxTitle = await screen.findByText("分析记录")
    // compareDocumentPosition returns DOCUMENT_POSITION_FOLLOWING (4)
    // when the argument follows the receiver in DOM tree order.
    expect(formTitle.compareDocumentPosition(inboxTitle))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  test("empty-state copy points users to the form above (not below)", async () => {
    await act(async () => {
      render(<AnalysisPage />)
    })
    // After the onboarding v1.0 EmptyStateCTA rewrite the copy reads
    // "暂无分析记录，上方表单提交一个新分析开始"; the test asserts the
    // empty-state still references the form ABOVE the inbox.
    await waitFor(() => {
      const empty = screen.getByText(/暂无分析记录/)
      expect(empty).toBeInTheDocument()
      expect(empty.textContent ?? "").toMatch(/上方/)
    })
  })
})
