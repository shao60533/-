import { test, expect } from "@playwright/test"

/**
 * tab-icons-v1 — Sidebar 5 tab 图标已切换到 custom SVG 集合
 * (TabIconDashboard / Analysis / Discover / Paper / More).
 *
 * Lucide 图标主要由 <path> 元素组成；新自定义图标显式使用 <rect> /
 * <circle> / <polyline>。回归点：底部 tabbar 的每个 button 的 svg 至少
 * 包含一个 rect/circle/polyline 元素 → 证明换图成功。
 */

test("底部 5 tab 使用新自定义图标 (非 lucide)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/static/dist/e2e/dev/dashboard.html")

  const tabbar = page.locator("[data-mobile-tabbar]")
  await expect(tabbar).toBeVisible({ timeout: 15_000 })

  // MOBILE_PRIMARY 渲染 4 个 <a data-mobile-tab="...">，"更多" 是
  // <button data-mobile-tab="more"> — 总共 5 个 [data-mobile-tab] 节点。
  const tabs = tabbar.locator("[data-mobile-tab]")
  await expect(tabs).toHaveCount(5)

  for (let i = 0; i < 5; i++) {
    const svg = tabs.nth(i).locator("svg")
    await expect(svg).toBeVisible()
    const customElements = await svg.locator("rect, circle, polyline").count()
    expect(customElements,
      `tab ${i} svg should contain rect/circle/polyline (custom icon)`)
      .toBeGreaterThan(0)
  }
})
