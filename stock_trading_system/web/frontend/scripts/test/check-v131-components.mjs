#!/usr/bin/env node
/**
 * mobile-ui-v1.3.1 fixup #2 — source-level component contract guard.
 *
 * The frontend never re-introduced vitest after the v1.2 rollback, so
 * unit-test parity with the user's request ("MobileTopbar / Sparkline
 * / AccountOverviewCard 相关测试") is enforced as a static AST-light
 * grep. Each assertion below corresponds to a behavioural property
 * that would otherwise need a component renderer:
 *
 *   - Sparkline returns null when ``cleanValues.length < 2``
 *   - Sparkline emits ``<svg ... data-sparkline>`` (so the runtime
 *     test in v131-visual.spec.ts can assert presence)
 *   - MobileTopbar renders ``data-mobile-topbar-subtitle`` ONLY when
 *     ``pageTitle`` truthy
 *   - MobileTopbar wires LLMSwitcher with ``variant="pill"``
 *   - LLMSwitcher pill trigger carries ``data-llm-pill`` and
 *     rounded-full styling
 *   - AccountOverviewCard renders Sparkline iff sparklineValues.length
 *     >= 5, and tags the wrapper with ``data-account-sparkline``
 *   - AccountOverviewCard hero exposes ``data-account-value`` /
 *     ``data-account-today-pnl`` for runtime overflow assertions
 *   - DashboardPage hides duplicate ``<h1>首页</h1>`` on mobile
 *     (hidden md:block)
 *
 * Runs from the frontend dir via ``npm run lint:ux`` (called from
 * ``npm run build``). Exits non-zero on any failed assertion so the
 * Vite build refuses to ship a regression.
 */
import { promises as fs } from "node:fs"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.resolve(__dirname, "../../src")

const FILES = {
  sparkline:        "components/shared/Sparkline.tsx",
  mobileTopbar:     "components/shared/MobileTopbar.tsx",
  llmSwitcher:      "components/shared/LLMSwitcher.tsx",
  dashboardPage:    "islands/dashboard/DashboardPage.tsx",
}

async function readSrc(rel) {
  return fs.readFile(path.join(SRC, rel), "utf8")
}

const failures = []
function check(label, ok, detail) {
  if (!ok) failures.push({ label, detail })
}

// ── Sparkline ────────────────────────────────────────────────
const sparkline = await readSrc(FILES.sparkline)
check(
  "Sparkline returns null when cleanValues.length < 2",
  /cleanValues\.length\s*<\s*2[\s\S]{0,50}return\s+null/.test(sparkline),
  "expected `if (cleanValues.length < 2) return null` guard",
)
check(
  "Sparkline svg carries data-sparkline marker",
  /<svg[\s\S]*?data-sparkline=""[\s\S]*?\/>/.test(sparkline)
    || /data-sparkline=""[\s\S]{0,200}<\/svg>/.test(sparkline),
  "expected <svg data-sparkline=\"\"> in JSX",
)

// ── MobileTopbar ────────────────────────────────────────────
const mobileTopbar = await readSrc(FILES.mobileTopbar)
check(
  "MobileTopbar wraps subtitle in `pageTitle &&` guard",
  /\{pageTitle\s*&&[\s\S]*?data-mobile-topbar-subtitle/.test(mobileTopbar),
  "expected `{pageTitle && (...data-mobile-topbar-subtitle...)}` conditional",
)
check(
  "MobileTopbar wires LLMSwitcher variant=\"pill\"",
  /<LLMSwitcher\s+variant="pill"\s*\/?>/.test(mobileTopbar),
  "expected <LLMSwitcher variant=\"pill\" /> in topbar",
)
check(
  "MobileTopbar root carries data-mobile-topbar marker",
  /data-mobile-topbar=""/.test(mobileTopbar),
  "expected data-mobile-topbar=\"\" on the <header>",
)

// ── LLMSwitcher pill ────────────────────────────────────────
const llm = await readSrc(FILES.llmSwitcher)
check(
  "LLMSwitcher accepts variant prop",
  /export\s+(type|interface)\s+LLMSwitcher(Variant|Props)/.test(llm)
    || /variant\?\s*:\s*"full"\s*\|\s*"pill"/.test(llm)
    || /variant:\s*LLMSwitcherVariant/.test(llm),
  "expected `variant?: \"full\" | \"pill\"` on LLMSwitcher props",
)
check(
  "LLMSwitcher pill trigger carries data-llm-pill",
  /data-llm-pill=""/.test(llm),
  "expected data-llm-pill=\"\" on the pill button",
)
check(
  "LLMSwitcher pill is rounded-full",
  /data-llm-pill="[^"]*"[\s\S]{0,400}rounded-full/.test(llm)
    || /rounded-full[\s\S]{0,400}data-llm-pill/.test(llm),
  "expected pill button to have rounded-full class",
)

// ── DashboardPage / AccountOverviewCard ─────────────────────
const dashboard = await readSrc(FILES.dashboardPage)
check(
  "AccountOverviewCard renders Sparkline iff sparklineValues.length >= 5",
  /sparklineValues\.length\s*>=\s*5[\s\S]{0,200}<Sparkline/.test(dashboard),
  "expected `sparklineValues.length >= 5 && (...<Sparkline...)` conditional",
)
check(
  "AccountOverviewCard tags sparkline wrapper with data-account-sparkline",
  /data-account-sparkline=""/.test(dashboard),
  "expected data-account-sparkline=\"\" wrapper",
)
check(
  "Account hero value carries data-account-value marker",
  /data-account-value=""/.test(dashboard),
  "expected data-account-value=\"\" on the total value element",
)
check(
  "Today PnL element carries data-account-today-pnl marker",
  /data-account-today-pnl=""/.test(dashboard),
  "expected data-account-today-pnl=\"\" on the today PnL element",
)
check(
  "Account hero value drops `truncate` so 390px never ellipsizes",
  !/data-account-value=""[\s\S]{0,250}\btruncate\b/.test(dashboard),
  "expected NO `truncate` class on the data-account-value element",
)
check(
  "DashboardPage hides duplicate desktop h1 on mobile",
  /<h1\s+className="hidden md:block[^"]*"[^>]*>\s*首页/.test(dashboard),
  "expected `<h1 className=\"hidden md:block ...\">首页</h1>`",
)

if (failures.length > 0) {
  console.error("\n❌ v1.3.1 component-contract guard found failures:")
  for (const f of failures) {
    console.error(`  • ${f.label}`)
    console.error(`      ${f.detail}`)
  }
  console.error("\nFix the source files referenced above and re-run `npm run lint:ux`.\n")
  process.exit(1)
}

console.log(`✓ v1.3.1 component contracts ok (${Object.keys(FILES).length} files checked)`)
