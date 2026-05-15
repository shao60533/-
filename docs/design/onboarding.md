# 设计方案：新手引导（Onboarding）v1.0

| 项 | 值 |
|---|---|
| Feature | `onboarding` |
| 版本 | v1.0 |
| 日期 | 2026-05-15 |
| 关联 PRD | [../prd/onboarding.md](../prd/onboarding.md) |
| 关联 demo | [`demo_onboarding_v1.html`](../../demo_onboarding_v1.html) |

---

## 1. 现状审计

### 1.1 当前认证 → 首页路径

| 端点 / 文件 | 行为 |
|---|---|
| [`/api/auth/register` (web/app.py)](../../stock_trading_system/web/app.py) | invite code + email + password → `repo.create()` → `_invite_mgr.redeem()` → set `session["user_id"]` |
| [`/api/auth/oauth/register`](../../stock_trading_system/web/app.py) | OAuth pending + invite code → 创建 user → 同上 |
| [`AppShell.tsx`](../../stock_trading_system/web/frontend/src/components/shared/AppShell.tsx) | 移动端 sticky topbar + main + tabbar，**无引导组件挂载点** |
| [`DashboardPage.tsx`](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) | 首页内容，**无 welcome modal / checklist 调用** |

**结论**：完全无引导基础设施。本期从零搭建，所有改动叠加在现有架构上。

### 1.2 4 任务完成动作映射到现有 API

| 任务 | 触发 API | 文件:行 |
|---|---|---|
| `add-holding` | `POST /api/portfolio/buy` 成功 | [`web/app.py`](../../stock_trading_system/web/app.py) 持仓买入 handler |
| `first-analysis` | `analysis_history` 写入 user 自己创建的行 | analysis worker / save_analysis 路径 |
| `first-screen` | `tasks` 表 `type=screen_v3` 行 `status=success` 首次出现 | screener-v3 worker success callback |
| `first-paper-plan` | `paper_trade_plans` 新行写入 | paper trade `save_plan` 路径 |

每个完成点调用统一 helper `_mark_onboarding_step(user_id, step_id)`，**fail-soft**（写失败 log warn 不抛）。

---

## 2. Schema

### 2.1 新表 `user_onboarding`

