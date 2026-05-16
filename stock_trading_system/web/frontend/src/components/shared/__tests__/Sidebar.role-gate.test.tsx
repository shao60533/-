import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, test, vi } from "vitest"

import { MobileTabbar, Sidebar } from "../Sidebar"

/**
 * mobile-ui-v1.3.1 addendum #3 — admin gate on "设置" / "系统设置".
 *
 * 3 cases:
 *   1. non-admin user → desktop sidebar omits "设置"
 *   2. non-admin user → MobileTabbar More sheet omits "系统设置"
 *   3. admin user     → both surfaces include their settings link
 *
 * LLMSwitcher is mocked because its real implementation depends on
 * /api/settings/llm-provider (an admin-only endpoint after this
 * change). The role-gate contract is what we're testing, not the
 * switcher.
 */

vi.mock("@/lib/auth", () => ({
  getCurrentUser: vi.fn(),
}))
vi.mock("../LLMSwitcher", () => ({
  LLMSwitcher: () => <div data-testid="mock-llm-switcher" />,
}))

import { getCurrentUser } from "@/lib/auth"

afterEach(() => {
  vi.clearAllMocks()
})

function setUser(role: string | null) {
  ;(getCurrentUser as unknown as ReturnType<typeof vi.fn>).mockReturnValue(
    role === null
      ? null
      : { id: 1, displayName: "Test", role },
  )
}

describe("<Sidebar> + <MobileTabbar> role gate", () => {
  test("non-admin: desktop Sidebar omits the 设置 link", () => {
    setUser("user")
    render(<Sidebar />)
    expect(screen.queryByText("设置")).toBeNull()
    // Sanity: a non-gated entry still renders.
    expect(screen.getByText("AI 分析")).toBeInTheDocument()
  })

  test("non-admin: MobileTabbar More sheet omits 系统设置 but keeps 账号", async () => {
    setUser("user")
    render(<MobileTabbar />)
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /更多/ }))
    })
    await waitFor(() => {
      expect(screen.getByText("账号")).toBeInTheDocument()
    })
    expect(screen.queryByText("系统设置")).toBeNull()
  })

  test("admin: both surfaces include their settings link", async () => {
    setUser("admin")
    const { unmount } = render(<Sidebar />)
    expect(screen.getByText("设置")).toBeInTheDocument()
    unmount()

    render(<MobileTabbar />)
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /更多/ }))
    })
    await waitFor(() => {
      expect(screen.getByText("系统设置")).toBeInTheDocument()
    })
  })
})
