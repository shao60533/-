import { useState } from "react"
import {
  LayoutDashboard, Brain, Crosshair,
  Wallet, FlaskConical, TestTube, Bell,
  FileText, Settings, ListChecks, MoreHorizontal,
  Receipt, UserCircle,
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
// mobile-ui-v1.3: bottom tabs collapse to 5 — 首页/分析/发现/纸面/更多.
// "持仓" is no longer a primary tab; holdings live on the home page.
// "纸面" is promoted to a primary tab so the analysis -> 纸面追踪 flow
// stays one tap away.

const MOBILE_PRIMARY: NavItem[] = [
  { label: "首页", href: "/",             icon: <LayoutDashboard className="w-5 h-5" /> },
  { label: "分析", href: "/analysis",     icon: <Brain className="w-5 h-5" /> },
  { label: "发现", href: "/screener-v3",  icon: <Crosshair className="w-5 h-5" /> },
  { label: "纸面", href: "/paper-trade",  icon: <TestTube className="w-5 h-5" /> },
]

interface MoreEntry extends NavItem { description?: string }

// mobile-ui-v1.3: More carries low-frequency pages only. No 复盘与运营
// status cards, no 调度器 shortcut, no 纸面交易 (now primary tab).
// 系统设置 副标题 = "模型与通知".
const MOBILE_MORE: MoreEntry[] = [
  { label: "报告中心", description: "日报/周报/月报",       href: "/reports",   icon: <FileText className="w-5 h-5" /> },
  { label: "策略回测", description: "表单 / 任务 / 结果",    href: "/backtest",  icon: <FlaskConical className="w-5 h-5" /> },
  { label: "交易记录", description: "买入 / 卖出流水",       href: "/portfolio", icon: <Receipt className="w-5 h-5" /> },
  { label: "预警中心", description: "模板 / 新建 / 历史",    href: "/alerts",    icon: <Bell className="w-5 h-5" /> },
  { label: "任务中心", description: "筛选 / 详情 / 重试",    href: "/tasks",     icon: <ListChecks className="w-5 h-5" /> },
  { label: "系统设置", description: "模型与通知",           href: "/settings",  icon: <Settings className="w-5 h-5" /> },
  { label: "账号",     description: "当前用户 / 退出登录",    href: "/settings#account", icon: <UserCircle className="w-5 h-5" /> },
]

function isMoreRouteActive(): boolean {
  const p = window.location.pathname
  return MOBILE_MORE.some((m) => {
    const href = m.href.split("#")[0]
    if (!href || href === "/") return false
    return p.startsWith(href)
  })
}

export function MobileTabbar() {
  const [moreOpen, setMoreOpen] = useState(false)
  const moreActive = moreOpen || isMoreRouteActive()

  return (
    <>
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 bg-card border-t border-border flex z-50"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        {MOBILE_PRIMARY.map((tab) => (
          <TabItem key={tab.href} item={tab} />
        ))}
        {/* More button — opens a sheet listing low-frequency pages. */}
        <button
          data-mobile-tab="more"
          onClick={() => setMoreOpen(true)}
          className={cn(
            "flex-1 flex flex-col items-center py-2 text-[10px] min-h-[44px]",
            moreActive ? "text-primary" : "text-muted-foreground",
          )}
        >
          <MoreHorizontal className="w-5 h-5" />
          <span className="mt-0.5 whitespace-nowrap">更多</span>
        </button>
      </nav>

      {/* More sheet — function map for low-frequency pages. */}
      <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
        <SheetContent side="bottom" className="pb-8">
          <SheetHeader>
            <SheetTitle>所有页面</SheetTitle>
            <SheetDescription>功能地图</SheetDescription>
          </SheetHeader>
          <div className="mb-3 border-b border-border pb-3">
            <LLMSwitcher />
          </div>
          <div className="grid grid-cols-1 gap-2 mt-2">
            {MOBILE_MORE.map((item) => (
              <a
                key={item.href}
                href={item.href}
                title={item.label}
                className="flex items-center gap-3 p-3 rounded-lg hover:bg-muted/50 transition-colors text-muted-foreground hover:text-foreground min-w-0 min-h-[44px]"
              >
                <span className="shrink-0">{item.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-foreground truncate">{item.label}</div>
                  {item.description && (
                    <div className="text-[11px] text-muted-foreground truncate">{item.description}</div>
                  )}
                </div>
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
      data-mobile-tab={item.href}
      href={item.href}
      className={cn(
        "flex-1 flex flex-col items-center py-2 text-[10px] min-h-[44px]",
        active ? "text-primary" : "text-muted-foreground",
      )}
    >
      {item.icon}
      <span className="mt-0.5 whitespace-nowrap">{item.label}</span>
    </a>
  )
}
