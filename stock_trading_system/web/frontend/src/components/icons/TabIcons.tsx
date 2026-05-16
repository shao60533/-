import type { SVGProps } from "react"

type TabIconProps = SVGProps<SVGSVGElement>

const BASE_PROPS = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": "true" as const,
}

/** 首页 — 4 cell portfolio grid + sparkline accent. */
export function TabIconDashboard(props: TabIconProps) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <rect x="3"  y="3"  width="8" height="8" rx="1.4" />
      <rect x="13" y="3"  width="8" height="8" rx="1.4" />
      <rect x="3"  y="13" width="8" height="8" rx="1.4" />
      <rect x="13" y="13" width="8" height="8" rx="1.4" />
      <polyline points="14.5,19 16,17 17.5,18 19.5,15.5" />
    </svg>
  )
}

/** 分析 — 中心 K 线 + 4 probe 节点环绕 (14 大师 / 多 agent 围绕单股). */
export function TabIconAnalysis(props: TabIconProps) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <line x1="12" y1="6"    x2="12" y2="8.5"  />
      <rect x="10" y="8.5"    width="4" height="7" rx="0.6" />
      <line x1="12" y1="15.5" x2="12" y2="18"   />
      <circle cx="4.5"  cy="6"  r="1.2" />
      <circle cx="19.5" cy="6"  r="1.2" />
      <circle cx="4.5"  cy="18" r="1.2" />
      <circle cx="19.5" cy="18" r="1.2" />
      <line x1="10" y1="9.5"  x2="5.5"  y2="6.6"  />
      <line x1="14" y1="9.5"  x2="18.5" y2="6.6"  />
      <line x1="10" y1="14.5" x2="5.5"  y2="17.4" />
      <line x1="14" y1="14.5" x2="18.5" y2="17.4" />
    </svg>
  )
}

/** 发现 — 漏斗 + 3 候选点 + stem 内 1 top pick. */
export function TabIconDiscover(props: TabIconProps) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <line x1="3" y1="5" x2="21" y2="5" />
      <path d="M 3 5 L 10 13 L 10 19" />
      <path d="M 21 5 L 14 13 L 14 19" />
      <line x1="10" y1="19" x2="14" y2="19" />
      <circle cx="12" cy="16" r="1.3" fill="currentColor" />
      <circle cx="7"  cy="9"  r="0.9" fill="currentColor" />
      <circle cx="12" cy="8"  r="0.9" fill="currentColor" />
      <circle cx="17" cy="9"  r="0.9" fill="currentColor" />
    </svg>
  )
}

/** 纸面 — 纸张 + dog-ear 折角 + 内部双 K 线. */
export function TabIconPaper(props: TabIconProps) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <path d="M 5 3 L 16 3 L 20 7 L 20 21 L 5 21 Z" />
      <path d="M 16 3 L 16 7 L 20 7" />
      <line x1="10" y1="11"   x2="10" y2="12.5" />
      <rect x="9"  y="12.5"   width="2" height="4" rx="0.3" />
      <line x1="10" y1="16.5" x2="10" y2="17.5" />
      <line x1="14" y1="11.5" x2="14" y2="13"   />
      <rect x="13" y="13"     width="2" height="3" rx="0.3" />
      <line x1="14" y1="16"   x2="14" y2="17.5" />
    </svg>
  )
}

/** 更多 — 3×3 dot 矩阵 + center accent (应用抽屉语义). */
export function TabIconMore(props: TabIconProps) {
  return (
    <svg {...BASE_PROPS} {...props}>
      <circle cx="6"  cy="7"  r="1.6" />
      <circle cx="12" cy="7"  r="1.6" />
      <circle cx="18" cy="7"  r="1.6" />
      <circle cx="6"  cy="14" r="1.6" />
      <circle cx="12" cy="14" r="1.6" />
      <circle cx="18" cy="14" r="1.6" />
      <circle cx="6"  cy="20" r="1.6" />
      <circle cx="12" cy="20" r="1.6" fill="currentColor" />
      <circle cx="18" cy="20" r="1.6" />
    </svg>
  )
}
