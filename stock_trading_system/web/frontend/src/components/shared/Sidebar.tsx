import {
  LayoutDashboard, Brain, ClockArrowDown, Crosshair,
  Wallet, FlaskConical, TestTube, Bell,
  FileText, Settings, ListChecks, ExternalLink,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getCurrentUser } from "@/lib/auth"

interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
  legacy?: boolean // true = un-migrated, goes to /app#xxx
}

const NAV_ITEMS: NavItem[] = [
  // Migrated → React URLs
  { label: "仪表盘",   href: "/",             icon: <LayoutDashboard className="w-4 h-4" /> },
  { label: "智能选股",  href: "/screener-v3",   icon: <Crosshair className="w-4 h-4" /> },
  { label: "任务中心",  href: "/tasks",          icon: <ListChecks className="w-4 h-4" /> },

  // Un-migrated → legacy SPA with hash
  { label: "AI 分析",   href: "/app#analysis",   icon: <Brain className="w-4 h-4" />,           legacy: true },
  { label: "分析记录",  href: "/app#history",     icon: <ClockArrowDown className="w-4 h-4" />,   legacy: true },
  { label: "持仓管理",  href: "/app#portfolio",   icon: <Wallet className="w-4 h-4" />,           legacy: true },
  { label: "策略回测",  href: "/app#backtest",    icon: <FlaskConical className="w-4 h-4" />,     legacy: true },
  { label: "纸面交易",  href: "/app#paper",       icon: <TestTube className="w-4 h-4" />,         legacy: true },
  { label: "预警中心",  href: "/app#alerts",      icon: <Bell className="w-4 h-4" />,             legacy: true },
  { label: "报告中心",  href: "/app#reports",     icon: <FileText className="w-4 h-4" />,         legacy: true },
  { label: "设置",      href: "/app#settings",    icon: <Settings className="w-4 h-4" />,         legacy: true },
]

export function Sidebar() {
  const user = getCurrentUser()
  const currentPath = window.location.pathname

  const isActive = (href: string) => {
    if (href === "/") return currentPath === "/" || currentPath === "/dashboard"
    return currentPath.startsWith(href.split("#")[0]) && href.split("#")[0] !== "/app"
  }

  return (
    <aside className="hidden md:flex flex-col w-56 min-h-screen bg-card border-r border-border">
      {/* Logo */}
      <div className="p-4 border-b border-border">
        <a href="/" className="text-sm font-bold text-primary flex items-center gap-2">
          ⚡ StockAI Terminal
        </a>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
        <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
          Overview
        </div>
        {NAV_ITEMS.slice(0, 3).map(item => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}

        <div className="px-2 py-1.5 mt-3 text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
          经典版功能
        </div>
        {NAV_ITEMS.slice(3).map(item => (
          <NavLink key={item.href} item={item} active={isActive(item.href)} />
        ))}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-border text-xs text-muted-foreground">
        {user && <span>{user.displayName}</span>}
      </div>
    </aside>
  )
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  return (
    <a
      href={item.href}
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors",
        active
          ? "bg-primary/10 text-primary font-medium"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/50",
      )}
    >
      {item.icon}
      <span className="flex-1">{item.label}</span>
      {item.legacy && <ExternalLink className="w-3 h-3 opacity-40" />}
    </a>
  )
}

/** Mobile bottom tabbar */
export function MobileTabbar() {
  const currentPath = window.location.pathname
  const tabs = [
    { label: "仪表盘", href: "/",             icon: <LayoutDashboard className="w-5 h-5" /> },
    { label: "分析",   href: "/app#analysis",  icon: <Brain className="w-5 h-5" /> },
    { label: "选股",   href: "/screener-v3",   icon: <Crosshair className="w-5 h-5" /> },
    { label: "持仓",   href: "/app#portfolio",  icon: <Wallet className="w-5 h-5" /> },
    { label: "任务",   href: "/tasks",          icon: <ListChecks className="w-5 h-5" /> },
  ]

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-card border-t border-border flex z-50"
         style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
      {tabs.map(tab => {
        const active = tab.href === "/" ? currentPath === "/" : currentPath.startsWith(tab.href.split("#")[0]) && tab.href.split("#")[0] !== "/app"
        return (
          <a key={tab.href} href={tab.href}
             className={cn(
               "flex-1 flex flex-col items-center py-2 text-[10px]",
               active ? "text-primary" : "text-muted-foreground",
             )}>
            {tab.icon}
            <span className="mt-0.5">{tab.label}</span>
          </a>
        )
      })}
    </nav>
  )
}
