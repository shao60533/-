# 设计方案：移动端顶栏 + 账户卡 hero 化（v1.3.1 增量）

| 项 | 值 |
|---|---|
| Feature | `mobile-ui-v1.3.1` |
| 版本 | v1.3.1 |
| 日期 | 2026-05-10 |
| 关联 PRD | [../prd/mobile-ui-v1.3.1.md](../prd/mobile-ui-v1.3.1.md) |
| 父设计 | [mobile-ui-v1.3.md](mobile-ui-v1.3.md) |

---

## 1. 现状审计（实测 2026-05-10）

### 1.1 AppShell 移动端结构

[`components/shared/AppShell.tsx`](../../stock_trading_system/web/frontend/src/components/shared/AppShell.tsx) 当前完整实现：

```tsx
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />                        {/* hidden md:flex 桌面侧栏 */}
      <main className="flex-1 min-w-0 pb-16 md:pb-0">{children}</main>
      <MobileTabbar />                   {/* md:hidden 底部 tab */}
    </div>
  )
}
```

**移动端结构**：仅有底部 tabbar + 主内容，**没有顶栏**。

### 1.2 LLMSwitcher 现状

[`components/shared/LLMSwitcher.tsx`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 是完整两段式 dropdown（provider + role preset，[OpenRouter v1.0 §9.1](llm-openrouter.md) 落地）。当前调用点：
- [`Sidebar.tsx:88`](../../stock_trading_system/web/frontend/src/components/shared/Sidebar.tsx) `<Sidebar>` 桌面侧栏顶部 logo 下方

**移动端无消费点**。

### 1.3 DashboardPage 账户卡

[`DashboardPage.tsx:494-549 <AccountOverviewCard>`](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 当前结构：
```
<Card>
  <CardContent>
    [账户总值] [今日 PnL]
    ─── border-t ───
    [总盈亏] [收益率] [活跃预警]   (grid-cols-3)
  </CardContent>
</Card>
```

**缺**：mini sparkline / hero 容器。

净值曲线在 [line 368-417](../../stock_trading_system/web/frontend/src/islands/dashboard/DashboardPage.tsx) 独立 Card 中（带完整 6 个 range chips + 重新计算按钮），位于 `lg:grid-cols-3` 桌面网格——移动端被推到首屏外。

### 1.4 数据流（不需新增）

- `<DashboardPage>` 调 [`/api/portfolio`](../../stock_trading_system/web/app.py) 拿 `data.history[]`（净值快照数组，每条 `{date, total_value, total_pnl, ...}`）
- `filteredHistory` 已按 range 过滤
- mini-chart 复用同一份数据，不需新接口

---

## 2. 模块结构

```
stock_trading_system/web/frontend/src/components/shared/
├── AppShell.tsx              ← 修改：插入 <MobileTopbar pageTitle={...}>
├── Sidebar.tsx               ← 不动(LLMSwitcher 仍在桌面侧栏)
├── LLMSwitcher.tsx           ← 不动(消费方+1)
├── MobileTopbar.tsx          ← 新建
└── Sparkline.tsx             ← 新建(纯 SVG mini-chart,~50 LOC)

stock_trading_system/web/frontend/src/islands/
├── dashboard/main.tsx        ← 修改:<AppShell pageTitle="首页 · 资产与持仓">
├── dashboard/DashboardPage.tsx ← 修改:<AccountOverviewCard> 加 sparkline + hero className
├── analysis/main.tsx         ← 修改:<AppShell pageTitle="分析 · Inbox 与命令">
├── screener-v3/main.tsx      ← 修改:<AppShell pageTitle="发现 · 智能选股 V3">
├── paper-trade-list/main.tsx ← 修改:<AppShell pageTitle="纸面交易">
├── ... (其余 island main.tsx 同步加 pageTitle prop)
```

---

## 3. `<MobileTopbar>` 设计

### 3.1 Props

```tsx
interface MobileTopbarProps {
  pageTitle?: string;   // 副标,如 "首页 · 资产与持仓"
}
```

### 3.2 渲染结构

```tsx
export function MobileTopbar({ pageTitle }: MobileTopbarProps) {
  return (
    <header className="md:hidden sticky top-0 z-40 bg-background/95 backdrop-blur border-b border-border">
      <div className="flex items-center justify-between gap-3 px-4 py-2.5 min-w-0">
        <div className="min-w-0 flex flex-col">
          <span className="text-sm font-bold text-primary truncate">⚡ StockAI Terminal</span>
          {pageTitle && (
            <span className="text-[11px] text-muted-foreground truncate max-w-[200px]">
              {pageTitle}
            </span>
          )}
        </div>
        <div className="shrink-0">
          <LLMSwitcher />
        </div>
      </div>
    </header>
  )
}
```

**关键属性**：
- `md:hidden` —— 仅移动端
- `sticky top-0 z-40` —— 滚动跟随，z 高于内容低于 modal/sheet（modal 通常 z-50+）
- `bg-background/95 backdrop-blur` —— 半透明 + 模糊，避免内容透出
- `pb-16` 已在 `<main>`，不冲突
- LLMSwitcher 用 `shrink-0` 保证窄屏不被压缩

### 3.3 AppShell 集成

```tsx
export function AppShell({ children, pageTitle }: {
  children: React.ReactNode;
  pageTitle?: string;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <MobileTopbar pageTitle={pageTitle} />
        <main className="flex-1 min-w-0 pb-16 md:pb-0">{children}</main>
      </div>
      <MobileTabbar />
    </div>
  )
}
```

每个 island main entry 显式传 `pageTitle`：
```tsx
// dashboard/main.tsx
<AppShell pageTitle="首页 · 资产与持仓">
  <DashboardPage />
</AppShell>
```

### 3.4 副标文案统一表

| Island | pageTitle |
|---|---|
| dashboard | `首页 · 资产与持仓` |
| analysis | `分析 · Inbox 与命令` |
| screener-v3 | `发现 · 智能选股 V3` |
| paper-trade-list / paper-trade-detail | `纸面交易` |
| portfolio（桌面侧栏可达，移动端经持仓详情来）| `持仓 · 管理` |
| transactions | `持仓 · 交易记录` |
| reports | `报告中心` |
| backtest | `策略回测` |
| alerts | `预警中心` |
| tasks | `任务中心` |
| settings | `系统设置` |
| login / register | （这两页通常无 AppShell 框架，不动）|

副标文案与 [demo `viewNames`](../../demo_mobile_full_v1.html) 完全对齐。

---

## 4. `<Sparkline>` 设计

### 4.1 选型

不引入新图表库。两选择：
- **A.** 复用 [`<ChartPanel>`](../../stock_trading_system/web/frontend/src/components/shared/ChartPanel.tsx)（ECharts），option 极简化（无坐标轴、无 tooltip）
- **B.** 纯 SVG sparkline（~50 LOC，0 依赖）

**推荐 B**——sparkline 只画一条 path，ECharts 配置 + 异步加载 chunk 反而是 overkill。

### 4.2 实现（[`components/shared/Sparkline.tsx`](../../stock_trading_system/web/frontend/src/components/shared/Sparkline.tsx)）

```tsx
import { useMemo } from "react"

interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  positive?: boolean       // true=green, false=red, undefined=auto from first vs last
  className?: string
}

export function Sparkline({
  values, width = 320, height = 40, positive, className,
}: SparklineProps) {
  const path = useMemo(() => {
    if (values.length < 2) return null
    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = max - min || 1
    const stepX = width / (values.length - 1)
    return values.map((v, i) => {
      const x = i * stepX
      const y = height - ((v - min) / range) * height
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`
    }).join(" ")
  }, [values, width, height])

  if (!path) return null

  const isUp = positive ?? (values[values.length - 1] >= values[0])
  const stroke = isUp ? "var(--color-accent-green)" : "var(--color-accent-red)"
  const fill = isUp
    ? "color-mix(in srgb, var(--color-accent-green) 16%, transparent)"
    : "color-mix(in srgb, var(--color-accent-red) 16%, transparent)"

  // close the path back to baseline so we can fill under it
  const lastX = width
  const fillPath = `${path} L${lastX},${height} L0,${height} Z`

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
      style={{ width: "100%", height }}
      aria-hidden="true"
    >
      <path d={fillPath} fill={fill} />
      <path d={path} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}
