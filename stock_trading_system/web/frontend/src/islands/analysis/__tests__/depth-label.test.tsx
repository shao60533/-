/**
 * analysis-depth-mode v1.0 — ``depthLabel`` 二元收敛 + 旧值兼容回归。
 *
 * 现状：v1.16 ``depthLabel`` 把 quick/standard/deep 三档分别映射为
 * 「快速 / 标准 / 深度」。v1.0 把 quick 移出产品入口，新字段
 * ``deep_analysis: bool`` 优先级最高，旧 ``depth`` 字段仍兼容（含旧值
 * ``quick`` → 显示「标准」）。任何输入都不应再返回「快速」。
 */

import { describe, it, expect } from "vitest"
import { depthLabel } from "../AnalysisPage"

describe("depthLabel v1.0 — 二元收敛", () => {
  // ── deep_analysis (bool) 优先级 ─────────────────────────────
  it("deep_analysis=true → 深度（即使 depth=standard）", () => {
    expect(depthLabel("standard", true)).toBe("深度")
  })

  it("deep_analysis=false → 标准（即使 depth=deep）", () => {
    expect(depthLabel("deep", false)).toBe("标准")
  })

  // ── 缺新字段时 fallback 旧 depth ──────────────────────────
  it.each([
    ["deep",     "深度"],
    ["DEEP",     "深度"],
    ["standard", "标准"],
    ["STANDARD", "标准"],
    ["quick",    "标准"],   // 旧值兼容映射
    ["QUICK",    "标准"],
    ["",         "标准"],   // 空字符串
    ["unknown",  "标准"],   // 未知值兜底
  ])("depth=%s → %s（无 deep_analysis）", (raw, expected) => {
    expect(depthLabel(raw)).toBe(expected)
  })

  // ── 完全缺字段：默认标准 ──────────────────────────────────
  it("null/undefined 全缺 → 标准", () => {
    expect(depthLabel(null)).toBe("标准")
    expect(depthLabel(undefined)).toBe("标准")
    expect(depthLabel(null, null)).toBe("标准")
    expect(depthLabel(undefined, undefined)).toBe("标准")
  })

  // ── v1.0 关键不变量：永远不返回「快速」 ───────────────────
  it.each([
    [null, null],
    [undefined, undefined],
    ["quick", null],
    ["quick", undefined],
    ["QUICK", false],     // deep_analysis=false 优先
    ["unknown-junk", null],
    ["", null],
  ])("depth=%s deep_analysis=%s → 不返回 快速", (raw, flag) => {
    const label = depthLabel(
      raw as string | null | undefined,
      flag as boolean | null | undefined,
    )
    expect(label).not.toBe("快速")
    // 收敛集合：只可能是 标准 / 深度
    expect(["标准", "深度"]).toContain(label)
  })
})
