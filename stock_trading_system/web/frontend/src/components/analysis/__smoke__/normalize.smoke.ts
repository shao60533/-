/**
 * Pure-function smoke checks for the client-side normaliser.
 *
 * Runtime test framework is intentionally not wired up — running this
 * file via ``tsc -b`` is enough: TypeScript verifies the type
 * signatures are sound, and the assertions below run only when this
 * module is imported by a host that wants the runtime guarantee
 * (e.g. a future vitest setup, or a Node smoke harness).
 *
 * The goal is *not* to render React; the goal is to prove that
 * ``normalizeCardForClient`` produces shapes the cards have already
 * proven safe via their own ``safeRecord`` / ``safeText`` guards.
 *
 * Usage (when a runner is added):
 *
 *     vitest run src/components/analysis/__smoke__/normalize.smoke.ts
 */

import { normalizeCardForClient, isRecord, safeRecord, describeShape } from "../shared/defensive"
import { ALL_MALFORMED_FIXTURES, malformedSummary, malformedDebateSynthesisVariants } from "./malformed-payloads"

interface Failure { label: string; reason: string; shape: unknown }
const failures: Failure[] = []

function check(label: string, fn: () => void) {
  try { fn() } catch (err) {
    failures.push({
      label,
      reason: err instanceof Error ? err.message : String(err),
      shape: null,
    })
  }
}

/* ------------------------------------------------------------ */
/* 1. ``normalizeCardForClient`` never throws on any input.    */
/* ------------------------------------------------------------ */

for (const f of ALL_MALFORMED_FIXTURES) {
  check(`normalize(${f.tabKey})`, () => {
    const out = normalizeCardForClient(f.tabKey, f.data)
    // The result must be ``null`` (drop) or a plain record. Never
    // an array, never a primitive — that's the contract the cards
    // rely on. ``safeRecord`` already enforces this internally; we
    // re-check at the boundary so a regression here is caught.
    if (out !== null && !isRecord(out)) {
      throw new Error(`expected null|record, got ${typeof out}`)
    }
  })
}

/* ------------------------------------------------------------ */
/* 2. Summary normalize collapses every malformed sub-field.    */
/* ------------------------------------------------------------ */

const norm = normalizeCardForClient("summary", malformedSummary)
check("summary normalize is a record", () => {
  if (!isRecord(norm)) throw new Error("expected record")
})
check("summary.debate_synthesis collapsed to null when array", () => {
  if (!isRecord(norm)) return
  if (norm.debate_synthesis !== null) {
    throw new Error(`expected null, got ${typeof norm.debate_synthesis}`)
  }
})
check("summary.decision_drivers filtered to records only", () => {
  if (!isRecord(norm)) return
  const drivers = norm.decision_drivers
  if (!Array.isArray(drivers)) throw new Error("expected array")
  for (const d of drivers) {
    if (!isRecord(d)) throw new Error(`non-record driver: ${describeShape(d, 1)}`)
  }
})
check("summary.key_metrics filtered to records only", () => {
  if (!isRecord(norm)) return
  const km = norm.key_metrics
  if (!Array.isArray(km)) throw new Error("expected array")
  for (const m of km) {
    if (!isRecord(m)) throw new Error(`non-record metric: ${describeShape(m, 1)}`)
  }
})

/* ------------------------------------------------------------ */
/* 3. Every debate_synthesis variant survives normalise.        */
/* ------------------------------------------------------------ */

for (const variant of malformedDebateSynthesisVariants) {
  check(`debate_synthesis variant ${describeShape(variant, 1)}`, () => {
    const n = normalizeCardForClient("summary", {
      rating: "Hold", confidence: "medium", action_direction: "wait",
      decision_drivers: [], key_metrics: [],
      debate_synthesis: variant,
      one_line_takeaway: "x",
    })
    if (!isRecord(n)) throw new Error("normalise dropped the whole card")
    const synth = n.debate_synthesis
    // Either null (collapsed) or a record with stances normalised.
    if (synth !== null && !isRecord(synth)) {
      throw new Error(`debate_synthesis must be null|record, got ${typeof synth}`)
    }
    if (isRecord(synth)) {
      for (const k of ["aggressive", "conservative", "neutral"] as const) {
        const s = synth[k]
        if (s !== null && !isRecord(s)) {
          throw new Error(`stance ${k} must be null|record, got ${typeof s}`)
        }
      }
    }
  })
}

/* ------------------------------------------------------------ */
/* 4. ``safeRecord`` round-trips correctly for primitives.      */
/* ------------------------------------------------------------ */

for (const v of [null, undefined, "x", 42, true, [], [{}]]) {
  check(`safeRecord(${describeShape(v, 1)}) is null`, () => {
    if (safeRecord(v) !== null) throw new Error("expected null")
  })
}
check("safeRecord({a:1}) returns the record", () => {
  const obj = { a: 1 }
  if (safeRecord(obj) !== obj) throw new Error("expected identity")
})

/* ------------------------------------------------------------ */
/* 5. Reporting harness — surface failures for any host runner. */
/* ------------------------------------------------------------ */

/** Returns a list of failed checks. Empty list = pass. Run from any
 *  test framework (vitest, node:test, custom CI script). */
export function runNormalizeSmoke(): Failure[] {
  return failures
}

// Self-execute when imported by a Node script via ``import`` side
// effect. The build step itself doesn't trigger this — Vite tree-shakes
// module-level statements that have no observable effect on the
// bundle. We avoid referencing the Node ``process`` global directly
// (this project doesn't depend on @types/node) and instead read from
// ``globalThis`` so the same module compiles in both Vite browser
// builds and a hypothetical Node smoke runner.
declare const globalThis: {
  process?: { env?: Record<string, string | undefined>; exit?: (code: number) => void }
} & typeof window
if (globalThis.process?.env?.RUN_ANALYSIS_SMOKE === "1") {
  if (failures.length > 0) {
    // eslint-disable-next-line no-console
    console.error("[normalize-smoke] FAIL", failures)
    globalThis.process.exit?.(1)
  } else {
    // eslint-disable-next-line no-console
    console.log("[normalize-smoke] OK")
  }
}