```

**关键属性**：
- `preserveAspectRatio="none"` —— 让 svg 跟随容器宽度自适应
- `width:100%` —— 充满父级
- 数据点 < 2 直接返回 null（数据不足降级）
- `aria-hidden="true"` —— 装饰性不进入屏幕阅读器

---

## 5. `<AccountOverviewCard>` 升级

### 5.1 Hero 容器

```tsx
<Card className="bg-card/95 ring-1 ring-primary/10 shadow-sm">
  <CardContent className="pt-5 pb-4 px-4 space-y-3">
    {/* 第 1 段:账户总值 + 今日 PnL —— 现状不动 */}
    <div className="flex items-start justify-between gap-3 min-w-0">
      ...
    </div>

    {/* 第 2 段:mini sparkline(新增,数据不足时不渲染)*/}
    {sparklineValues.length >= 5 && (
      <div className="-mx-2">
        <Sparkline values={sparklineValues} height={44} />
      </div>
    )}

    {/* 第 3 段:三栏 metric —— 现状不动 */}
    <div className="grid grid-cols-3 gap-2 pt-1 border-t border-border/40">
      <Metric .../>
      <Metric .../>
      <Metric .../>
    </div>
  </CardContent>
</Card>
```

**视觉差异化**（hero）：
- `bg-card/95` —— 比常规 Card `bg-card` 略深或同色（具体看 token，关键是要有差异）
- `ring-1 ring-primary/10` —— 微亮边框（hero 区分）
- `shadow-sm` —— 增加视觉抬升

### 5.2 Sparkline 数据传递

`<DashboardPage>` 已有 `data.history[]`（净值快照），传入：

```tsx
const sparklineValues = useMemo(
  () => (data?.history ?? []).map(h => h.total_value).filter(v => Number.isFinite(v)),
  [data?.history],
)

