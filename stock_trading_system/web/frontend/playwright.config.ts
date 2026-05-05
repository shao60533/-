import { defineConfig, devices } from "@playwright/test"

/**
 * 2026-05-05 mobile-overflow scrollWidth verification.
 *
 * Spins up the project's existing Vite dev server (`npm run dev`) and
 * runs each spec at three viewport widths (320 / 375 / 414). The dev
 * harness pages live in `e2e/dev/*.html` — each one mounts a single
 * island so the full Flask backend doesn't have to be online for
 * layout assertions to fire. API calls fail with empty responses; the
 * island then renders skeletons / error states, both of which are
 * legitimate layouts and equally valid targets for `scrollWidth`
 * overflow checks.
 *
 * To run locally:
 *   cd stock_trading_system/web/frontend
 *   npx playwright test
 *
 * To update screenshots:
 *   npx playwright test --update-snapshots
 */
export default defineConfig({
  testDir: "./e2e/specs",
  fullyParallel: false,         // dev server only handles ~one client well
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "./e2e/.results",

  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Default mobile spec; per-test viewport overrides below.
    viewport: { width: 375, height: 667 },
  },

  // Auto-start the existing Vite dev server. `reuseExistingServer` lets
  // a developer running `npm run dev` in another terminal reuse it.
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173/e2e/dev/screener-v3.html",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },

  projects: [
    {
      name: "chromium-mobile",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
})
