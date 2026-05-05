import { test, expect } from "@playwright/test"
import { mkdir } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

// `__dirname` is undefined in ES module scope; reconstruct via
// `import.meta.url` so the screenshot dir resolves consistently
// whether playwright invokes us through tsx or node-esm.
const __dirname = path.dirname(fileURLToPath(import.meta.url))

/**
 * Mobile UI Phase 1 verification.
 *
 * Each test loads one island in the dev harness, sets a viewport width
 * (320 / 375 / 414), waits for the React tree to mount, and asserts
 * that `document.documentElement.scrollWidth <= window.innerWidth + 1`
 * — the contract from the user's mobile UI spec. The +1 absorbs the
 * sub-pixel rounding that some browsers emit for hairline borders.
 *
 * Screenshots are archived to docs/qa/mobile-2026-05-05/{page}-{w}.png
 * regardless of pass/fail so the PR reviewer can eyeball the layouts.
 */

// 12 islands × 3 widths = 36 tests covering the full mobile sweep.
// Order matches the user's original verification list so the run-log
// reads top-to-bottom in the same shape as the spec.
const PAGES = [
  { key: "dashboard",        url: "/e2e/dev/dashboard.html"        },
  { key: "analysis",         url: "/e2e/dev/analysis.html"         },
  { key: "reports",          url: "/e2e/dev/reports.html"          },
  { key: "screener-v3",      url: "/e2e/dev/screener-v3.html"      },
  { key: "portfolio",        url: "/e2e/dev/portfolio.html"        },
  { key: "alerts",           url: "/e2e/dev/alerts.html"           },
  { key: "paper-trade-list", url: "/e2e/dev/paper-trade-list.html" },
  { key: "paper-trade",      url: "/e2e/dev/paper-trade.html"      },
  { key: "tasks",            url: "/e2e/dev/tasks.html"            },
  { key: "backtest",         url: "/e2e/dev/backtest.html"         },
  { key: "settings",         url: "/e2e/dev/settings.html"         },
  { key: "history",          url: "/e2e/dev/history.html"          },
]

const WIDTHS = [320, 375, 414]

const SCREENSHOT_DIR = path.resolve(
  __dirname, "../../../../../docs/qa/mobile-2026-05-05-phase2",
)

test.beforeAll(async () => {
  await mkdir(SCREENSHOT_DIR, { recursive: true })
})

for (const page of PAGES) {
  for (const width of WIDTHS) {
    test(`${page.key} @ ${width}px — no horizontal overflow`, async ({ page: pw }) => {
      await pw.setViewportSize({ width, height: 800 })
      // Vite dev server lazy-compiles dependencies on first request;
      // a cold module graph for an island can take 20–40s before the
      // bundle is available. `networkidle` waits for that flush plus
      // any /api/* requests the island fires (which 404 against the
      // bare dev server but still count toward the idle threshold).
      await pw.goto(page.url, { waitUntil: "networkidle", timeout: 60_000 })
      // Once the network is quiet, give React a generous window to
      // mount the AppShell + island. Layout assertions only need
      // *some* DOM to observe; the cap is intentionally lax.
      await pw.waitForFunction(() => {
        const root = document.getElementById("react-root")
        return root && root.children.length > 0
      }, null, { timeout: 30_000 })
      // Brief settle for Suspense / lazy-imported chart panels.
      await pw.waitForTimeout(500)

      // Archive the screenshot before asserting so even a failing run
      // leaves a visual trail the reviewer can inspect.
      const file = path.join(SCREENSHOT_DIR, `${page.key}-${width}.png`)
      await pw.screenshot({ path: file, fullPage: true })

      const overflow = await pw.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }))
      expect(
        overflow.scrollWidth,
        `${page.key} @ ${width}px overflowed: scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth}`,
      ).toBeLessThanOrEqual(overflow.innerWidth + 1)
    })
  }
}
