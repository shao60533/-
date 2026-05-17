/**
 * analysis-inbox-group-by-ticker v1.0 — pure helpers.
 *
 * The "按个股" view of the analysis Inbox collapses every completed
 * analysis row by ticker. This module owns the two pure transforms
 * the view depends on:
 *
 *   groupAnalysisRowsByTicker — produce one TickerGroup per ticker,
 *                               newest-first within and across groups.
 *   summarizeSignalDrift      — short label describing whether the
 *                               ticker's signal moved across recorded
 *                               analyses (e.g. "BUY → HOLD") or held
 *                               steady ("BUY").
 *
 * Kept side-effect-free so the view can re-render cheaply and the
 * vitest suite can pin behaviour without bootstrapping React.
 */

import { signalLabel } from "./AnalysisPage"

/** Subset of an /api/history row used by the group view. Mirrors the
 *  ``kind: "analysis"`` arm of ``InboxRow`` in AnalysisPage.tsx but
 *  imports nothing from React so the helpers stay vitest-friendly. */
export interface CompletedAnalysisRow {
  id: number
  ticker: string
  signal: string
  date: string
  created_at: string
  provider: string | null
  model: string | null
  depth: "quick" | "standard" | "deep" | null
}

export interface TickerGroup {
  ticker: string
  rows: CompletedAnalysisRow[]
  latestRow: CompletedAnalysisRow
  latestCreatedAt: string
  count: number
}

export interface SignalDrift {
  kind: "stable" | "drift"
  /** Pre-rendered short label, e.g. "BUY → HOLD" / "BUY". Empty when
   *  the row list is empty. */
  label: string
  /** First → last canonical signal labels (newest at index 0,
   *  matching the row sort order). Useful for tests that want to
   *  assert beyond the formatted string. */
  from: string
  to: string
}

const EMPTY_DRIFT: SignalDrift = { kind: "stable", label: "", from: "", to: "" }

function compareCreatedAtDesc(a: CompletedAnalysisRow, b: CompletedAnalysisRow): number {
  return (b.created_at || "").localeCompare(a.created_at || "")
}

/**
 * Bucket the inbox's completed-analysis rows by ``ticker``.
 *
 *   * Tickers are uppercased; empty / falsy tickers are dropped.
 *   * Each group's ``rows`` is sorted newest-first by ``created_at``.
 *   * Groups themselves are sorted newest-first by the latest row in
 *     each group, so the most-recently-analysed ticker floats to the
 *     top regardless of how many historical records it accumulated.
 */
export function groupAnalysisRowsByTicker(
  rows: readonly CompletedAnalysisRow[],
): TickerGroup[] {
  if (rows.length === 0) return []

  const buckets = new Map<string, CompletedAnalysisRow[]>()
  for (const r of rows) {
    const t = (r.ticker || "").toUpperCase()
    if (!t) continue
    const list = buckets.get(t)
    if (list === undefined) {
      buckets.set(t, [r])
    } else {
      list.push(r)
    }
  }

  const groups: TickerGroup[] = []
  for (const [ticker, arr] of buckets.entries()) {
    const sorted = [...arr].sort(compareCreatedAtDesc)
    groups.push({
      ticker,
      rows: sorted,
      latestRow: sorted[0],
      latestCreatedAt: sorted[0].created_at || "",
      count: sorted.length,
    })
  }

  groups.sort((a, b) => b.latestCreatedAt.localeCompare(a.latestCreatedAt))
  return groups
}

/**
 * Compare the oldest vs. newest canonicalised signal for a group.
 *
 *   * Single-row group → ``kind: "stable"``, label = that one signal
 *     (e.g. ``"BUY"``).
 *   * All rows share the same canonical signal → ``kind: "stable"``.
 *   * Otherwise → ``kind: "drift"``, label like ``"BUY → HOLD"`` using
 *     the OLDEST row as the source and the NEWEST as the target.
 *
 * The function trusts the row order it was passed; callers that pull
 * from ``TickerGroup.rows`` get newest-first ordering, so we read the
 * last element for the oldest record and the first for the newest.
 */
export function summarizeSignalDrift(
  rows: readonly CompletedAnalysisRow[],
): SignalDrift {
  if (rows.length === 0) return EMPTY_DRIFT
  const newest = signalLabel(rows[0].signal).toUpperCase()
  if (rows.length === 1) {
    return { kind: "stable", label: newest, from: newest, to: newest }
  }
  const oldest = signalLabel(rows[rows.length - 1].signal).toUpperCase()
  if (oldest === newest) {
    return { kind: "stable", label: newest, from: oldest, to: newest }
  }
  return {
    kind: "drift",
    label: `${oldest} → ${newest}`,
    from: oldest,
    to: newest,
  }
}
