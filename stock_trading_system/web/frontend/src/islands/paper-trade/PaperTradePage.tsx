import {
  CheckCircle2, Clock4, TrendingUp,
  Sparkles, ExternalLink,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn, formatCurrency } from "@/lib/utils"

interface Tier {
  seq: number
  label: string
  target: number        // percent
  trigger: string
  triggerDetail: string
  status: "executed" | "pending" | "expired"
  executedAt?: string
  executedAt_extra?: string
}

const tiers: Tier[] = [
  { seq: 1, label: "初始建仓", target: 12.5, trigger: "立即", triggerDetail: "初始建仓 12.5%", status: "executed", executedAt: "2026-04-15", executedAt_extra: "@ $198.87" },
  { seq: 2, label: "加仓档", target: 70,   trigger: "突破 $200-$210 后回踩", triggerDetail: "突破并回踩 200.0-210.0 → 加仓至 70%", status: "pending" },
  { seq: 3, label: "硬性止损", target: 0,  trigger: "价格 ≤ $124.57", triggerDetail: "硬性止损：跌破 124.57", status: "pending" },
  { seq: 4, label: "跟踪止盈", target: 0,  trigger: "收盘 < MA200", triggerDetail: "跟踪止盈：收盘跌破 MA200", status: "pending" },
]

