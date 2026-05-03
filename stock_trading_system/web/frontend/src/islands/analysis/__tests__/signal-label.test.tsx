/**
 * v1.3 — signalLabel tri-state mapping regression.
 *
 * The /analysis list rows and the detail-page Header used to show
 * the raw ``row.signal`` value, which surfaced the LLM's full 7-state
 * rating ladder ("Overweight" / "Strong Sell" / 中文 / mixed case)
 * directly to users. ``signalLabel`` collapses every variant into the
 * canonical {Buy, Sell, Hold} triple so the colored Badge stays
 * readable regardless of which provider/prompt produced the signal.
 *
 * Importantly, this is a TEXT-only normalization — ``signalVariant``
 * still owns the badge color (4 variants) and ``RatingBadge`` inside
 * the Decision banner still carries the 7-state rating ladder. Those
 * stay untouched.
 */

import { describe, it, expect } from "vitest"
import { signalLabel } from "../AnalysisPage"

describe("signalLabel v1.3 tri-state mapping", () => {
  // ── Buy ─────────────────────────────────────────────
  it.each([
    "Buy", "Strong Buy", "Overweight", "BUY",
    "bullish", "加仓", "ADD",
  ])("maps %s → Buy", (raw) => {
    expect(signalLabel(raw)).toBe("Buy")
  })

  // ── Sell ────────────────────────────────────────────
  it.each([
    "Sell", "Strong Sell", "Underweight", "SELL",
    "bearish", "减仓", "REDUCE",
  ])("maps %s → Sell", (raw) => {
    expect(signalLabel(raw)).toBe("Sell")
  })

  // ── Hold (default) ──────────────────────────────────
  it.each([
    "Hold", "HOLD", "Neutral", "neutral",
    "WAIT", "中性",
    "", "   ", "unknown junk",
  ])("maps %s → Hold", (raw) => {
    expect(signalLabel(raw)).toBe("Hold")
  })

  it.each([null, undefined])("handles nullish input", (raw) => {
    expect(signalLabel(raw as null | undefined)).toBe("Hold")
  })
})
