/**
 * Defensive helpers used across the 8 structured analysis cards.
 *
 * Production /analysis/17 (SNDK) initially white-screened on a single
 * bad ``support_resistance[i].price`` string. Wrapping every render in
 * an ErrorBoundary is necessary but not sufficient — even after the
 * boundary, /analysis/17 still showed "结构化卡片渲染失败" because the
 * Overview card itself was throwing on a non-record ``debate_synthesis``
 * (or a ``decision_drivers`` whose items were strings/null).
 *
 * The contract for this module is therefore:
 *   1. Every helper is total — it never throws on any input.
 *   2. ``normalizeCardForClient`` mirrors the backend ``_normalize_card``
 *      so even if production DB still has a stale unnormalised payload,
 *      the React layer self-heals before the card sees it.
 */

/* ------------------------------------------------------------------ */
/* Primitive guards                                                   */
/* ------------------------------------------------------------------ */

/** Always return an array. ``null`` / ``undefined`` / scalars / objects
 *  all degrade to ``[]`` so map/filter/sort never explode. */
export function safeArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : []
}

/** True iff ``v`` is a plain record (object, not array, not null).
 *  Used everywhere we rely on indexing into a key/value bag. */
export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v)
}

/** Return ``v`` as a record or ``null``. Mirrors ``isinstance(card, dict)``
 *  on the backend. Use this anywhere the card body assumes "this is an
 *  object I can read fields off of." */
export function safeRecord(v: unknown): Record<string, unknown> | null {
  return isRecord(v) ? v : null
}

/** Coerce to a finite number or ``null``. Strips trailing ``%`` and
 *  commas so akshare-style ``"15.3%"`` parses cleanly. */