export function PaperTradePage() {
  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header strip */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="font-mono text-2xl font-bold tracking-tight">NVDA</div>
          <Badge variant="success" className="gap-1.5">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-pulse-dot rounded-full bg-[var(--color-accent-green)]" />
            </span>
            live
          </Badge>
        </div>
      </div>

      {/* Two-column: strategy overview + holdings */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* 核心论点 + 执行总结 */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-[var(--color-accent-blue)]" />
                <CardTitle>当前策略</CardTitle>
                <Badge variant="blue">BUY</Badge>
              </div>
              <span className="text-[11px] text-[var(--color-text-muted)]">分析 #25 · 04-19 22:26</span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-[var(--color-text-muted)] mb-1.5">
                  执行总结
                </div>
                <p className="text-sm leading-relaxed text-[var(--color-text-primary)]">
                  AI 基础设施周期上行，Blackwell 交付加速释放二阶导；
                  建议右侧介入，突破 $210 回踩加仓至 70%，硬性止损设于 $124.57，
                  跟踪止盈以收盘跌破 MA200 为准。投资周期 3-6 个月。
                </p>
              </div>
              <div className="flex items-center gap-4 text-xs text-[var(--color-text-secondary)]">
                <span className="inline-flex items-center gap-1">
                  <Clock4 className="h-3 w-3" />
                  投资周期 3-6 个月
                </span>
                <span>共 4 档 · 1 已执行 · 3 待触发</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* 持仓状态 */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-[var(--color-accent-green)]" />
              持仓状态
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2.5">
            <div>
              <div className="font-mono text-3xl font-bold tabular-nums leading-none">62.86 <span className="text-sm font-medium text-[var(--color-text-secondary)]">股</span></div>
              <div className="text-xs text-[var(--color-text-secondary)] mt-1">成本 $198.87 · 现价 $201.68</div>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-xl font-semibold text-[var(--color-accent-green)] tabular-nums">+1.41%</span>
              <span className="text-xs text-[var(--color-text-muted)]">浮盈 · 持仓 2 天</span>
            </div>
            <div className="grid grid-cols-2 gap-2 pt-2 border-t border-[var(--color-border)] text-xs">
              <Metric k="市值" v={formatCurrency(12676.62)} />
              <Metric k="现金" v={formatCurrency(87500.00)} />
              <Metric k="总值" v={formatCurrency(100176.62)} />
              <Metric k="再确认" v="× 3" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 计划档位 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>计划档位</CardTitle>
            <Badge variant="muted">已执行 / 待触发</Badge>
          </div>
        </CardHeader>
        <CardContent className="px-0 pb-2">
          {tiers.map((t, i) => (
            <TierRow key={t.seq} tier={t} isLast={i === tiers.length - 1} />
          ))}
        </CardContent>
      </Card>

      {/* AI 最终决策 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-[var(--color-accent-blue)]" />
              <CardTitle>AI 最终决策</CardTitle>
            </div>
            <Button variant="ghost" size="sm" className="gap-1">
              关联分析 #25 · 04-19 22:26
              <ExternalLink className="h-3 w-3" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="prose prose-sm prose-invert max-w-none">
            <p className="text-sm leading-relaxed text-[var(--color-text-primary)]">
              <strong className="text-[var(--color-accent-blue)]">Executive Summary</strong>：针对 <code className="px-1.5 py-0.5 rounded bg-[var(--color-bg-secondary)] text-[var(--color-accent-blue)] font-mono text-[12px]">NVDA</code> 的最终交易方案为坚决执行右侧防御与流动性回收。
              现有持仓须在股价反弹至 <span className="font-mono text-[var(--color-accent-green)]">$201.68</span>（布林带上轨）至 <span className="font-mono">$210</span>（50 日均线）双重阻力区时果断逢高减仓，目标将 NVDA 风险敞口降至 0%。
              重新评估 NVDA 的硬性门槛为右侧共振信号：股价需带量有效突破并连续站稳 <span className="font-mono">$228.24</span> 两百日均线，且下一财报季必须同步验证营业利润率突破 5%、存货周转率实质性改善及汽车业务亏损显著收窄。
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function Metric({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">{k}</div>
      <div className="font-mono tabular-nums text-sm">{v}</div>
    </div>
  )
}

function TierRow({ tier, isLast }: { tier: Tier; isLast: boolean }) {
  const statusConfig = {
    executed: {
      color: "text-[var(--color-accent-green)]",
      bgBar: "bg-[var(--color-accent-green)]",
      badge: (
        <Badge variant="success" className="gap-1 shrink-0">
          <CheckCircle2 className="h-3 w-3" />
          已执行
        </Badge>
      ),
    },
    pending: {
      color: "text-[var(--color-text-secondary)]",
      bgBar: "bg-[var(--color-border-bright)]",
      badge: (
        <Badge variant="blue" className="gap-1 shrink-0">
          <Clock4 className="h-3 w-3" />
          待触发
        </Badge>
      ),
    },
    expired: {
      color: "text-[var(--color-text-muted)]",
      bgBar: "bg-[var(--color-border)]",
      badge: <Badge variant="muted" className="shrink-0">已失效</Badge>,
    },
  }[tier.status]

  return (
    <div
      className={cn(
        "relative px-4 py-3.5 sm:px-5",
        !isLast && "border-b border-[var(--color-border)]",
        tier.status === "pending" && "hover:bg-[var(--color-bg-secondary)] transition-colors"
      )}
    >
      {/* Left rail */}
      <div className={cn("absolute left-0 top-0 bottom-0 w-0.5", statusConfig.bgBar)} />

      {/* ═══ Mobile layout (<768px): 2-row stack ═══ */}
      <div className="md:hidden space-y-2">
        {/* Row 1: seq + label + target + status-badge */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={cn("font-mono text-xs font-semibold shrink-0", statusConfig.color)}>
              #{tier.seq}
            </span>
            <span className={cn("text-sm font-semibold truncate", statusConfig.color)}>
              {tier.label}
            </span>
            <Badge variant="blue" className="font-mono shrink-0">
              {tier.target}%
            </Badge>
          </div>
          {statusConfig.badge}
        </div>

        {/* Row 2: trigger detail (full-width, wrap) */}
        <div className="text-xs leading-relaxed">
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)] shrink-0">
              触发
            </span>
            <span className="font-mono text-[var(--color-accent-blue)] break-all">
              {tier.trigger}
            </span>
          </div>
          <div className="text-[var(--color-text-secondary)] mt-1">
            {tier.triggerDetail}
          </div>
          {tier.executedAt && (
            <div className="text-[10px] text-[var(--color-text-muted)] font-mono mt-1.5">
              {tier.executedAt}{tier.executedAt_extra ? ` · ${tier.executedAt_extra}` : ""}
            </div>
          )}
        </div>
      </div>

      {/* ═══ Desktop layout (≥768px): 12-col grid ═══ */}
      <div className="hidden md:grid md:grid-cols-12 items-center gap-3">
        <div className="col-span-1 flex items-center gap-2">
          <span className={cn("font-mono text-xs font-semibold", statusConfig.color)}>
            #{tier.seq}
          </span>
        </div>
        <div className="col-span-2">
          <div className={cn("text-sm font-semibold", statusConfig.color)}>{tier.label}</div>
        </div>
        <div className="col-span-1">
          <Badge variant="blue" className="font-mono">{tier.target}%</Badge>
        </div>
        <div className="col-span-3">
          <div className="text-[10px] uppercase tracking-wider text-[var(--color-text-muted)]">
            触发条件
          </div>
          <div className="text-xs font-mono text-[var(--color-accent-blue)]">{tier.trigger}</div>
        </div>
        <div className="col-span-3 text-xs text-[var(--color-text-secondary)]">
          {tier.triggerDetail}
        </div>
        <div className="col-span-2 flex items-center justify-end gap-2">
          {statusConfig.badge}
          {tier.executedAt && (
            <div className="text-[10px] text-[var(--color-text-muted)] font-mono text-right hidden lg:block">
              {tier.executedAt}
              {tier.executedAt_extra && <div>{tier.executedAt_extra}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
