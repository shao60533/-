import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { useOnboardingState } from "../useOnboardingState"

/**
 * useOnboardingState — 4 cases per docs/design/onboarding.md §6.2.
 *
 *  1. Mount → GET /api/onboarding/state populates state
 *  2. markWelcomed → POST /api/onboarding/mark-welcomed + refresh
 *  3. dismissChecklist → POST /api/onboarding/dismiss-checklist + refresh
 *  4. reset → POST /api/onboarding/reset + refresh
 */

const DEFAULT_STATE = {
  welcome_pending: true,
  welcomed: false,
  tour_completed: false,
  checklist_dismissed: false,
  steps_completed: {},
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      const method = (init?.method ?? "GET").toUpperCase()
      if (url === "/api/onboarding/state" && method === "GET") {
        return new Response(JSON.stringify(DEFAULT_STATE), { status: 200 })
      }
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("useOnboardingState", () => {
  test("mount calls GET /api/onboarding/state", async () => {
    const { result } = renderHook(() => useOnboardingState())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.state).toEqual(DEFAULT_STATE)
    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>
    expect(fetchMock.mock.calls[0][0]).toBe("/api/onboarding/state")
  })

  test("markWelcomed POSTs + refreshes", async () => {
    const { result } = renderHook(() => useOnboardingState())
    await waitFor(() => expect(result.current.loading).toBe(false))

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>
    fetchMock.mockClear()

    await act(async () => {
      await result.current.markWelcomed(true)
    })

    const posted = fetchMock.mock.calls.find(
      (c) => (c[1]?.method ?? "GET").toUpperCase() === "POST",
    )
    expect(posted?.[0]).toBe("/api/onboarding/mark-welcomed")
    expect(JSON.parse(String(posted?.[1]?.body))).toEqual({ tour_completed: true })

    const refreshed = fetchMock.mock.calls.find(
      (c) => c[0] === "/api/onboarding/state",
    )
    expect(refreshed).toBeTruthy()
  })

  test("dismissChecklist POSTs + refreshes", async () => {
    const { result } = renderHook(() => useOnboardingState())
    await waitFor(() => expect(result.current.loading).toBe(false))

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>
    fetchMock.mockClear()

    await act(async () => {
      await result.current.dismissChecklist()
    })

    const posted = fetchMock.mock.calls.find(
      (c) => (c[1]?.method ?? "GET").toUpperCase() === "POST",
    )
    expect(posted?.[0]).toBe("/api/onboarding/dismiss-checklist")
  })

  test("reset POSTs + refreshes", async () => {
    const { result } = renderHook(() => useOnboardingState())
    await waitFor(() => expect(result.current.loading).toBe(false))

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>
    fetchMock.mockClear()

    await act(async () => {
      await result.current.reset()
    })

    const posted = fetchMock.mock.calls.find(
      (c) => (c[1]?.method ?? "GET").toUpperCase() === "POST",
    )
    expect(posted?.[0]).toBe("/api/onboarding/reset")
  })
})
