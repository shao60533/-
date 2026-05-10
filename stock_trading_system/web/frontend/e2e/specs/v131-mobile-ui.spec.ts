import { test, expect } from "@playwright/test"

/**
 * v1.3.1 mobile UI verification — five cases mandated by
 * docs/prd/mobile-ui-v1.3.1.md §8.2.
 *
 * Each test boots a real island via the existing Vite dev harness
 * (`/static/dist/e2e/dev/<page>.html`). API calls fail (no Flask
 * backend in this fixture); React renders skeletons + error states,
 * but the static DOM scaffolding under test (topbar, page titles,
 * card ordering) is present regardless. Where data IS required (the
 * sparkline test), we intercept `/api/dashboard` and synthesize a
 * history slice with ≥ 5 points.
 */

const PAGES = {
  dashboard: "/static/dist/e2e/dev/dashboard.html",
  analysis: "/static/dist/e2e/dev/analysis.html",
  "screener-v3": "/static/dist/e2e/dev/screener-v3.html",
} as const


test.describe("v1.3.1 R-MUI-19 — mobile topbar surface", () => {

  test("any first-tier page shows ⚡ StockAI Terminal brand at the top", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto(PAGES.dashboard)
    // Use a regex match on the brand text — getByText with exact emoji
    // can be brittle if the runtime collapses whitespace or splits the
    // text node. Header element + StockAI Terminal substring is enough
    // to prove the topbar mounted.
    const header = page.locator("header.md\\:hidden").first()
    await expect(header).toContainText("StockAI Terminal", { timeout: 15_000 })
  })

  test("LLMSwitcher chip clickable + opens a dropdown menu", async ({ page }) => {
    // Mock the LLM-state endpoint that LLMSwitcher actually consumes.
    // Without this, `if (!state) return null` keeps the chip out of
    // the DOM entirely and the topbar shows only the brand link.
    await page.route("**/api/settings/llm-provider", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          active: "qwen",
          has_qwen_key: true,
          has_gemini_key: false,
          has_openrouter_key: false,
          locked_by_env: false,
        }),
      }),
    )

    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto(PAGES.dashboard)

    // Wait for the topbar header to mount before probing for the chip.
    const header = page.locator("header.md\\:hidden").first()
    await expect(header).toBeVisible({ timeout: 15_000 })

    // Use the data-llm-pill marker for an unambiguous selector. The
    // chip appears only after the LLM state resolves.
    const trigger = header.locator("[data-llm-pill]")
    await expect(trigger).toBeVisible({ timeout: 10_000 })
    await trigger.click()
    // Dropdown menu items use radix's [role=menu] container.
    await expect(page.locator('[role="menu"]')).toBeVisible({ timeout: 5_000 })
  })

})


test.describe("v1.3.1 R-MUI-20 — sparkline above the fold", () => {

  test("dashboard at 375px renders embedded sparkline svg when history is available", async ({ page }) => {
    // Build a history with 5+ points so the sparkline gating threshold
    // passes. /api/dashboard is the only fetch that needs real data;
    // others can return empty defaults.
    await page.route("**/api/dashboard*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          pnl: { total_value: 12345.67, total_pnl: 678.9, total_pnl_pct: 5.81 },
          history: Array.from({ length: 12 }, (_, i) => ({
            ts: `2026-05-${String(i + 1).padStart(2, "0")}`,
            total_value: 10_000 + i * 250,
          })),
          alerts_count: 0,
          holdings_count: 3,
          tasks_count: 0,
        }),
      }),
    )
    await page.route("**/api/portfolio/summary", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total_value: 12345.67,
          total_pnl: 678.9,
          total_pnl_pct: 5.81,
          today_pnl: 12.34,
          today_pnl_pct: 0.1,
          holdings_count: 3,
        }),
      }),
    )

    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto(PAGES.dashboard)

    // Sparkline emits an svg with [data-sparkline] when ≥ 5 finite
    // history points are available. Allow generous timeout — the
    // dashboard pulls four endpoints in parallel before paint.
    const sparkline = page.locator("svg[data-sparkline]")
    await expect(sparkline).toBeVisible({ timeout: 15_000 })
  })

})


test.describe("v1.3.1 R-MUI-22 — Analysis page form-first ordering", () => {

  test("/analysis renders 发起分析 ABOVE 分析记录 in DOM order", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto(PAGES.analysis)

    const formTitle = page.getByText("发起分析").first()
    const inboxTitle = page.getByText("分析记录").first()
    await expect(formTitle).toBeVisible({ timeout: 10_000 })
    await expect(inboxTitle).toBeVisible({ timeout: 10_000 })

    // compareDocumentPosition: 4 ⇒ inbox follows form in DOM order.
    const order = await formTitle.evaluate((form, inbox: Element) =>
      form.compareDocumentPosition(inbox), await inboxTitle.elementHandle())
    expect(order).toBe(4)
  })

})


test.describe("v1.3.1 R-MUI-23 — Screener-v3 form-first ordering", () => {

  test("/screener-v3 home view renders ScreenerForm ABOVE 最近选股", async ({ page }) => {
    // Recent screens card hides itself when empty; supply 1 row so we
    // can verify ordering. /api/screen/v3/history?limit=3 is the path.
    await page.route("**/api/screen/v3/history**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{
            task_id: "tk_e2e_1",
            title: "e2e test recent",
            status: "succeeded",
            created_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
            duration_sec: 12,
            params: {
              nl_query: "x", market: "us", candidate_n: 50,
              gurus: ["munger"], mode: "balanced", with_roundtable: false,
            },
            summary: null,
          }],
        }),
      }),
    )

    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto(PAGES["screener-v3"])

    const formMarker = page.getByText(/智能选股 V3.*Agent/i).first()
    const recentMarker = page.getByText("最近选股").first()
    await expect(formMarker).toBeVisible({ timeout: 10_000 })
    await expect(recentMarker).toBeVisible({ timeout: 10_000 })

    const order = await formMarker.evaluate((form, recent: Element) =>
      form.compareDocumentPosition(recent), await recentMarker.elementHandle())
    expect(order).toBe(4)
  })

})