<AccountOverviewCard
  pnl={pnl}
  summary={summary}
  alertsCount={data?.alerts_count ?? 0}
  sparklineValues={sparklineValues}
/>
```

`<AccountOverviewCard>` props 加 `sparklineValues: number[]`。

### 5.3 数据不足降级（R-MUI-20a）

```tsx
{sparklineValues.length >= 5 && (
  <div className="-mx-2">
    <Sparkline values={sparklineValues} height={44} />
  </div>
)}
```

- 数据点 < 5 → 不渲染（避免拉伸怪异）
- 不显示空状态占位（直接退化两段布局）

阈值 5 是经验值：少于 5 个点的 sparkline 信息密度太低，不如不画。

### 5.4 Sparkline 颜色与 PnL 一致

```tsx
const isUp = pnl.total_pnl >= 0
<Sparkline values={sparklineValues} positive={isUp} height={44} />
```

让 sparkline 颜色（绿/红）与账户 PnL 方向对齐，视觉一致。

---

## 6. 测试

### 6.1 Vitest

`__tests__/MobileTopbar.test.tsx`（4 case）：
1. 渲染品牌 `⚡ StockAI Terminal`
2. 传 `pageTitle="首页"` → 副标可见
3. 不传 pageTitle → 副标不渲染
4. LLMSwitcher 子组件被挂载（mock 检查）

`__tests__/Sparkline.test.tsx`（5 case）：
1. values < 2 → 返回 null
2. values 5 个 → 渲染 svg + 2 个 path（fill + stroke）
3. positive=true → stroke 含 `--color-accent-green`
4. positive=false → stroke 含 `--color-accent-red`
5. positive 不传 → 自动从首尾推断方向

`__tests__/AccountOverviewCard.test.tsx`（3 case，扩展现有）：
1. sparklineValues >= 5 → Sparkline 渲染
2. sparklineValues < 5 → Sparkline 不渲染（卡退化两段）
3. hero 容器有 `ring-1 ring-primary/10` className

### 6.2 Playwright（与 v1.3 同套）

12 页面 × 4 viewport 回归保留；额外加：
- 移动端任意页面顶栏可见 `StockAI Terminal` + LLMSwitcher
- 点 LLMSwitcher chip 弹出菜单（与桌面行为对齐）
- 375px viewport 首屏可见 sparkline（DOM 测试 `getByLabelText` 或类名定位）

### 6.3 手动回归

- iPhone SE 2 / 14 / 14 Pro Max / Pixel 7 五机型
- 切换 5 个一级 tab 顶栏副标实时变化
- 切换 LLM provider/preset 在移动端可用
- 数据稀疏（新用户首日）账户卡退化两段不破布局
- 桌面端 ≥md 顶栏不显示，无视觉变化

---

## 6.5 布局顺序调整（R-MUI-22 / R-MUI-23）

### 6.5.1 现状

**Analysis 页**（[`AnalysisPage.tsx:486+`](../../stock_trading_system/web/frontend/src/islands/analysis/AnalysisPage.tsx)）当前顺序：
```
<AnalysisHomeInbox>
  <Card>分析记录 Inbox</Card>      ← 在上(line 486)
  <Card>发起分析</Card>             ← 在下(line 541)
