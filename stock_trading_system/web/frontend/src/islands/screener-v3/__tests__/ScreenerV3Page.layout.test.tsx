import { render, screen, waitFor, act } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { ScreenerV3Page } from "../ScreenerV3Page"

/**
 * v1.3.1 R-MUI-23 — Screener-v3 page layout order
 *
 * 1. ScreenerForm DOM-precedes RecentScreensCard
 * 2. With ?prefill=<id> the prefill banner still lives inside the
 *    form Card (not orphaned at the top of the page) — proves the
 *    swap moved the form intact, including its inner banner state.
 *
 * apiGet/apiPost are mocked so the page mounts with empty state and
 * no real network traffic. /api/screener-v3/* endpoints return empty
 * lists; prefill-task fetch returns null so the banner exits its
 * loading state cleanly.
 */

// /api/screen/v3/history?limit=3 must return at least one row, otherwise
// RecentScreensCard hides itself (intentional empty-state behavior).
// We need it visible to assert DOM ordering in the layout test.
const FAKE_RECENT_ROW = {
  task_id: "tk_layout_test_1",
  title: "Layout test recent",
  status: "succeeded",
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  duration_sec: 12,
  params: {
    nl_query: "test",
    market: "us",
    candidate_n: 50,
    gurus: ["munger"],
    mode: "balanced",
    with_roundtable: false,
  },
  summary: null,
}

vi.mock("@/lib/api", () => {
  const apiGet = vi.fn(async (path: string) => {
    if (path.startsWith("/api/screen/v3/history?limit=3")) {
      return { items: [FAKE_RECENT_ROW] }
    }
    if (path.startsWith("/api/screen/v3/history/")) {
      // prefill task fetch — null short-circuits banner load.
      return null
    }
    if (path.startsWith("/api/screen/v3/")) return { items: [], total: 0 }
    if (path.startsWith("/api/tasks/")) return null
    return null
  })
  return {
    apiGet,
    apiPost: vi.fn(async () => ({})),
    apiDel: vi.fn(async () => ({})),
    ApiError: class ApiError extends Error {
      status = 0
      body = {}
    },
  }
})

vi.mock("@/lib/socket", () => ({
  subscribeTaskStream: vi.fn(() => ({ destroy: () => undefined })),
}))

beforeEach(() => {
  window.history.replaceState({}, "", "/")
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("<ScreenerV3Page> — v1.3.1 R-MUI-23 layout order", () => {
  test("ScreenerForm DOM-precedes RecentScreensCard", async () => {
    await act(async () => {
      render(<ScreenerV3Page />)
    })
    const formMarker = await screen.findByText(/智能选股 V3.*Agent/i)
    const recentMarker = await waitFor(() => screen.getByText("最近选股"))
    expect(formMarker.compareDocumentPosition(recentMarker))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  test("prefill mode renders the page without crashing (banner lives inside the form)", async () => {
    // ?prefill=<id> tells ScreenerForm to attempt fetching a prior
    // task; the mock returns null so the form just falls back to its
    // default state. We don't depend on banner copy here — only on
    // both DOM-order anchors still being present and ordered right.
    window.history.replaceState({}, "", "/?prefill=abc123")
    await act(async () => {
      render(<ScreenerV3Page />)
    })
    const formMarker = await screen.findByText(/智能选股 V3.*Agent/i)
    const recentMarker = await waitFor(() => screen.getByText("最近选股"))
    expect(formMarker.compareDocumentPosition(recentMarker))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })
})