export function toFiniteNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null
  if (typeof v === "number") return Number.isFinite(v) ? v : null
  if (typeof v === "string") {
    const cleaned = v.trim().replace(/,/g, "").replace(/%$/, "")
    const n = Number(cleaned)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** Format a finite number to ``digits`` decimals; ``"—"`` otherwise.
 *  Tolerates string-encoded numbers from less-strict providers. */
export function fmtNumber(v: unknown, digits = 2): string {
  const n = toFiniteNumber(v)
  return n === null ? "—" : n.toFixed(digits)
}

/** True iff ``v`` is a non-empty string after trimming. Used so cards
 *  can hide whole sections instead of rendering empty headers. */
export function nonEmptyStr(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0
}

/** Return a React-safe text value. React throws when plain objects are
 *  rendered as children; malformed LLM payloads occasionally put objects
 *  where schemas expect strings. Keep scalar values, hide objects/arrays. */
export function safeText(v: unknown, fallback = ""): string {
  if (typeof v === "string") return v
  if (typeof v === "number" && Number.isFinite(v)) return String(v)
  if (typeof v === "boolean") return v ? "true" : "false"
  return fallback
}

/** Look up a tone class from a record; fall back to ``fallback`` for
 *  any unknown key (or null/undefined). Cards use this everywhere they
 *  used to do ``MAP[v]`` directly — that pattern threw a "cannot read
 *  className of undefined" when the LLM returned a value outside the
 *  enum (e.g. ``"BULLISH "`` with a trailing space).
 */
export function lookupTone<T extends string>(
  map: Record<string, string>,
  key: T | string | null | undefined,
  fallback: string,
): string {
  if (typeof key !== "string") return fallback
  return map[key] ?? map[key.toLowerCase()] ?? fallback
}

/** Coerce ``v`` into one of ``allowed`` (case-sensitive). Anything else
 *  (wrong type, unknown enum, trailing whitespace, etc.) collapses to
 *  ``fallback``. Mirror of the backend ``_safe_enum`` contract. */
export function safeEnum<T extends string>(
  v: unknown,
  allowed: readonly T[],
  fallback: T,
): T {
  if (typeof v !== "string") return fallback
  const trimmed = v.trim()
  return (allowed as readonly string[]).includes(trimmed) ? (trimmed as T) : fallback
}

/** Coerce ``v`` into a strict boolean. Strings ``"true"`` / ``"false"``
 *  (case-insensitive, trimmed) decode; everything non-boolean else
 *  becomes ``fallback`` (default ``false``). */
export function safeBool(v: unknown, fallback = false): boolean {
  if (typeof v === "boolean") return v
  if (typeof v === "string") {
    const t = v.trim().toLowerCase()
    if (t === "true") return true
    if (t === "false") return false
  }
  return fallback
}

/* ------------------------------------------------------------------ */
/* Per-tab client-side normalize                                      */
/* ------------------------------------------------------------------ */

/** Tab keys that have a structured card. Anything outside this set
 *  passes through ``normalizeCardForClient`` unchanged (we only know
 *  how to reshape the eight tabs we own). */
const STRUCT_TAB_KEYS = [
  "summary", "Market", "Sentiment", "News",
  "Fundamentals", "Investment Debate", "Risk Assessment", "Decision",
] as const
export type StructTabKey = typeof STRUCT_TAB_KEYS[number]

function keepRecordItems(arr: unknown): Record<string, unknown>[] {
  return safeArray<unknown>(arr).filter(isRecord) as Record<string, unknown>[]
}

/**
 * Mirror of ``stock_trading_system/web/app.py::_normalize_card`` — the
 * defense-in-depth layer. The backend normaliser is the primary fix;
 * this exists so production rows that predate the backend fix (or any
 * future backend regression) still render a usable card.
 *
 * Contract:
 *   * Returns ``null`` when ``card`` isn't a record (drop the whole
 *     card; the markdown body still renders below it).
 *   * For each known tab, coerces array fields to ``[]``, drops non-
 *     record array items, normalises non-finite numbers to ``null``.
 *   * Unknown tab keys pass through after ``safeRecord``.
 */
export function normalizeCardForClient(
  tabKey: string, card: unknown,
): Record<string, unknown> | null {
  const rec = safeRecord(card)
  if (!rec) return null
  const out: Record<string, unknown> = { ...rec }

  switch (tabKey) {
    case "summary": {
      out.key_metrics = keepRecordItems(out.key_metrics)
      out.decision_drivers = keepRecordItems(out.decision_drivers)
      out.debate_synthesis = safeRecord(out.debate_synthesis)
      // Stance sub-records: if any is non-record, drop it. The card
      // tolerates each stance being null individually.
      if (isRecord(out.debate_synthesis)) {
        const synth = out.debate_synthesis as Record<string, unknown>
        synth.aggressive = safeRecord(synth.aggressive)
        synth.conservative = safeRecord(synth.conservative)
        synth.neutral = safeRecord(synth.neutral)
      }
      break
    }
    case "Market": {
      out.indicators = keepRecordItems(out.indicators)
      out.support_resistance = keepRecordItems(out.support_resistance)
        .map(lvl => ({ ...lvl, price: toFiniteNumber(lvl.price) }))
      out.patterns = safeArray<unknown>(out.patterns)
        .filter((p): p is string => typeof p === "string" && p.trim().length > 0)
      break
    }
    case "Sentiment": {
      out.drivers = keepRecordItems(out.drivers)
      out.mood_score = toFiniteNumber(out.mood_score) ?? 0
      out.contrarian_signal = safeBool(out.contrarian_signal)
      break
    }
    case "News": {
      out.headlines = keepRecordItems(out.headlines)
      out.catalysts = keepRecordItems(out.catalysts)
      break
    }
    case "Fundamentals": {
      for (const k of ["valuation", "growth", "profitability", "balance_sheet"] as const) {
        out[k] = safeRecord(out[k])
      }
      out.quality_score = toFiniteNumber(out.quality_score)
      break
    }
    case "Investment Debate": {
      out.bull_arguments = keepRecordItems(out.bull_arguments)
      out.bear_arguments = keepRecordItems(out.bear_arguments)
      break
    }
    case "Risk Assessment": {
      out.aggressive = safeRecord(out.aggressive)
      out.conservative = safeRecord(out.conservative)
      out.neutral = safeRecord(out.neutral)
      out.top_risks = keepRecordItems(out.top_risks)
      break
    }
    case "Decision": {
      out.entry_zone = safeRecord(out.entry_zone)
      out.structural_stop = toFiniteNumber(out.structural_stop)
      out.take_profit_levels = keepRecordItems(out.take_profit_levels)
      out.preconditions = safeArray<unknown>(out.preconditions)
        .filter((p): p is string => typeof p === "string" && p.trim().length > 0)
      out.exit_conditions = safeArray<unknown>(out.exit_conditions)
        .filter((p): p is string => typeof p === "string" && p.trim().length > 0)
      out.alternative_scenarios = keepRecordItems(out.alternative_scenarios)
      break
    }
    default:
      // Unknown tab — pass through with only the record guard.
      break
  }
  return out
}

/** Build a JSON-safe shape descriptor of ``v`` for telemetry. We log
 *  field names + types only, never the values themselves — the v1.21
 *  guidance is "never echo report bodies into console / Sentry."  */
export function describeShape(v: unknown, depth = 2): unknown {
  if (v === null) return "null"
  if (Array.isArray(v)) {
    if (depth <= 0) return `array(${v.length})`
    return {
      __type: "array", length: v.length,
      sample: v.slice(0, 3).map(item => describeShape(item, depth - 1)),
    }
  }
  if (isRecord(v)) {
    if (depth <= 0) return "object"
    const out: Record<string, unknown> = { __type: "object" }
    for (const [k, val] of Object.entries(v)) {
      out[k] = describeShape(val, depth - 1)
    }
    return out
  }
  return typeof v
}