```

**Screener-v3 页**（[`ScreenerV3Page.tsx:69-73`](../../stock_trading_system/web/frontend/src/islands/screener-v3/ScreenerV3Page.tsx)）当前顺序：
```tsx
function ScreenerHomeView({ prefillId }) {
  return (
    <RecentScreensCard />          ← 在上(line 72)
    <ScreenerForm ... />           ← 在下(line 73)
  )
}
```

### 6.5.2 修法（仅 JSX 顺序交换）

**Analysis 页**：在 `<AnalysisHomeInbox>` 内把两个 `<Card>` 顺序对调——`发起分析` 卡放第一个、`分析记录 Inbox` 卡放第二个。section title 顺序同步对调。

**Screener-v3 页**：在 `ScreenerHomeView` JSX return 里把 `<RecentScreensCard />` 与 `<ScreenerForm prefillTaskId={prefillId} />` 顺序对调——`<ScreenerForm>` 在前、`<RecentScreensCard>` 在后。

### 6.5.3 不动

- `<RunningRow>` / `<CompletedRow>` 内部渲染
- `<RecentScreenCard>` 内部渲染
- 表单字段、提交逻辑、prefill 流程
- Tasks 列表（不在本期范围）
- 桌面端布局也跟着改（保持桌面与移动同序）

### 6.5.4 测试

`tests/frontend/analysis/AnalysisPage.layout.test.tsx`（2 case）：
- DOM 顺序断言 `getByText("发起分析")` 在 `getByText("分析记录")` 前
- 提交分析后乐观插入仍在 Inbox 顶部（行为不变）

`tests/frontend/screener-v3/ScreenerV3Page.layout.test.tsx`（2 case）：
- DOM 顺序断言 `<ScreenerForm>` 在 `<RecentScreensCard>` 前
- prefill 模式 banner 在 form 内（位置随 form 上移）

---

## 7. 实施顺序

| 步骤 | 工作 | 文件 | LOC |
|---|---|---|---|
| 1 | `<Sparkline>` + 单测 | `components/shared/Sparkline.tsx`, tests | ~80 |
| 2 | `<MobileTopbar>` + 单测 | `components/shared/MobileTopbar.tsx`, tests | ~80 |
| 3 | `<AppShell>` 加 `pageTitle` prop + 集成 MobileTopbar | `components/shared/AppShell.tsx` | ~15 |
| 4 | 11 个 island main entry 加 `pageTitle` | `islands/*/main.tsx` | ~30 |
| 5 | `<AccountOverviewCard>` 加 sparkline + hero className + props 扩展 + 单测 | `islands/dashboard/DashboardPage.tsx`, tests | ~40 |
| 6 | Analysis 页 `<AnalysisHomeInbox>` JSX 顺序对调（发起分析 → 分析记录） | `islands/analysis/AnalysisPage.tsx` | ~10 |
| 7 | Screener-v3 `<ScreenerHomeView>` JSX 顺序对调（form → recent） | `islands/screener-v3/ScreenerV3Page.tsx` | ~5 |
| 8 | 2 个 layout DOM 顺序单测 | tests | ~40 |
| 9 | Playwright 回归 + 手动回归 | — | — |
| **合计** | | | **~300 LOC** |

每步独立 commit。预估总工时 **~4h**。

---

## 8. 严格不动清单

- [`<LLMSwitcher>`](../../stock_trading_system/web/frontend/src/components/shared/LLMSwitcher.tsx) 实现（仅消费）
- 桌面 `<Sidebar>` 视觉
- 桌面 `lg:grid-cols-3` 净值曲线独立 Card
- 后端 API / 数据 schema / task type
- v1.3 已落地的 R-MUI-01..18 所有改动
- shadcn UI primitives
- TradingAgents / 数据层 / LLM / business logic

---

## 9. 风险

| 风险 | 影响 | 处理 |
|---|---|---|
| 顶栏 + 底部 tabbar 双 fixed 挤压 | 内容遮挡 | `<main>` 已有 `pb-16`，顶栏 sticky 不需额外 padding（sticky 占位不像 fixed） |
| LLMSwitcher 在窄屏顶栏溢出 | 视觉破 | LLMSwitcher 已是 chip 形态 + truncate；副标超长时 max-w-[200px] truncate |
| sparkline 在数据稀疏时拉伸 | 视觉差 | 阈值 5 个点起渲染 |
| 桌面端误显示移动顶栏 | 视觉冲突 | `md:hidden` 严格隔离，桌面端 0 视觉变化 |
| 副标文案散在 11 个 island | 维护成本 | 文案集中在各 island main.tsx，与路由就近；未来如增多可改 context 集中 |
| pageTitle prop 漏传 | 副标不显示但不报错 | 设计为可选 prop，缺失时仅品牌名（不破布局）|

---

*v1.3.1 设计稿 — 等待确认后开始实施*
