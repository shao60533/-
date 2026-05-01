/**
 * Defensive helpers used across the 8 structured analysis cards.
 *
 * The production /analysis/17 white-screen was caused by a single bad
 * field — ``support_resistance[i].price`` happened to be a string, and
 * the card called ``price.toFixed(2)`` directly. Wrapping every render
 * in an ErrorBoundary is necessary but not sufficient; the cards
 * themselves should never throw on mildly-malformed payloads.
 */

/** Always return an array. ``null`` / ``undefined`` / scalars / objects
 *  all degrade to ``[]`` so map/filter/sort never explode. */
export function safeArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : []
}

/** Format a finite number to ``digits`` decimals; ``"—"`` otherwise.
 *  Tolerates string-encoded numbers from less-strict providers. */
export function fmtNumber(v: unknown, digits = 2): string {
  const n = toFiniteNumber(v)
  return n === null ? "—" : n.toFixed(digits)
}

/** Coerce a value to a finite number or ``null``. Strips trailing
 *  ``%`` and commas so akshare-style ``"15.3%"`` parses cleanly. */
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

/** True iff ``v`` is a non-empty string after trimming. Used so cards
 *  can hide whole sections instead of rendering empty headers. */
export function nonEmptyStr(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0
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
