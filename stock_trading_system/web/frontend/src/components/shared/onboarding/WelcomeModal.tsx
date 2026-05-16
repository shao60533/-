/**
 * <WelcomeModal> — first-visit welcome with 3 capability cards, dual
 * CTA (skip / start tour) and a yellow-bordered compliance footer.
 *
 * Spec: docs/design/onboarding.md §4.3.
 * Visual contract: demo_onboarding_v1.html `.modal` section.
 *
 * Mobile-only by hard rule (md:hidden). Desktop users see nothing.
 */
import { Button } from "@/components/ui/button"

interface WelcomeModalProps {
  open: boolean
  onSkip: () => void
  onStartTour: () => void
}

interface FeatItemProps {
  n: string
  title: string
  desc: string
}

function FeatItem({ n, title, desc }: FeatItemProps) {
  return (
    <div className="flex gap-2.5 items-start">
      <span className="shrink-0 w-6 h-6 rounded-full bg-primary/15 text-primary text-[11px] font-bold grid place-items-center mt-0.5">
        {n}
      </span>
      <div className="text-[12.5px] leading-relaxed">
        <div className="font-semibold text-foreground">{title}</div>
        <div className="text-muted-foreground">{desc}</div>
      </div>
    </div>
  )
}

export function WelcomeModal({ open, onSkip, onStartTour }: WelcomeModalProps) {
  if (!open) return null
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-welcome-title"
      className="md:hidden fixed inset-0 z-[100] bg-background/72 backdrop-blur-sm grid place-items-center p-4"
    >
      <div className="w-full max-w-[340px] rounded-2xl border border-primary/25 bg-card shadow-2xl p-5">
        <span className="inline-block px-2.5 py-0.5 rounded-full bg-primary/18 text-primary text-[10px] font-bold mb-3">
          👋 欢迎
        </span>
        <h2
          id="onboarding-welcome-title"
          className="text-lg font-semibold leading-tight mb-2 text-foreground"
        >
          欢迎使用 StockAI Terminal
        </h2>
        <p className="text-xs text-muted-foreground leading-relaxed mb-3">
          30 秒了解你将用到的核心能力，随时可跳过。
        </p>
        <div className="grid gap-2 mb-4">
          <FeatItem
            n="1"
            title="AI 分析"
            desc="14 大师 + 8 维结构化报告 + K 线 + 多空辩论"
          />
          <FeatItem
            n="2"
            title="智能选股 V3"
            desc="自然语言 → 候选股票 + 圆桌辩论 + 投票共识"
          />
          <FeatItem
            n="3"
            title="纸面交易"
            desc="不动用真金的策略追踪，按 Plan / Event 双视图复盘"
          />
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" className="flex-1" onClick={onSkip}>
            稍后再说
          </Button>
          <Button className="flex-1" onClick={onStartTour}>
            开始 60 秒导览
          </Button>
        </div>
        <div className="mt-3 px-2.5 py-2 rounded-md bg-yellow-500/8 border border-yellow-500/25 text-[10.5px] text-muted-foreground leading-snug">
          ⚠️ <b>风险提示</b>：本系统输出为 AI 研究观点，
          <b>不构成投资建议</b>；纸面交易仅作模拟，不触发任何真实下单。
        </div>
      </div>
    </div>
  )
}
