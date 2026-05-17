import { describe, expect, test } from "vitest"

import {
  groupAnalysisRowsByTicker,
  summarizeSignalDrift,
  type CompletedAnalysisRow,
} from "../groupAnalysisRowsByTicker"

/**
 * analysis-inbox-group-by-ticker v1.0 — pure-function contract.
 *
 * Covers:
 *   - Empty input returns empty groups / drift.
 *   - Mixed tickers (AAPL × 2 + MSFT × 1) collapse to 2 groups, each
 *     newest-first internally, AAPL ahead because its latest row is
 *     newer than MSFT's only row.
 *   - Empty / falsy ticker rows are dropped.
 *   - Drift detection: stable BUY → "BUY"; BUY then HOLD → "BUY → HOLD"
 *     keyed on oldest → newest ordering.
 *   - Case normalisation: lowercase / mixed ticker collapses with
 *     uppercase counterpart.
 */

function row(
  id: number,
  ticker: string,
  signal: string,
  createdAt: string,
): CompletedAnalysisRow {
  return {
    id,
    ticker,
    signal,
    date: createdAt.slice(0, 10),
    created_at: createdAt,
    provider: null,
    model: null,
    depth: "standard",
  }
}

describe("groupAnalysisRowsByTicker", () => {
  test("returns [] for empty input", () => {
    expect(groupAnalysisRowsByTicker([])).toEqual([])
  })

  test("collapses AAPL×2 + MSFT×1 into 2 groups, newest first", () => {
    const rows: CompletedAnalysisRow[] = [
      row(1, "AAPL", "BUY", "2026-05-01 10:00:00"),
      row(2, "MSFT", "HOLD", "2026-05-02 10:00:00"),
      row(3, "AAPL", "HOLD", "2026-05-03 10:00:00"),
    ]
    const groups = groupAnalysisRowsByTicker(rows)
    expect(groups.map(g => g.ticker)).toEqual(["AAPL", "MSFT"])

    const aapl = groups[0]
    expect(aapl.count).toBe(2)
    expect(aapl.rows.map(r => r.id)).toEqual([3, 1]) // newest first
    expect(aapl.latestRow.id).toBe(3)
    expect(aapl.latestCreatedAt).toBe("2026-05-03 10:00:00")

    const msft = groups[1]
    expect(msft.count).toBe(1)
    expect(msft.latestRow.id).toBe(2)
  })

  test("drops rows with empty / null ticker", () => {
    const rows: CompletedAnalysisRow[] = [
      row(1, "", "BUY", "2026-05-01"),
      row(2, "AAPL", "BUY", "2026-05-02"),
    ]
    const groups = groupAnalysisRowsByTicker(rows)
    expect(groups).toHaveLength(1)
    expect(groups[0].ticker).toBe("AAPL")
    expect(groups[0].rows.map(r => r.id)).toEqual([2])
  })

  test("normalises ticker case so 'aapl' collapses with 'AAPL'", () => {
    const rows: CompletedAnalysisRow[] = [
      row(1, "aapl", "BUY", "2026-05-01 10:00:00"),
      row(2, "AAPL", "HOLD", "2026-05-02 10:00:00"),
    ]
    const groups = groupAnalysisRowsByTicker(rows)
    expect(groups).toHaveLength(1)
    expect(groups[0].ticker).toBe("AAPL")
    expect(groups[0].count).toBe(2)
  })
})

describe("summarizeSignalDrift", () => {
  test("empty rows → empty stable drift", () => {
    const d = summarizeSignalDrift([])
    expect(d.kind).toBe("stable")
    expect(d.label).toBe("")
  })

  test("single row → stable with that signal as label", () => {
    const d = summarizeSignalDrift([row(1, "AAPL", "BUY", "2026-05-01")])
    expect(d.kind).toBe("stable")
    expect(d.label).toBe("BUY")
    expect(d.from).toBe("BUY")
    expect(d.to).toBe("BUY")
  })

  test("all rows share signal → stable", () => {
    // Note: caller passes newest-first ordering (matching TickerGroup.rows).
    const rows: CompletedAnalysisRow[] = [
      row(3, "AAPL", "buy", "2026-05-03"),
      row(2, "AAPL", "BUY", "2026-05-02"),
      row(1, "AAPL", "bullish", "2026-05-01"),
    ]
    const d = summarizeSignalDrift(rows)
    expect(d.kind).toBe("stable")
    expect(d.label).toBe("BUY")
  })

  test("oldest BUY → newest HOLD reports drift 'BUY → HOLD'", () => {
    // Newest-first input ordering: index 0 = most recent.
    const rows: CompletedAnalysisRow[] = [
      row(3, "AAPL", "HOLD", "2026-05-03"),
      row(2, "AAPL", "HOLD", "2026-05-02"),
      row(1, "AAPL", "BUY",  "2026-05-01"),
    ]
    const d = summarizeSignalDrift(rows)
    expect(d.kind).toBe("drift")
    expect(d.label).toBe("BUY → HOLD")
    expect(d.from).toBe("BUY")
    expect(d.to).toBe("HOLD")
  })
})
