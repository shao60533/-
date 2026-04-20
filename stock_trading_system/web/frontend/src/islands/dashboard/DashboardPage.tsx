import {
  TrendingUp, Wallet, Target, Bell,
  Sparkles, CheckCircle2, Clock, Activity,
} from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Stat } from "@/components/ui/stat"
import { formatCurrency, formatPct } from "@/lib/utils"

export function DashboardPage() {
  return (
    <div className="space-y-6">
      {/* Row 1: 4 stat cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat
          label="账户总值"
          value={formatCurrency(100176.62)}
          delta={1.41}
          hint="较昨日"
          icon={<Wallet className="h-4 w-4" />}
        />
        <Stat
          label="今日盈亏"
          value={formatCurrency(1417.22)}
          delta={1.41}
          hint="持仓 2 天"
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <Stat
          label="胜率"
          value="68.4%"
          delta={2.1}
          hint="近 30 天"
          icon={<Target className="h-4 w-4" />}
        />
        <Stat
          label="活跃预警"
          value="12"
          hint="3 触发 · 9 待触发"
          icon={<Bell className="h-4 w-4" />}
        />
      </div>

      {/* Row 2: main + side */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* 主区：今日市场洞察 */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-[var(--color-accent-blue)]" />
                <CardTitle>今日 AI 洞察</CardTitle>
              </div>
              <Badge variant="blue">实时流</Badge>
            </div>
            <CardDescription>由 14 位大师 Agent 综合评估产出</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[
                { ticker: "NVDA", signal: "buy", score: 88, gurus: "Buffett · Munger · Wood · Druckenmiller", reason: "AI 基础设施周期，护城河与成长共振" },
                { ticker: "AAPL", signal: "hold", score: 62, gurus: "Buffett · Graham · Ackman", reason: "估值偏高，等待回调后再加仓" },
                { ticker: "XIACY", signal: "sell", score: 34, gurus: "Burry · Taleb · Marks", reason: "右侧防御，营业利润率未见改善" },
              ].map(item => (
                <div
                  key={item.ticker}
                  className="flex items-center gap-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-4 py-3 hover:border-[var(--color-border-bright)] transition-colors cursor-pointer"
                >
                  <div className="font-mono text-sm font-semibold w-14">{item.ticker}</div>
                  <Badge variant={item.signal as "buy"|"sell"|"hold"} className="uppercase">
                    {item.signal}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-medium truncate">{item.reason}</div>
                    </div>
                    <div className="text-[11px] text-[var(--color-text-muted)] mt-0.5 truncate">
                      {item.gurus}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="font-mono text-lg font-semibold tabular-nums">{item.score}</div>
                    <div className="text-[10px] text-[var(--color-text-muted)]">综合分</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
              <span>更新于 2 分钟前</span>
              <Button variant="ghost" size="sm">查看全部洞察 →</Button>
            </div>
          </CardContent>
        </Card>

        {/* 右侧：实时进度 + 持仓概览 */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-[var(--color-accent-green)]" />
                <CardTitle>运行中任务</CardTitle>
              </div>
              <CardDescription>实时进度流</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <TaskProgressRow
                title="选股 V3 · 14 大师"
                progress={64}
                stage="fundamentals_agent"
                eta="1.5 min"
              />
              <TaskProgressRow
                title="批量分析持仓 · 8 只"
                progress={38}
                stage="NVDA 分析中"
                eta="3 min"
              />
              <TaskProgressRow
                title="回测 · Graham 策略"
                progress={92}
                stage="生成权益曲线"
                eta="10s"
                tone="success"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>持仓概览</CardTitle>
              <CardDescription>6 只股票 · 总值 $12,676</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {[
                  { t: "NVDA", q: "62.86 股", p: 2.4 },
                  { t: "AAPL", q: "30 股", p: -0.8 },
                  { t: "MSFT", q: "15 股", p: 1.2 },
                ].map(p => (
                  <div key={p.t} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="h-3.5 w-3.5 text-[var(--color-accent-green)]" />
                      <span className="font-mono font-medium">{p.t}</span>
                      <span className="text-[11px] text-[var(--color-text-muted)]">{p.q}</span>
                    </div>
                    <span
                      className={
                        p.p >= 0
                          ? "font-mono text-[var(--color-accent-green)] tabular-nums"
                          : "font-mono text-[var(--color-accent-red)] tabular-nums"
                      }
                    >
                      {formatPct(p.p)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function TaskProgressRow(props: {
  title: string
  progress: number
  stage: string
  eta: string
  tone?: "default" | "success"
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium truncate">{props.title}</div>
        <div className="font-mono text-[11px] text-[var(--color-text-secondary)] tabular-nums shrink-0">
          {props.progress}%
        </div>
      </div>
      <Progress value={props.progress} tone={props.tone} />
      <div className="flex items-center justify-between text-[10px] text-[var(--color-text-muted)]">
        <span className="truncate">{props.stage}</span>
        <span className="flex items-center gap-1">
          <Clock className="h-2.5 w-2.5" />
          {props.eta}
        </span>
      </div>
    </div>
  )
}
