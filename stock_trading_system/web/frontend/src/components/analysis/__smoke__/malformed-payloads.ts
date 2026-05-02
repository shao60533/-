/**
 * Storybook-like fixture catalogue of malformed structured-card
 * payloads observed (or plausible) in production.
 *
 * Frontend has no runtime test framework wired up, but every entry
 * here is consumed by ``normalize.smoke.ts`` (pure-function smoke
 * checks) and by ``tsc -b`` (the build verifies these shapes still
 * compile against ``normalizeCardForClient`` + ``OverviewCard``
 * prop types, both of which accept ``unknown``).
 *
 * If you can hit prod /api/history/<id> directly, paste the real
 * blob into ``RAW_PROD_SNDK_17`` below and re-run
 * ``npm run build && pytest tests/web/test_analysis_sndk_smoke.py``.
 * The harness is intentionally tolerant — every shape here MUST
 * NOT throw.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

/** A truly hostile ``rendering.summary`` blob — every nested field is
 *  the wrong type. The Overview card must render the empty/neutral
 *  state on this without throwing. */
export const malformedSummary: any = {
  rating: { nested: "obj" },                 // wrong: object instead of string
  confidence: ["high"],                       // wrong: array
  action_direction: 42,                       // wrong: number
  // ``key_metrics`` items are mixed scalar / null / record / array.
  key_metrics: [
    "string-metric",
    null,
    { label: "PE", value: { foo: "bar" }, tone: "neutral" },
    { label: "Vol", value: ["a", "b"], tone: "garbage-enum" },
    42,
  ],
  // ``debate_synthesis`` is sometimes an array (LLM serialised the
  // three stances as a list of dicts).
  debate_synthesis: [
    { claim: "x", evidence: "y", limitation: "z" },
    { claim: "x2", evidence: "y2", limitation: "z2" },
  ],
  decision_drivers: [
    "string-driver",
    null,
    { headline: "Real driver", detail: "Real detail" },
    [],                                       // wrong: array item
  ],
  one_line_takeaway: { foo: "bar" },         // wrong: object
}

/** ``debate_synthesis`` is the field most likely to trip the Overview
 *  card. Variants here cover every wrong-type case the LLM produces. */
export const malformedDebateSynthesisVariants: readonly unknown[] = [
  null,
  undefined,
  "string-not-record",
  ["array", "instead", "of", "record"],
  42,
  true,
  // Partial record — verdict only, no stances:
  { verdict: "Hold (no stance details)" },
  // Stances are themselves malformed:
  {
    aggressive: "string-not-stance",
    conservative: ["array"],
    neutral: 42,
    verdict: "verdict OK",
  },
  // Stance objects exist but missing fields:
  {
    aggressive: { claim: "ok" },              // missing evidence/limitation
    conservative: {},
    neutral: null,
    verdict: "",
  },
]

/** ``Market.support_resistance`` produced by an over-eager LLM where
 *  ``price`` is variously a string, an object, or missing. */
export const malformedMarket: any = {
  trend: "BULLISH ",                           // trailing whitespace, wrong case
  indicators: [
    "string-indicator",
    null,
    { name: "RSI", value: { v: 32 }, signal: "bearish" },
  ],
  support_resistance: [
    { price: 32.5, kind: "support", strength: "strong" },
    { price: "—", kind: "resistance" },
    { price: { value: 38.4 }, kind: "resistance" },
    null,
    "string-level",
  ],
  patterns: [null, "lower-high", "", "rising-wedge", 42],
  summary: { obj: "instead-of-string" },
}

/** ``Decision.entry_zone`` shape variants — sometimes a scalar, an
 *  array, or strings instead of numbers. */
export const malformedDecision: any = {
  final_action: "buy ",                        // wrong: case + whitespace
  conviction: { high: true },                  // wrong: object
  entry_zone: "150-160",                       // wrong: string
  structural_stop: "n/a",                      // wrong: string
  take_profit_levels: [
    { price: "30", weight_pct: 50 },
    { price: "bad", weight_pct: "x" },
    null,
    "string-level",
  ],
  preconditions: ["volume confirms", null, 42],
  exit_conditions: null,                       // wrong: should be array
  alternative_scenarios: "table-not-array",
  one_line_summary: ["wrong", "type"],
  time_horizon: "weekly",                      // unknown enum
}

/** Generic per-tab fixtures — used by the smoke harness to assert
 *  ``normalizeCardForClient`` returns either a record or null on each. */
export const ALL_MALFORMED_FIXTURES: readonly { tabKey: string; data: unknown }[] = [
  { tabKey: "summary", data: malformedSummary },
  { tabKey: "summary", data: ["array-not-record"] },
  { tabKey: "summary", data: "string-not-record" },
  { tabKey: "summary", data: null },
  { tabKey: "Market", data: malformedMarket },
  { tabKey: "Decision", data: malformedDecision },
  { tabKey: "Sentiment", data: { mood: "EXTREME_FEAR  ", mood_score: "—", drivers: ["x"] } },
  { tabKey: "News", data: { headlines: ["x"], catalysts: null, summary: 42 } },
  { tabKey: "Fundamentals", data: { valuation: "x", growth: null, balance_sheet: ["a"], quality_score: "—" } },
  { tabKey: "Investment Debate", data: { bull_arguments: "x", bear_arguments: null, verdict: "weird" } },
  { tabKey: "Risk Assessment", data: { aggressive: "x", conservative: null, top_risks: "string" } },
  // Production /analysis/17 raw — fill this in if a debug fetch yields
  // the actual blob; until then the synthesised shapes above are the
  // closest approximation.
  { tabKey: "summary", data: { /* paste prod here */ } },
]
