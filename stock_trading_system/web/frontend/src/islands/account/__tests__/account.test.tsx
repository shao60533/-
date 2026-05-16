import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest"

import { AccountPage } from "../AccountPage"

/**
 * AccountPage — 3 cases per mobile-ui-v1.3.1 addendum #3 §3 test plan.
 *
 *   1. renders user info (display name + role badge + ID row)
 *   2. logout confirm=yes posts /api/auth/logout + navigates to /login
 *   3. logout confirm=cancel does NOT call the API
 */

vi.mock("@/lib/auth", () => ({
  getCurrentUser: vi.fn(),
}))
vi.mock("@/components/ui/toaster", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

import { getCurrentUser } from "@/lib/auth"

const apiPostMock = vi.fn()
vi.mock("@/lib/api", () => ({
  apiPost: (...args: unknown[]) => apiPostMock(...args),
}))

const originalLocation = window.location

beforeEach(() => {
  ;(getCurrentUser as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
    id: 42,
    displayName: "Alice",
    role: "user",
  })
  apiPostMock.mockReset()
  apiPostMock.mockResolvedValue({})
  // Redefine window.location so the post-logout navigation in the
  // component (window.location.href = "/login") is observable.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, href: "/account" },
  })
})

afterEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(window, "location", {
    configurable: true,
    value: originalLocation,
  })
})

describe("<AccountPage>", () => {
  test("renders user info card", () => {
    render(<AccountPage />)
    // displayName appears in both the header + the 显示名 info row.
    expect(screen.getAllByText("Alice").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("用户")).toBeInTheDocument()
    expect(screen.getByText("#42")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /退出登录/ }),
    ).toBeInTheDocument()
  })

  test("logout confirm=yes posts to /api/auth/logout and navigates to /login", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true)
    render(<AccountPage />)
    fireEvent.click(screen.getByRole("button", { name: /退出登录/ }))
    await waitFor(() => {
      expect(apiPostMock).toHaveBeenCalledWith("/api/auth/logout", {})
    })
    expect(window.location.href).toBe("/login")
    confirmSpy.mockRestore()
  })

  test("logout confirm=cancel does NOT call the API", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false)
    render(<AccountPage />)
    fireEvent.click(screen.getByRole("button", { name: /退出登录/ }))
    expect(apiPostMock).not.toHaveBeenCalled()
    expect(window.location.href).toBe("/account")
    confirmSpy.mockRestore()
  })
})
