import { useState } from "react"
import {
  LayoutDashboard, Brain, Crosshair,
  Wallet, FlaskConical, TestTube, Bell,
  FileText, Settings, ListChecks, MoreHorizontal,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getCurrentUser } from "@/lib/auth"
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from "@/components/ui/sheet"
import { LLMSwitcher } from "./LLMSwitcher"

interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
}

interface NavGroup {
  title: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: "概览",
    items: [
      { label: "仪表盘", href: "/", icon: <LayoutDashboard className="w-4 h-4" /> },
    ],
  },
  {
    title: "分析",
    items: [
      // v1.22: ``/analysis`` is the unified inbox — running tasks and
      // completed analyses live in one list, so the standalone
      // ``/history`` link was retired (route still 301-redirects to
      // ``/analysis`` so old bookmarks keep resolving).
      { label: "AI 分析",  href: "/analysis", icon: <Brain className="w-4 h-4" /> },
      { label: "报告中心", href: "/reports",   icon: <FileText className="w-4 h-4" /> },
    ],
  },
  {
    title: "选股",
    items: [
      { label: "智能选股 V3", href: "/screener-v3", icon: <Crosshair className="w-4 h-4" /> },
      { label: "策略回测",   href: "/backtest", icon: <FlaskConical className="w-4 h-4" /> },
    ],
  },
  {
    title: "持仓",
    items: [
      { label: "持仓管理", href: "/portfolio", icon: <Wallet className="w-4 h-4" /> },
      { label: "预警中心", href: "/alerts",    icon: <Bell className="w-4 h-4" /> },
    ],
  },
  {
    title: "纸面交易",
    items: [
      { label: "全部会话", href: "/paper-trade", icon: <TestTube className="w-4 h-4" /> },
    ],
  },
  {
    title: "系统",
    items: [
      { label: "任务中心", href: "/tasks",    icon: <ListChecks className="w-4 h-4" /> },
      { label: "设置",     href: "/settings", icon: <Settings className="w-4 h-4" /> },
    ],
  },
]

function isActive(href: string): boolean {
  const p = window.location.pathname
  if (href === "/") return p === "/" || p === "/dashboard"
  return p.startsWith(href)
}

export function Sidebar() {
  const user = getCurrentUser()

  return (
    <aside className="hidden md:flex flex-col w-56 min-h-screen bg-card border-r border-border">
      {/* Logo + LLM Switcher */}
      <div className="p-4 border-b border-border space-y-2">
        <a href="/" className="text-sm font-bold text-primary flex items-center gap-2">
          ⚡ StockAI Terminal
        </a>
        <LLMSwitcher />
      </div>

      {/* Nav groups */}
      <nav className="flex-1 p-2 overflow-y-auto">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-1">
            <div className="px-2 py-1.5 mt-2 first:mt-0 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
              {group.title}
            </div>
            {group.items.map((item) => (
              <SidebarLink key={item.href} item={item} active={isActive(item.href)} />
            ))}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-border text-xs text-muted-foreground">
        {user && <span>{user.displayName}</span>}
      </div>
    </aside>
  )
}

function SidebarLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <a
      href={item.href}
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors relative",
        active
          ? "bg-primary/10 text-primary font-medium"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
      )}
    >
      {active && (
        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-4 rounded-r bg-[var(--color-accent-blue)]" />
      )}
      {item.icon}
      <span className="flex-1">{item.label}</span>
    </a>
  )
}

/* ── Mobile bottom tabbar ─────────────────────────────────── */

const MOBILE_PRIMARY: NavItem[] = [
  { label: "仪表盘", href: "/",             icon: <LayoutDashboard className="w-5 h-5" /> },
  { label: "分析",   href: "/analysis",     icon: <Brain className="w-5 h-5" /> },
  { label: "选股",   href: "/screener-v3",  icon: <Crosshair className="w-5 h-5" /> },
  { label: "持仓",   href: "/portfolio",    icon: <Wallet className="w-5 h-5" /> },
]

const MOBILE_MORE: NavItem[] = [
  // v1.22: 分析记录 merged into ``/analysis`` inbox. See note above.
  { label: "报告中心", href: "/reports",      icon: <FileText className="w-5 h-5" /> },
  { label: "策略回测", href: "/backtest",  icon: <FlaskConical className="w-5 h-5" /> },
  { label: "纸面交易", href: "/paper-trade",  icon: <TestTube className="w-5 h-5" /> },
  { label: "预警中心", href: "/alerts",       icon: <Bell className="w-5 h-5" /> },
  { label: "任务中心", href: "/tasks",        icon: <ListChecks className="w-5 h-5" /> },
  { label: "设置",     href: "/settings",     icon: <Settings className="w-5 h-5" /> },
]

export function MobileTabbar() {
  const [moreOpen, setMoreOpen] = useState(false)

  return (
    <>
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 bg-card border-t border-border flex z-50"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        {MOBILE_PRIMARY.map((tab) => (
          <TabItem key={tab.href} item={tab} />
        ))}
        {/* More button */}
        <button
          onClick={() => setMoreOpen(true)}
          className={cn(
            "flex-1 flex flex-col items-center py-2 text-[10px]",
            moreOpen ? "text-primary" : "text-muted-foreground",
          )}
        >
          <MoreHorizontal className="w-5 h-5" />
          <span className="mt-0.5">更多</span>
        </button>
      </nav>

      {/* More sheet */}
      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="bottom" className="pb-8">
          <SheetHeader>
            <SheetTitle>更多功能</SheetTitle>
            <SheetDescription>快速导航到其他页面</SheetDescription>
          </SheetHeader>
          <div className="mb-3 border-b border-border pb-3">
            <LLMSwitcher />
          </div>
          {/* v1.6 mobile fix: 4-col grid on 320px squashes long Chinese
              labels (e.g. "纸面交易记录") into 2-line wraps that touch
              the next cell. Drop to 3-col under sm + truncate per cell
              so labels stay one line; tooltips via ``title`` keep the
              full text accessible. ``min-w-0`` on both icon wrapper
              and label prevents flex overflow inside the cell. */}
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3 mt-2">
            {MOBILE_MORE.map((item) => (
              <a
                key={item.href}
                href={item.href}
                title={item.label}
                className="flex flex-col items-center gap-1.5 p-3 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground min-w-0"
              >
                <span className="min-w-0 shrink-0">{item.icon}</span>
                <span className="text-[11px] truncate max-w-full text-center">
                  {item.label}
                </span>
              </a>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  )
}

function TabItem({ item }: { item: NavItem }) {
  const active = isActive(item.href)
  return (
    <a
      href={item.href}
      className={cn(
        "flex-1 flex flex-col items-center py-2 text-[10px]",
        active ? "text-primary" : "text-muted-foreground",
      )}
    >
      {item.icon}
      <span className="mt-0.5">{item.label}</span>
    </a>
  )
}
