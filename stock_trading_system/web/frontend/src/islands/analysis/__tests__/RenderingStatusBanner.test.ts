import { describe, expect, test } from "vitest"

import { decideBannerReason, getRenderingMeta } from "../AnalysisPage"

/**
 * analysis-overview-fallback v1.0 — banner decision tree.
 *
 * The legacy banner skipped every ``partial`` row; that's why a
 * partial-with-summary-fallback row (the common case after a
 * provider-side rate limit on Overview) showed nothing and users
 * couldn't tell whether the 概览 they were reading came from the LLM
 * or the deterministic fallback. ``decideBannerReason`` is the pure
 * decision the banner consumes; testing it head-on is far cheaper
 * than mounting <AnalysisPage>.
 */

describe("decideBannerReason — analysis-overview-fallback v1.0", () => {
  test("success: no banner regardless of meta", () => {
    expect(
      decideBannerReason({
        rendering_status: "success",
        rendering: { _meta: { summary_source: "llm", failed_tabs: [] } } as any,
      }),
    ).toBeNull()
  })

  test("partial with no summary gap: still silent (legacy behaviour)", () => {
    expect(
      decideBannerReason({
        rendering_status: "partial",
        rendering: {
          _meta: {
            summary_source: "llm",
            failed_tabs: ["Risk Assessment"],
          },
        } as any,
      }),
    ).toBeNull()
  })

  test("partial with summary_source=fallback → 'summary_fallback' chip", () => {
    expect(
      decideBannerReason({
        rendering_status: "partial",
        rendering: {
          _meta: {
            summary_source: "fallback",
            failed_tabs: [],
          },
        } as any,
      }),
    ).toBe("summary_fallback")
  })

  test("partial with failed_tabs containing 'summary' → 'summary_missing' retry CTA", () => {
    expect(
      decideBannerReason({
        rendering_status: "partial",
        rendering: {
          _meta: {
            summary_source: undefined,
            failed_tabs: ["summary", "Risk Assessment"],
          },
        } as any,
      }),
    ).toBe("summary_missing")
  })

  test("failed status: always 'failed' banner regardless of meta", () => {
    expect(
      decideBannerReason({
        rendering_status: "failed",
        rendering: null,
      }),
    ).toBe("failed")
  })

  test("empty status: 'empty' banner", () => {
    expect(
      decideBannerReason({
        rendering_status: "empty",
        rendering: null,
      }),
    ).toBe("empty")
  })

  test("pending status: 'pending' banner", () => {
    expect(
      decideBannerReason({
        rendering_status: "pending",
        rendering: null,
      }),
    ).toBe("pending")
  })

  test("legacy row without _meta: behaviour matches plain status", () => {
    expect(
      decideBannerReason({
        rendering_status: "partial",
        rendering: { summary: { rating: "Hold" } } as any,
      }),
    ).toBeNull()
    expect(
      decideBannerReason({
        rendering_status: "failed",
        rendering: { summary: { rating: "Hold" } } as any,
      }),
    ).toBe("failed")
  })
})

describe("getRenderingMeta — tolerant accessor", () => {
  test("legacy row (no rendering) returns empty object", () => {
    expect(getRenderingMeta({ rendering: null } as any)).toEqual({})
  })
  test("legacy row (no _meta) returns empty object", () => {
    expect(
      getRenderingMeta({ rendering: { summary: {} } } as any),
    ).toEqual({})
  })
  test("v1.0 row exposes summary_source / failed_tabs / errors", () => {
    expect(
      getRenderingMeta({
        rendering: {
          _meta: {
            summary_source: "fallback",
            failed_tabs: ["News"],
            errors: { summary: "RateLimitError" },
          },
        },
      } as any),
    ).toEqual({
      summary_source: "fallback",
      failed_tabs: ["News"],
      errors: { summary: "RateLimitError" },
    })
  })
})