```sql
CREATE TABLE IF NOT EXISTS user_onboarding (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  welcome_pending INTEGER NOT NULL DEFAULT 0,      -- 0/1, 注册后置 1
  welcomed INTEGER NOT NULL DEFAULT 0,             -- 用户首次看到/跳过 welcome modal 后置 1
  tour_completed INTEGER NOT NULL DEFAULT 0,       -- 走完 Driver.js Tour 后置 1
  tour_skipped_at_step INTEGER,                    -- 中途跳出在第几步(P1, v1.0 可选)
  checklist_dismissed INTEGER NOT NULL DEFAULT 0,  -- 用户主动关闭 checklist
  steps_completed TEXT NOT NULL DEFAULT '{}',      -- JSONB: {"add-holding":true, "first-analysis":true, ...}
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**关键约束**：
- `user_id PRIMARY KEY` —— 一个用户一行
- `ON DELETE CASCADE` —— user 硬删时自动清（软删 status='deleted' 不动）
- `steps_completed` 是 JSON 字符串，便于未来扩展任务（5/6/...）不动 schema
- **不存任何 PII**（user_id 已是 FK 引用即可）

### 2.2 Migration（[`migrations/add_user_onboarding.py`](../../stock_trading_system/migrations/add_user_onboarding.py)，新建，idempotent）

```python
def add_user_onboarding(db_path: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_onboarding'").fetchone():
            return False
        conn.executescript("""
            CREATE TABLE user_onboarding (
              user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
              welcome_pending INTEGER NOT NULL DEFAULT 0,
              welcomed INTEGER NOT NULL DEFAULT 0,
              tour_completed INTEGER NOT NULL DEFAULT 0,
              tour_skipped_at_step INTEGER,
              checklist_dismissed INTEGER NOT NULL DEFAULT 0,
              steps_completed TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    return True
```

接入 [`auth/bootstrap.py`](../../stock_trading_system/auth/bootstrap.py) startup migration 链，与 OAuth migration 并列。

---

## 3. Backend: `OnboardingRepository` + 4 端点

### 3.1 Repository（[`auth/onboarding_repository.py`](../../stock_trading_system/auth/onboarding_repository.py)）

```python
@dataclass
class OnboardingState:
    user_id: int
    welcome_pending: bool
    welcomed: bool
    tour_completed: bool
    checklist_dismissed: bool
    steps_completed: dict[str, bool]   # 解析后的 JSON
    updated_at: str


class OnboardingRepository:
    KNOWN_STEPS = frozenset({
        "add-holding", "first-analysis", "first-screen", "first-paper-plan",
    })

    def __init__(self, db_path: str):
        self._db_path = db_path

    def get_or_init(self, user_id: int) -> OnboardingState:
        """Return state; create row with defaults if missing."""

    def init_for_new_user(self, user_id: int) -> None:
        """Called from register handler. Sets welcome_pending=1."""

    def mark_step(self, user_id: int, step_id: str) -> bool:
        """Mark one step completed. Returns False if step_id unknown or already done."""
        # 校验:step_id 必须在 KNOWN_STEPS
        # 幂等:已 true 直接返 False 不写 DB
        # 写完更新 updated_at

    def mark_welcomed(self, user_id: int, tour_completed: bool = False) -> None: ...

    def dismiss_checklist(self, user_id: int) -> None: ...

    def reset(self, user_id: int) -> None:
        """Clear all flags + steps. Used by /api/onboarding/reset."""
        # welcome_pending → 1(重置后下次进首页重新弹)
        # 其它全部 → 0 / {}
```

**Fail-soft 政策**：所有写操作 try/except 包裹 + log warn，**不抛**——onboarding 写失败不能阻塞核心业务（如 register / portfolio.buy）。

### 3.2 4 个 API 端点（[`web/app.py`](../../stock_trading_system/web/app.py)）

```python
@app.route("/api/onboarding/state")
def get_onboarding_state():
    if g.user is None:
        return jsonify({"error": "unauthorized"}), 401
    state = _onboarding_repo.get_or_init(g.user.id)
    return jsonify({
        "welcome_pending": state.welcome_pending,
        "welcomed": state.welcomed,
        "tour_completed": state.tour_completed,
        "checklist_dismissed": state.checklist_dismissed,
        "steps_completed": state.steps_completed,
    })


@app.route("/api/onboarding/mark-welcomed", methods=["POST"])
def mark_welcomed():
    if g.user is None: return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    tour_completed = bool(body.get("tour_completed", False))
    _onboarding_repo.mark_welcomed(g.user.id, tour_completed=tour_completed)
    return jsonify({"ok": True})


@app.route("/api/onboarding/dismiss-checklist", methods=["POST"])
def dismiss_checklist():
    if g.user is None: return jsonify({"error": "unauthorized"}), 401
    _onboarding_repo.dismiss_checklist(g.user.id)
    return jsonify({"ok": True})


@app.route("/api/onboarding/reset", methods=["POST"])
def reset_onboarding():
    if g.user is None: return jsonify({"error": "unauthorized"}), 401
    _onboarding_repo.reset(g.user.id)
    return jsonify({"ok": True})
```

**注意**：**没有** `/api/onboarding/complete-step` 公开端点——任务完成只能由后端在对应业务 handler 中调 `_mark_onboarding_step(g.user.id, "...")` 触发，**禁止**前端主动 POST 完成步骤（防伪造）。

### 3.3 注册时初始化（修改 register handlers）

```python
# /api/auth/register handler 内,user_repo.create() 之后 _invite_mgr.redeem() 之前:
_onboarding_repo.init_for_new_user(new_user.id)
```

同样改 `/api/auth/oauth/register` handler。

### 3.4 4 个任务完成钩子（4 处既有 handler 内插一行）

| 触发点 | 文件:行 | 插入代码 |
|---|---|---|
| 持仓买入成功 | [`web/app.py`](../../stock_trading_system/web/app.py) `POST /api/portfolio/buy` handler 成功路径末尾 | `_mark_onboarding_step(g.user.id, "add-holding")` |
| 分析任务 success | [`tasks/workers.py`](../../stock_trading_system/tasks/workers.py) `make_analysis_worker` `save_analysis` 后 / 或 web 层 `on_task_complete` | `_mark_onboarding_step(user_id, "first-analysis")` |
| 选股 v3 任务 success | [`tasks/workers.py`](../../stock_trading_system/tasks/workers.py) `make_screen_v3_worker` 成功 return 前 | `_mark_onboarding_step(user_id, "first-screen")` |
| 纸面交易 plan 创建 | [`strategy/paper_trader/session_store.py`](../../stock_trading_system/strategy/paper_trader/session_store.py) `save_plan` 成功 / 或 web 层 paper-trade plan endpoint | `_mark_onboarding_step(user_id, "first-paper-plan")` |

**Helper**（web/app.py 或 tasks/onboarding_hooks.py）：
```python
def _mark_onboarding_step(user_id: int, step_id: str) -> None:
    """Fail-soft helper. Never raises — onboarding write failure
    must not break the business action that triggered it."""
    if not user_id:
        return
    try:
        _onboarding_repo.mark_step(user_id, step_id)
    except Exception as e:
        logger.warning("onboarding mark_step failed user=%d step=%s: %s",
                       user_id, step_id, e)
```

worker 内部从 `params["__user_id__"]` 或 `params["user_id"]` 取（已是现有惯例，复用）。

---

## 4. 前端组件

### 4.1 目录结构

```
stock_trading_system/web/frontend/src/
├── components/shared/onboarding/
│   ├── WelcomeModal.tsx            ← 新建
│   ├── OnboardingChecklist.tsx     ← 新建
│   ├── EmptyStateCTA.tsx           ← 新建(4 处空状态复用)
│   ├── useOnboardingState.ts       ← 新建(hook,统一状态)
│   ├── useOnboardingTour.ts        ← 新建(Driver.js wrapper)
│   ├── tour-steps.ts               ← 新建(6 步 Tour 配置)
│   └── onboarding-anchors.ts       ← 新建(锚点 ID 常量,共享)
├── styles/
│   └── onboarding.css              ← 新建(Driver.js dark theme 覆写)
└── components/shared/
    ├── AppShell.tsx                ← 修改:挂载 <WelcomeModal> + <OnboardingChecklist>
    ├── LLMSwitcher.tsx             ← 修改:加首次点击 inline hint
    └── ...其它既有组件不动
```

### 4.2 `useOnboardingState` hook

```ts
export interface OnboardingState {
  welcome_pending: boolean
  welcomed: boolean
  tour_completed: boolean
  checklist_dismissed: boolean
  steps_completed: Record<string, boolean>
}

export function useOnboardingState() {
  const [state, setState] = useState<OnboardingState | null>(null)

  const refresh = useCallback(async () => {
    try {
      const data = await apiGet<OnboardingState>("/api/onboarding/state")
      setState(data)
    } catch { /* silent */ }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const markWelcomed = useCallback(async (tour_completed = false) => {
    await apiPost("/api/onboarding/mark-welcomed", { tour_completed })
    refresh()
  }, [refresh])

  const dismissChecklist = useCallback(async () => {
    await apiPost("/api/onboarding/dismiss-checklist", {})
    refresh()
  }, [refresh])

  const reset = useCallback(async () => {
    await apiPost("/api/onboarding/reset", {})
    refresh()
  }, [refresh])

  return { state, markWelcomed, dismissChecklist, reset, refresh }
}
```

### 4.3 `<WelcomeModal>`

视觉对齐 [`demo_onboarding_v1.html`](../../demo_onboarding_v1.html) `.modal` 部分：
- 蓝色 badge "👋 欢迎"
- 标题 + 一句话副标
- 3 大能力卡（AI 分析 / 智能选股 / 纸面交易）
- 双 CTA: `稍后再说` / `开始 60 秒导览`
- 底部黄底风险提示

```tsx
interface WelcomeModalProps {
  open: boolean
  onSkip: () => void
  onStartTour: () => void
}

export function WelcomeModal({ open, onSkip, onStartTour }: WelcomeModalProps) {
  if (!open) return null
  return (
    <div className="md:hidden fixed inset-0 z-[100] bg-background/72 backdrop-blur-sm grid place-items-center p-4">
      <div className="w-full max-w-[340px] rounded-2xl border border-primary/25 bg-card shadow-2xl p-5">
        <span className="inline-block px-2.5 py-0.5 rounded-full bg-primary/18 text-primary text-[10px] font-bold mb-3">
          👋 欢迎
        </span>
        <h2 className="text-lg font-semibold leading-tight mb-2">欢迎使用 StockAI Terminal</h2>
        <p className="text-xs text-muted-foreground leading-relaxed mb-3">
          30 秒了解你将用到的核心能力，随时可跳过。
        </p>
        <div className="grid gap-2 mb-4">
          <FeatItem n="1" title="AI 分析" desc="14 大师 + 8 维结构化报告 + K 线 + 多空辩论" />
          <FeatItem n="2" title="智能选股 V3" desc="自然语言 → 候选股票 + 圆桌辩论 + 投票共识" />
          <FeatItem n="3" title="纸面交易" desc="不动用真金的策略追踪，按 Plan / Event 双视图复盘" />
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" className="flex-1" onClick={onSkip}>稍后再说</Button>
          <Button className="flex-1" onClick={onStartTour}>开始 60 秒导览</Button>
        </div>
        <div className="mt-3 px-2.5 py-2 rounded-md bg-yellow-500/8 border border-yellow-500/25 text-[10.5px] text-muted-foreground leading-snug">
          ⚠️ <b>风险提示</b>：本系统输出为 AI 研究观点，<b>不构成投资建议</b>；纸面交易仅作模拟，不触发任何真实下单。
        </div>
      </div>
    </div>
  )
}
```

### 4.4 `<OnboardingChecklist>`

```tsx
const TASKS = [
  { id: "add-holding",      label: "添加第一只持仓",         href: "/" },
  { id: "first-analysis",   label: "完成第一次 AI 分析",      href: "/analysis" },
  { id: "first-screen",     label: "完成第一次智能选股",      href: "/screener-v3" },
  { id: "first-paper-plan", label: "创建第一笔纸面交易计划",   href: "/paper-trade" },
] as const

interface OnboardingChecklistProps {
  stepsCompleted: Record<string, boolean>
  onDismiss: () => void
}

export function OnboardingChecklist({ stepsCompleted, onDismiss }: OnboardingChecklistProps) {
  const done = TASKS.filter(t => stepsCompleted[t.id]).length
  const pct = Math.round((done / TASKS.length) * 100)

  // 100% 时延迟 600ms 后调 onDismiss + toast 庆祝
  useEffect(() => {
    if (done === TASKS.length) {
      const t = setTimeout(() => {
        onDismiss()
        toast.success("🎉 全部任务完成！可在设置中重新开启引导")
      }, 600)
      return () => clearTimeout(t)
    }
  }, [done, onDismiss])

  return (
    <div
      id="onboarding-checklist"
      className="md:hidden fixed left-3 right-3 bottom-[70px] z-[6] rounded-2xl border border-primary/30 bg-card/96 backdrop-blur shadow-xl p-3"
    >
      <div className="flex items-center justify-between mb-1.5">
        <strong className="text-[13px]">🚀 上手任务</strong>
        <button className="w-5 h-5 text-muted-foreground hover:text-foreground" onClick={onDismiss} aria-label="关闭引导">×</button>
      </div>
      <div className="h-1 bg-white/6 rounded-full overflow-hidden mb-2.5">
        <div className="h-full bg-gradient-to-r from-primary to-green-500 transition-all duration-300"
             style={{ width: `${pct}%` }} />
      </div>
      {TASKS.map((t, i) => {
        const ok = stepsCompleted[t.id]
        return (
          <a key={t.id} href={ok ? "#" : t.href}
             onClick={(e) => { if (ok) e.preventDefault() }}
             className={cn(
               "flex items-center gap-2.5 py-1.5 text-xs border-b border-white/4 last:border-0",
               ok ? "text-muted-foreground line-through" : "cursor-pointer hover:text-primary",
             )}>
            <span className={cn(
              "w-4 h-4 rounded-full border grid place-items-center text-[10px] shrink-0",
              ok ? "border-green-500 bg-green-500 text-background" : "border-line-2",
            )}>
              {ok ? "✓" : (i + 1)}
            </span>
            <span className="flex-1">{t.label}</span>
            {!ok && <span className="text-muted-foreground/60">›</span>}
          </a>
        )
      })}
    </div>
  )
}
```

### 4.5 `useOnboardingTour` hook + `tour-steps.ts`

```ts
// tour-steps.ts
export const TOUR_STEPS: readonly TourStep[] = [
  { element: "#topbar",
    popover: { title: "顶栏 · 品牌与模型切换", description: "蓝色 chip 切换 AI 模型(OpenRouter / Qwen / Gemini)+ deep/quick 双挡。", side: "bottom" } },
  { element: "#account-hero",
    popover: { title: "账户 Hero · 总览与趋势", description: "账户总值 + 今日 PnL + 90D sparkline + 三栏 metric。", side: "bottom" } },
  { element: "#holdings-section",
    popover: { title: "持仓明细 · 决策中枢", description: "搜索 / 买入 / 5 ↔ 全部 / 每只可看分析、卖出、修正成本、移除。", side: "top" } },
  { element: "#batch-analyze-card",
    popover: { title: "批量分析持仓", description: "一键复核所有持仓的最新 AI 观点。跳过 4h 内已分析,逐只顺序执行。", side: "top" } },
  { element: "[data-mobile-tabbar]",
    popover: { title: "底部导航 · 5 个一级入口", description: "首页 / 分析 / 发现 / 纸面 / 更多。", side: "top" } },
  { element: "#onboarding-checklist",
    popover: { title: "4 项上手任务", description: "完成 4 项即解锁全部核心功能。完成度持续显示,可随时折叠。", side: "top" } },
] as const

// useOnboardingTour.ts
import { driver } from "driver.js"
import "driver.js/dist/driver.css"
import "@/styles/onboarding.css"   // 我们的 dark theme 覆写

export function useOnboardingTour() {
  const start = useCallback((opts: { onDone: () => void }) => {
    const d = driver({
      showProgress: true,
      progressText: "{{current}} / {{total}}",
      nextBtnText: "下一步 →",
      prevBtnText: "← 上一步",
      doneBtnText: "完成 ✓",
      allowClose: true,
      smoothScroll: true,
      stagePadding: 6,
      stageRadius: 10,
      steps: TOUR_STEPS,
      onDestroyed: () => opts.onDone(),
    })
    d.drive()
  }, [])
  return { start }
}
```

### 4.6 锚点 ID 注入既有组件

在已落地组件加 `id`/`data-*` 属性（**不动其它代码**）：

| 文件:行 | 改动 |
|---|---|
| [`MobileTopbar.tsx`](../../stock_trading_system/web/frontend/src/components/shared/MobileTopbar.tsx) | `<header id="topbar" ...>` |
| [`DashboardPage.tsx AccountOverviewCard`](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) | `<Card id="account-hero" ...>` |
| [`HoldingsSection.tsx`](../../stock_trading_system/web/frontend/src/islands/dashboard/HoldingsSection.tsx) | 外层容器加 `<div id="holdings-section">` |
| [`HoldingsSection.tsx BatchAnalyzeHoldingsCard`](../../stock_trading_system/web/frontend/src/islands/dashboard/HoldingsSection.tsx) | `<Card id="batch-analyze-card" ...>` |
| [`Sidebar.tsx MobileTabbar`](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) | `<nav data-mobile-tabbar ...>` |

`#onboarding-checklist` 由 `<OnboardingChecklist>` 自己挂。

### 4.7 `<AppShell>` 集成

```tsx
import { WelcomeModal } from "./onboarding/WelcomeModal"
import { OnboardingChecklist } from "./onboarding/OnboardingChecklist"
import { useOnboardingState } from "./onboarding/useOnboardingState"
import { useOnboardingTour } from "./onboarding/useOnboardingTour"

export function AppShell({ children, pageTitle }: AppShellProps) {
  const { state, markWelcomed, dismissChecklist } = useOnboardingState()
  const { start: startTour } = useOnboardingTour()

  const showWelcome = state?.welcome_pending && !state?.welcomed
  const showChecklist = state && state.welcomed && !state.checklist_dismissed
    && Object.values(state.steps_completed).filter(Boolean).length < 4

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <MobileTopbar pageTitle={pageTitle} />
        <main className="flex-1 min-w-0 pb-16 md:pb-0">{children}</main>
      </div>
      <MobileTabbar />

      {/* Onboarding 仅在 state 加载后 + 移动端渲染 */}
      <WelcomeModal
        open={!!showWelcome}
        onSkip={() => markWelcomed(false)}
        onStartTour={() => {
          markWelcomed(false)
          startTour({ onDone: () => markWelcomed(true) })
        }}
      />
      {showChecklist && state && (
        <OnboardingChecklist
          stepsCompleted={state.steps_completed}
          onDismiss={dismissChecklist}
        />
      )}
    </div>
  )
}
```

### 4.8 LLMSwitcher inline hint（[`LLMSwitcher.tsx`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx)）

在现有 dropdown trigger button 旁加：

```tsx
const HINT_KEY = "onboarding_hint_llm_dismissed"
const [showHint, setShowHint] = useState(() => !localStorage.getItem(HINT_KEY))

// 在 DropdownMenuTrigger 外层加 wrapper:
<div className="relative">
  <DropdownMenuTrigger ... />
  {showHint && (
    <div className="md:hidden absolute top-full right-0 mt-2 max-w-[240px] p-2.5 rounded-md border border-primary/35 bg-primary/10 text-xs shadow-xl z-50">
      点这里切换 AI 模型(OpenRouter / Qwen / Gemini)。
      <button className="absolute top-1 right-1 text-muted-foreground" onClick={() => {
        localStorage.setItem(HINT_KEY, "1")
        setShowHint(false)
      }}>×</button>
    </div>
  )}
</div>
```

用户首次**点 trigger 或** 关 hint 后 → localStorage 标记永久静默。

### 4.9 设置页"新手引导" section（[`SettingsPage.tsx`](../../stock_trading_system/web/frontend/src/islands/settings/SettingsPage.tsx)）

```tsx
function OnboardingSection() {
  const { reset } = useOnboardingState()
  const [busy, setBusy] = useState(false)
  return (
    <Card>
      <CardHeader><CardTitle>新手引导</CardTitle></CardHeader>
      <CardContent>
        <p className="text-xs text-muted-foreground mb-3">
          重新观看欢迎导览与 4 项上手任务清单（仅移动端可见）。
        </p>
        <Button variant="outline" size="sm" disabled={busy} onClick={async () => {
          setBusy(true)
          try {
            await reset()
            toast.success("已重置,回首页查看")
          } finally { setBusy(false) }
        }}>
          {busy ? "重置中..." : "重新观看引导"}
        </Button>
      </CardContent>
    </Card>
  )
}
```

### 4.10 4 处空状态 CTA

复用 `<EmptyStateCTA>` 共享组件：

```tsx
interface EmptyStateCTAProps {
  icon?: React.ReactNode
  message: string
  ctaLabel: string
  onClick?: () => void
  href?: string
}

export function EmptyStateCTA({ icon, message, ctaLabel, onClick, href }: EmptyStateCTAProps) {
  return (
    <div className="border border-dashed border-white/15 bg-white/2 rounded-lg p-6 text-center">
      {icon && <div className="text-3xl opacity-55 mb-2">{icon}</div>}
      <p className="text-xs text-muted-foreground mb-3">{message}</p>
      {href
        ? <a href={href}><Button>{ctaLabel}</Button></a>
        : <Button onClick={onClick}>{ctaLabel}</Button>}
    </div>
  )
}
```

集成到 4 处：
- 持仓为空 (`HoldingsSection`)：复用本组件替换现有"暂无持仓"提示
- Analysis Inbox 为空 (`AnalysisPage`)：line 508 既有 "暂无分析记录" 改本组件
- 选股最近为空 (`RecentScreensCard`)：当前 list 空时显示
- 纸面列表为空 (`PaperTradeListPage`)：list 空时显示

---

## 5. Driver.js 集成细节

### 5.1 安装

```bash
cd stock_trading_system/web/frontend
npm install driver.js@^1.3
```

`package.json` dependencies 加 `"driver.js": "^1.3.1"`。

**不走 CDN**——本地依赖保证国内访问与离线开发。

### 5.2 Dark 主题 CSS 覆写（[`styles/onboarding.css`](../../stock_trading_system/web/frontend/src/styles/onboarding.css)）

复用 [`demo_onboarding_v1.html`](../../demo_onboarding_v1.html) `.driver-popover` 等覆写规则（约 20 行）。

### 5.3 z-index 层级

| 元素 | z-index | 备注 |
|---|---|---|
| 主内容 | 0 | 默认 |
| MobileTabbar | 5 | tab 栏 |
| OnboardingChecklist | 6 | 浮于 tabbar 之上 |
| MobileTopbar | 40 | sticky 顶栏 |
| Driver.js overlay/popover | 999 | 内置 |
| WelcomeModal | 100 | 进入 modal 时高于 onboarding 但低于 Driver.js |

---

## 6. 测试

### 6.1 后端单测

`tests/auth/test_onboarding_repository.py`（7 case）：
1. `get_or_init` 新 user → 返回默认 state
2. `init_for_new_user` → `welcome_pending=1`
3. `mark_step("add-holding")` 后 `steps_completed["add-holding"]=true`
4. `mark_step` 未知 step_id → 返 False 不写
5. `mark_step` 已 true → 幂等 返 False
6. `reset` 清所有 flag + 重置 `welcome_pending=1`
7. 跨用户隔离：alice mark_step 不影响 bob

`tests/web/test_onboarding_api.py`（10 case）：
1-3. GET state 未登录 401 / 已登录 200 / 跨用户隔离
4-5. POST mark-welcomed `tour_completed=false` / `true`
6. POST dismiss-checklist
7. POST reset
8. **没有** `/api/onboarding/complete-step` 公开端点（防伪造）
9. 注册后 state.welcome_pending=true
10. OAuth 注册后 state.welcome_pending=true

`tests/tasks/test_onboarding_hooks.py`（4 case）：
1. portfolio.buy 成功 → "add-holding" 标记
2. analysis worker save 成功 → "first-analysis" 标记
3. screen_v3 worker success → "first-screen" 标记
4. paper_trade save_plan → "first-paper-plan" 标记

### 6.2 前端单测

`__tests__/WelcomeModal.test.tsx`（3 case）：
1. `open=true` 渲染 / `open=false` 不渲染
2. 点 Skip → onSkip 调用
3. 点 Start Tour → onStartTour 调用

`__tests__/OnboardingChecklist.test.tsx`（5 case）：
1. 4 任务渲染（标签 + 序号）
2. 完成 2 项 → progress bar 50%
3. 完成项 line-through + ring 绿
4. 100% → setTimeout 后 onDismiss 调用
5. 点未完成项 → href 跳转 / 完成项 href="#" 不跳

`__tests__/useOnboardingState.test.tsx`（4 case）：
1. mount 调 GET /api/onboarding/state
2. markWelcomed POST + refresh
3. dismissChecklist POST + refresh
4. reset POST + refresh

### 6.3 集成 / E2E

Playwright 5 新 case：
1. 注册新用户 alice → 进首页 → WelcomeModal 弹出
2. 点 "稍后再说" → modal 关 + Checklist 显示
3. 点 "开始 60 秒导览" → Driver.js Tour 启动 6 步
4. 模拟买入持仓 → Checklist "add-holding" 划掉
5. 4 项全完成 → 600ms 后 Checklist 消失 + toast

桌面端断言：≥md viewport WelcomeModal / Checklist 不渲染。

### 6.4 手动 5 机型

iPhone SE 2 / 14 / 14 Pro Max / Pixel 7 / iPad

10 项检查：
1. ✅ 新用户注册 → 进首页 → modal 自动弹
2. ✅ 风险提示在 modal 底部黄底可见
3. ✅ 点 "开始导览" → Tour 6 步顺序聚焦
4. ✅ Tour 任意步可点 × 退出
5. ✅ Tour 结束 → Checklist 显示
6. ✅ Checklist 点项 → 跳对应页面
7. ✅ 完成对应动作 → 任务自动划掉
8. ✅ 100% → Checklist 消失 + toast
9. ✅ 设置页"重新观看引导" → 重置生效
10. ✅ 桌面端 ≥md 无引导组件渲染

---

## 7. 实施顺序

| 步骤 | 工作 | 文件 | LOC |
|---|---|---|---|
| 1 | Schema migration + bootstrap 接入 | `migrations/add_user_onboarding.py`, `auth/bootstrap.py` | ~40 |
| 2 | `OnboardingRepository` + 7 单测 | `auth/onboarding_repository.py`, tests | ~150 |
| 3 | 4 个 API 端点 + 10 单测 + 2 register handler 改动 | `web/app.py`, tests | ~120 |
| 4 | 4 个任务完成钩子 + 4 单测 | `web/app.py`, `tasks/workers.py`, `paper_trader/session_store.py`, tests | ~50 |
| 5 | npm install driver.js + onboarding.css 覆写 | `package.json`, `styles/onboarding.css` | ~30 |
| 6 | `useOnboardingState` hook + 4 vitest | `hooks/useOnboardingState.ts`, tests | ~80 |
| 7 | `tour-steps.ts` + `useOnboardingTour` hook | `components/shared/onboarding/` | ~50 |
| 8 | `<WelcomeModal>` + 3 vitest | `components/shared/onboarding/WelcomeModal.tsx`, tests | ~120 |
| 9 | `<OnboardingChecklist>` + 5 vitest | `components/shared/onboarding/OnboardingChecklist.tsx`, tests | ~130 |
| 10 | `<AppShell>` 集成 + 5 锚点 ID 注入既有组件 | `components/shared/AppShell.tsx` + 5 组件改 1 行 | ~30 |
| 11 | LLMSwitcher inline hint | `components/shared/LLMSwitcher.tsx` | ~30 |
| 12 | 4 处空状态 CTA + `<EmptyStateCTA>` 共享组件 | 4 个 island + `components/shared/EmptyStateCTA.tsx` | ~80 |
| 13 | 设置页 "新手引导" section | `islands/settings/SettingsPage.tsx` | ~30 |
| 14 | Playwright 5 新 case + 手动 5 机型回归 | — | ~80 |
| **合计** | | | **~1020 LOC** + ~80 行文档 |

每步独立 commit。预估总工时 **~9h**。

---

## 8. 严格不动清单

- [`<LLMSwitcher>`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 内部逻辑（仅加 inline hint wrapper）
- 桌面 `<Sidebar>` 视觉
- OAuth quick-signin 任何路由 / 流程
- 邀请码 / 多租户隔离
- `users` 表 schema
- TradingAgents / LLM / screener / paper-trade 业务逻辑
- 6 个锚点宿主组件的内部实现（仅加 `id`/`data-*` 一行）
- shadcn UI primitives

---

## 9. 风险

| 风险 | 影响 | 处理 |
|---|---|---|
| Driver.js 锚点元素未渲染（懒加载组件）| Tour 卡死 | 6 个锚点均在 dashboard 首屏 + 永久挂载；`allowClose: true` 提供逃生 |
| 老用户 `user_onboarding` 表无行 → state API 返默认空 | 老用户突然看到 modal | 后端只在 register handler 写 `welcome_pending=1`；老用户行不存在 → `get_or_init` 创建时默认 `welcome_pending=0` → 不弹 modal |
| 注册 → 重定向首页 → state API 调用 race | 首次 modal 闪现失败 | `useOnboardingState` mount 时 fetch；fetch 完成前 `state===null` 不渲染任何引导组件 |
| 任务完成钩子调用失败（DB 异常）| 业务动作未失败但任务未标记 | `_mark_onboarding_step` fail-soft + log warn，不抛 |
| 用户清浏览器缓存丢失 LLM hint dismiss | hint 重弹一次 | 可接受（用户主动清缓存即重置） |
| 引导组件 z-index 与 modal/sheet/toast 冲突 | 视觉错乱 | §5.3 明确分层 |
| Driver.js 版本变更 API 不兼容 | 升级时坏 | pin `^1.3.1`，next major (2.x) 出来时统一评估 |
| 风险提示文案合规要求修改 | 文案变 | 常量集中在 `<WelcomeModal>` 一处 |

---

*v1.0 设计稿 — 等待确认后开始实施*
