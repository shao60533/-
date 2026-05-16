/**
 * Driver.js Tour configuration — 6 steps anchored on the dashboard.
 *
 * Spec: docs/design/onboarding.md §4.5 + PRD §3.1 6-step Tour table.
 *
 * Anchors live on existing components (one `id`/`data-*` added per host —
 * see step 11 anchor injection):
 *   #topbar              — MobileTopbar wrapper
 *   #account-hero        — DashboardPage AccountOverviewCard
 *   #holdings-section    — HoldingsSection wrapper
 *   #batch-analyze-card  — BatchAnalyzeHoldingsCard
 *   [data-mobile-tabbar] — Sidebar MobileTabbar
 *   #onboarding-checklist — OnboardingChecklist self-mount
 */
import type { DriveStep } from "driver.js"

export const TOUR_STEPS: readonly DriveStep[] = [
  {
    element: "#topbar",
    popover: {
      title: "顶栏 · 品牌与模型切换",
      description:
        "蓝色 chip 切换 AI 模型（OpenRouter / Qwen / Gemini）+ deep/quick 双挡。",
      side: "bottom",
    },
  },
  {
    element: "#account-hero",
    popover: {
      title: "账户 Hero · 总览与趋势",
      description: "账户总值 + 今日 PnL + 90D sparkline + 三栏 metric。",
      side: "bottom",
    },
  },
  {
    element: "#holdings-section",
    popover: {
      title: "持仓明细 · 决策中枢",
      description:
        "搜索 / 买入 / 5 ↔ 全部 / 每只可看分析、卖出、修正成本、移除。",
      side: "top",
    },
  },
  {
    element: "#batch-analyze-card",
    popover: {
      title: "批量分析持仓",
      description:
        "一键复核所有持仓的最新 AI 观点。跳过 4h 内已分析，逐只顺序执行。",
      side: "top",
    },
  },
  {
    element: "[data-mobile-tabbar]",
    popover: {
      title: "底部导航 · 5 个一级入口",
      description: "首页 / 分析 / 发现 / 纸面 / 更多。",
      side: "top",
    },
  },
  {
    element: "#onboarding-checklist",
    popover: {
      title: "4 项上手任务",
      description:
        "完成 4 项即解锁全部核心功能。完成度持续显示，可随时折叠。",
      side: "top",
    },
  },
] as const
