# 技术方案：UI React Island —— 剩余 11 页完整设计

| 项 | 值 |
|---|---|
| Feature | `ui-react-island-pages` |
| 版本 | v1.0 |
| 日期 | 2026-04-24 |
| 关联主方案 | [ui-react-island.md](./ui-react-island.md) v2.0 §15 |
| 关联 PRD | [../prd/ui-react-island.md](../prd/ui-react-island.md) |
| 关联测试 | [../test-cases/ui-react-island.md](../test-cases/ui-react-island.md) v2.0 |

## 1. 如何阅读本文档

主方案 [ui-react-island.md](./ui-react-island.md) 讲的是**架构**（Vite/Flask 管道、构建、4 首批页面）。本文档是**每页详细施工图**，涵盖剩余 11 页。

每页有 **10 个子节**，按同一模板编写：

1. **路由与入口**
2. **当前 Jinja 状态**（行号 + 槽点清单）
3. **UI 线框 mockup**
4. **数据模型**（TypeScript `interface`）
5. **页面状态机**（local state shape）
6. **组件树**
7. **后端 API 契约**（已有 + 新增）
8. **交互清单**（click / submit / hover / keyboard）
9. **空态 · 加载 · 错误 · 边界**
10. **移动端 + a11y**

## 2. 全局约定（所有页共用）

### 2.1 URL 命名

| 类型 | 规则 | 例 |
|---|---|---|
| 列表页 | `/resource`（复数）| `/portfolio`, `/alerts`, `/history` |
| 单个资源 | `/resource/<id>` | `/paper-trade/NVDA`, `/analysis/25`, `/backtest/17` |
| 表单触发 | `/resource/new` | `/alerts/new`, `/backtest/new`（或 Dialog 不改 URL，视情况）|
| 管理员 | `/admin/<sub>` | `/admin/invites`, `/admin/users` |

**与 Flask 路由 1:1**。React 不自己做路由，切换靠 `<a href>` 或 `window.location.href`。

### 2.2 AppShell 包裹

每页**必须**用 `<AppShell>` 包裹（统一 nav + sidebar + mobile tabbar + Toaster + 连接指示）。

```tsx
export function XxxPage() {
  // ...
  return (
    <AppShell>
      <PageContent />
    </AppShell>
  )
}
```

### 2.3 数据 fetch 三段式

所有页面数据获取统一四态：

```tsx
type LoadState<T> =
  | { status: "loading" }
  | { status: "error"; error: string; retry: () => void }
  | { status: "empty" }       // 服务器返回 200 但数据为空
  | { status: "ready"; data: T }
```

UI 对应：
- loading → `<Skeleton>`（500ms+ 才显示，避免闪）
- error → `<Alert variant="destructive">`（含 retry 按钮）
- empty → `<EmptyState>` 组件（图标 + 文案 + 主 CTA）
- ready → 正常内容

### 2.4 移动端统一断点

对齐 [mobile-optimization.md](./mobile-optimization.md) §2.1：

| 断点 | Tailwind | 典型调整 |
|---|---|---|
| ≤ 375px | 默认 | 单列，字号 clamp 最小 |
| ≤ 575.98px | 默认 | 表格→卡片，tab→横滑 chip |
| ≤ 767.98px | `md:` 前 | 栅格 1-2 列，侧栏收起 |
| ≥ 768px | `md:` | 桌面布局 |

所有交互元素 ≥ 44px 触摸目标（PRD §2.1 已约束）。

### 2.5 a11y 最低要求

- 所有可点元素必须 `role="button"` 或原生 `<button>`，有 `aria-label` 或可见文本
- 表单所有字段关联 `<label>` 或 `aria-label`
- 错误通过 `aria-describedby` 关联字段
- Tab 顺序合理
- Focus ring 必须可见（不抹 outline）
- 对比度 ≥ 4.5:1（暗色模式 CSS token 已满足）

---

## 3. 共享组件详细规格

v2.0 新增 7 个共享组件。每个组件都会在多页复用，必须先做。

### 3.1 `<AppShell>`

```tsx
interface AppShellProps {
  children: ReactNode
  sidebarHidden?: boolean   // 极简模式（auth 页用）
  maxWidth?: "default" | "wide" | "full"
  pageTitle?: string        // 覆盖 <title>
}
```

**结构**：

```
┌─────────────────────── viewport ──────────────────────────┐
│  <NavTopbar> (桌面可见) ─────────────────────────────────── │
│  - Logo / breadcrumb                                        │
│  - 全局搜索（⌘K 触发 Command）                               │
│  - Provider indicator（qwen/gemini）                        │
│  - User menu dropdown                                       │
├───────────┬───────────────────────────────────────────────┤
│ <Sidebar> │ <main> 页面主体                                │
│ 240 px    │   max-w-7xl mx-auto px-4 lg:px-8 py-6         │
│ 桌面可见   │   {children}                                   │
│           │                                                │
│           │                                                │
└───────────┴───────────────────────────────────────────────┘
  <MobileTabbar> (移动可见)
  <ConnectionIndicator> (右下角小徽章)
  <Toaster>
```

**职责**：
- 读取 `<meta name="user-id">` 决定是否渲染
- 维护 sidebar 折叠/展开状态（localStorage）
- 提供 `AppShellContext`（user, csrfToken, provider）给所有子组件
- 顶部 `⌘K` 全局 Command 绑定

**已有依赖**：Command（shadcn） / DropdownMenu / Toaster / Sheet（移动 sidebar）。

### 3.2 `<DataTable>`

基于 **`@tanstack/react-table`**。

```tsx
interface DataTableProps<T> {
  data: T[]
  columns: ColumnDef<T>[]
  // 过滤
  searchable?: { key: keyof T; placeholder: string }
  filterBar?: ReactNode
  // 排序
  defaultSort?: { key: keyof T; desc: boolean }
  // 分页
  pageSize?: number
  // 空态
  empty?: {
    title: string
    description?: string
    action?: { label: string; onClick: () => void }
  }
  // 移动端卡片渲染（≤575.98px）
  mobileCard?: (row: T) => ReactNode
  // 行点击（整行可点）
  onRowClick?: (row: T) => void
  // 行操作
  rowActions?: (row: T) => Array<{ label: string; onClick: () => void; destructive?: boolean }>
  // 选择
  selectable?: boolean
  onSelectionChange?: (rows: T[]) => void
}
```

**渲染逻辑**：
- 桌面（≥768px）：标准 `<table>`
- 平板（576-767.98px）：`<table>` + 隐藏次要列（`meta.mobilePriority: "low"`）
- 移动（≤575.98px）：若 `mobileCard` 提供则用卡片视图，否则横向滚动

**行内操作**：`rowActions` 渲染为行末 `<DropdownMenu>`。

### 3.3 `<Form>` 系列

基于 **`react-hook-form` + `zod`**。shadcn 官方有完整 `form.tsx` 模板，直接 copy。

```tsx
// 用法示例（预警规则）
const schema = z.object({
  ticker: z.string().min(1, "必填"),
  condition: z.enum(["price_above", "price_below", "volume_spike"]),
  threshold: z.number().positive("必须正数"),
  notify: z.object({
    in_app: z.boolean().default(true),
    email: z.boolean().default(false),
    telegram: z.boolean().default(false),
  }),
})

const form = useForm<z.infer<typeof schema>>({
  resolver: zodResolver(schema),
  defaultValues: { ticker: "", condition: "price_above", threshold: 0, notify: {...} },
})

<Form {...form}>
  <form onSubmit={form.handleSubmit(onSubmit)}>
    <FormField name="ticker" render={({ field }) => (
      <FormItem>
        <FormLabel>股票代码</FormLabel>
        <FormControl><Input {...field} /></FormControl>
        <FormMessage />
      </FormItem>
    )} />
    ...
    <Button type="submit" disabled={form.formState.isSubmitting}>保存</Button>
  </form>
</Form>
```

**约定**：
- 所有表单页 **必须** 用 `<Form>` + zod schema，不允许裸 `useState`
- schema 与后端 Pydantic 字段对齐（名字一致）
- 提交失败时 `toast.error(error.message)` + 保留用户输入（不 reset）

### 3.4 `<EChartsPanel>`

```tsx
interface EChartsPanelProps {
  option: echarts.EChartsOption
  height?: number                    // 默认 320
  loading?: boolean
  onReady?: (chart: echarts.ECharts) => void
  className?: string
}
```

**Tree-shake** 按需导入：

```tsx
// lib/echarts.ts
import * as echarts from "echarts/core"
import { LineChart, BarChart, ScatterChart, PieChart } from "echarts/charts"
import {
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkPointComponent, MarkLineComponent,
  MarkAreaComponent, VisualMapComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"

echarts.use([
  LineChart, BarChart, ScatterChart, PieChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkPointComponent, MarkLineComponent,
  MarkAreaComponent, VisualMapComponent,
  CanvasRenderer,
])

export { echarts }
```

### 3.5 `<AuthCard>`

```tsx
interface AuthCardProps {
  title: string
  description?: string
  children: ReactNode         // form
  footer?: ReactNode          // 其他跳转链接
}
```

布局：居中、最大宽 420px、背景微渐变、Logo 置顶。

### 3.6 `<SettingsTabs>`

Apple System Preferences 风：

```tsx
interface SettingsTabsProps {
  sections: Array<{
    id: string
    label: string
    icon: ReactNode
    items: Array<{
      id: string
      label: string
      component: ReactNode   // lazy-loadable
      adminOnly?: boolean
    }>
  }>
  defaultItemId?: string
}
```

- 桌面：左侧 220px 垂直导航 + 右侧内容区
- 移动（≤768px）：折叠为顶部 `<Select>` 选择当前 item

### 3.7 `<FilterBar>`

```tsx
interface FilterBarProps {
  search?: { value: string; onChange: (v: string) => void; placeholder?: string }
  chips?: Array<{
    key: string
    label: string
    active: boolean
    onClick: () => void
  }>
  dateRange?: { from: Date | null; to: Date | null; onChange: (range: {from, to}) => void }
  actions?: ReactNode    // 右侧按钮（新建、导出）
}
```

移动端：`search` 占一整行，chips 横滑（`.chip-row`），actions 下沉到次行。

---

## 4. 数据列表页（P0）

### 4.1 Portfolio · 持仓管理

#### 4.1.1 路由与入口

- **URL**：`/portfolio`
- **Flask 路由**：`@app.route("/portfolio")` → `render_template("islands/portfolio.html")`
- **React entry**：`src/islands/portfolio/main.tsx`
- **侧边栏 active**：`/portfolio`

#### 4.1.2 当前 Jinja 状态

[index.html:562-677](../../stock_trading_system/web/templates/index.html) 槽点：
- 表单 `col-6 col-md-4` × 4 栏在 375px 挤到 90px（已被 [paper-trade v1.3](./paper-trade.md) 诊断）
- 持仓列表是 Bootstrap `<table class="table">`，移动端横向滚动
- 买入 / 卖出是两个独立表单块，视觉重复
- 盈亏用红绿色但无 icon + 对比度不足
- 无 stat 卡（总值 / 今日 PnL / 胜率）

#### 4.1.3 UI mockup

**桌面（≥1024px）**：

```
┌─ AppShell ──────────────────────────────────────────────────┐
│                                                              │
│  持仓管理                                     [⋯ 导出] [+ 买入]│
│                                                              │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │ 总值     │ │ 今日 PnL │ │ 胜率     │ │ 持仓数  │           │
│  │ $100,17  │ │ +$1,417  │ │ 68.4%    │ │ 8 只    │           │
│  │ +1.41%   │ │ +1.41%   │ │ 近 30 天 │ │         │           │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘           │
│                                                              │
│  [搜索...] [市场▾] [排序▾]                       [+ 买入]    │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ ★ 代码 名称    持仓    成本     现价    盈亏    信号  ⋯  ││
│  │ ─ NVDA NVIDIA  62.86   198.87   201.68  +1.41% [BUY]  ⋯ ││
│  │ ─ AAPL Apple   30      210.12   234.22  +11.47%[HOLD] ⋯ ││
│  │ ...                                                       ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  ┌─ 近 30 天净值 ──────────────────────────────────────────┐│
│  │ [ECharts area chart + drawdown markArea]                 ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

**移动（≤575.98px）**：

```
┌─ AppShell ─────────────────────┐
│ 持仓管理              [+ 买入]  │
│                                 │
│  ┌──────┐ ┌──────┐            │
│  │ 总值 │ │ PnL  │            │
│  │ ...  │ │ ...  │            │
│  └──────┘ └──────┘            │
│  ┌──────┐ ┌──────┐            │
│  │ 胜率 │ │ 持仓数│            │
│  └──────┘ └──────┘            │
│                                 │
│  [搜索...]                      │
│  [美股][A股][港股]  (chip 横滑) │
│                                 │
│  ┌─ NVDA ─────────────────┐   │
│  │ NVIDIA · 62.86 股       │   │
│  │ $198.87 → $201.68       │   │
│  │ +1.41%      [BUY] ⋯     │   │
│  └────────────────────────┘   │
│  ┌─ AAPL ─────────────────┐   │
│  │ ...                      │   │
│  └────────────────────────┘   │
└────────────────────────────────┘
```

#### 4.1.4 数据模型

```ts
export interface Holding {
  ticker: string
  name: string
  market: "US" | "CN" | "HK"
  shares: number
  avg_cost: number
  current_price: number
  market_value: number
  pnl: number              // 绝对值
  pnl_pct: number          // 百分比
  signal: "buy" | "sell" | "hold" | null   // 最新 AI 信号
  added_date: string       // ISO
  bookmarked: boolean
}

export interface PortfolioSummary {
  total_value: number
  today_pnl: number
  today_pnl_pct: number
  win_rate_30d: number
  holdings_count: number
}

export interface PortfolioHistoryPoint {
  date: string
  total_value: number
  drawdown_pct: number     // 负数
}
```

#### 4.1.5 页面状态机

```ts
interface PortfolioPageState {
  summary: LoadState<PortfolioSummary>
  holdings: LoadState<Holding[]>
  history: LoadState<PortfolioHistoryPoint[]>

  // UI local
  filter: {
    search: string
    market: "all" | "US" | "CN" | "HK"
    sort: { key: keyof Holding; desc: boolean }
  }
  buyDialogOpen: boolean
  sellDialogOpen: boolean
  sellTarget: Holding | null
}
```

#### 4.1.6 组件树

```
<PortfolioPage>
  <AppShell>
    <PageHeader title="持仓管理" actions={<BuyButton />} />
    <StatGrid>
      <Stat label="总值" value={...} delta={...} />
      <Stat label="今日 PnL" ... />
      <Stat label="胜率" ... />
      <Stat label="持仓数" ... />
    </StatGrid>

    <Card>
      <FilterBar search={{...}} chips={[markets]} actions={<BuyButton />} />
      <DataTable
        data={holdings}
        columns={holdingColumns}
        searchable={{ key: "ticker" }}
        mobileCard={row => <HoldingMobileCard row={row} />}
        rowActions={row => [
          { label: "分析", onClick: () => goto(`/analysis?ticker=${row.ticker}`) },
          { label: "加仓", onClick: () => openBuyDialog(row.ticker) },
          { label: "卖出", onClick: () => openSellDialog(row) },
          { label: "移除", destructive: true, onClick: () => confirmRemove(row) },
        ]}
      />
    </Card>

    <Card>
      <CardHeader>近 30 天净值</CardHeader>
      <CardContent><EChartsPanel option={buildEquityOption(history)} /></CardContent>
    </Card>

    <BuyDialog open={buyDialogOpen} onClose={...} />
    <SellDialog open={sellDialogOpen} holding={sellTarget} onClose={...} />
  </AppShell>
</PortfolioPage>
```

#### 4.1.7 后端 API 契约

| Method | Path | 用途 | 现状 |
|---|---|---|---|
| GET | `/api/portfolio/holdings` | 列表 | ✅ 已有 |
| GET | `/api/portfolio/pnl?days=1` | 今日盈亏 + 胜率 | ✅ 已有 |
| GET | `/api/portfolio/history?days=30` | 净值曲线 | ✅ 已有 |
| GET | `/api/portfolio/summary` | 聚合 4 stat | **🆕 新增**（替代 3 个独立查询，减少 RTT）|
| POST | `/api/portfolio/add` | 买入 | ✅ 已有 |
| POST | `/api/portfolio/sell` | 卖出 | ✅ 已有 |
| DELETE | `/api/portfolio/<ticker>` | 移除 | **🆕 新增** |

**新增 `/api/portfolio/summary`**（后端 ~30 LOC）：

```python
@app.route("/api/portfolio/summary")
@login_required
def portfolio_summary():
    user_id = g.user.id
    total = portfolio_db.get_total_value(user_id)
    today = portfolio_db.get_today_pnl(user_id)
    win_rate = portfolio_db.get_win_rate(user_id, days=30)
    count = portfolio_db.get_holdings_count(user_id)
    return jsonify({
        "total_value": total,
        "today_pnl": today["value"],
        "today_pnl_pct": today["pct"],
        "win_rate_30d": win_rate,
        "holdings_count": count,
    })
```

#### 4.1.8 交互清单

| 触发 | 动作 |
|---|---|
| 点 [+ 买入] | 打开 `<BuyDialog>` |
| [+ 买入] Dialog 提交 | `POST /api/portfolio/add` → 成功 toast + 关闭 + refetch holdings + summary |
| 行点击 | 跳 `/analysis?ticker=<x>` |
| 行末 ⋯ → 分析 | 同上 |
| 行末 ⋯ → 加仓 | 打开 BuyDialog 预填 ticker |
| 行末 ⋯ → 卖出 | 打开 SellDialog |
| 行末 ⋯ → 移除 | 二次确认 Dialog → `DELETE /api/portfolio/<ticker>` |
| ★ 切换 | `POST /api/portfolio/bookmark` / `DELETE` |
| 搜索框输入 | 本地过滤（< 500 行无需后端）|
| 市场 chip 切换 | 本地过滤 |
| 排序列点击 | 本地排序（tanstack-table 原生） |
| 数据过期（> 60s） | 后台 refetch |
| 创建买入任务成功 | toast.success + 动画高亮新行 |

#### 4.1.9 空态 · 加载 · 错误 · 边界

| 状态 | UI |
|---|---|
| 初始 loading | 4 个 stat `<Skeleton>` + DataTable `<Skeleton>` 行 ×5 |
| 空持仓 | `<EmptyState icon="📊" title="还没有持仓" description="点右上角添加第一笔买入" action={买入} />` |
| 网络错误 | `<Alert variant="destructive">加载持仓失败 [重试]</Alert>` |
| 买入失败 | 表单 inline error + toast |
| 余额不足（未来可能）| 买入 Dialog 显示 `<Alert variant="warning">` |
| 价格失效（某 ticker 数据 stale > 5min）| 行 badge 显示 "报价延迟" |

#### 4.1.10 移动端 + a11y

- 持仓 DataTable ≤575.98px 切 `mobileCard`
- stat 卡 375px 强制 2x2 grid
- [+ 买入] 移动端浮动在右下角（FAB）
- DataTable 行内操作 `⋯` 在移动端用 Sheet（而非 DropdownMenu）
- 所有金额 `font-mono tabular-nums` 保证对齐
- 股票代码 `<span lang="en">` 防中文 CJK 字距影响

---

### 4.2 History · 分析记录

#### 4.2.1 路由与入口

- **URL**：`/history`
- **React entry**：`src/islands/history/main.tsx`

#### 4.2.2 当前 Jinja 状态

[index.html:438-462](../../stock_trading_system/web/templates/index.html) 槽点：
- 搜索 + button 在 375px col-8/col-4 比例怪（参见 [mobile-optimization §4.3](./mobile-optimization.md)）
- 无 bookmark 功能（multi-tenant 已实装后端）
- 仅按日期排序

#### 4.2.3 UI mockup（卡片流）

```
┌─ 分析记录 ─────────────────────────────────────────────┐
│                                                         │
│  [搜索 ticker / 核心论点]                                │
│  [我的 | 全部]  [信号▾] [Provider▾] [近 7 天▾]          │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ★ NVDA  BUY  2026-04-19 22:26  · alice · Qwen   │  │
│  │   核心论点：AI 基础设施周期上行, Blackwell...    │  │
│  │   Buffett · Munger · Wood · Druckenmiller       │  │
│  │   置信度 85%  分数 88                             │  │
│  │                            [查看详情] [再次分析] │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ☆ AAPL  HOLD  2026-04-18  · bob · Gemini         │  │
│  │   ...                                              │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  [加载更多]                                             │
└─────────────────────────────────────────────────────────┘
```

#### 4.2.4 数据模型

```ts
export interface AnalysisRecord {
  id: number
  ticker: string
  created_at: string           // ISO
  signal: "buy" | "sell" | "hold" | null
  confidence: number | null
  score: number | null
  executive_summary: string    // v1.3 新增字段
  gurus: string[]              // e.g. ["buffett", "munger"]
  provider: "qwen" | "gemini"
  creator_display: string      // 触发者
  creator_id: number
  bookmarked: boolean
}

export interface HistoryFilters {
  search: string
  scope: "my" | "all"
  signal: "buy" | "sell" | "hold" | "all"
  provider: "qwen" | "gemini" | "all"
  dateRange: "today" | "7d" | "30d" | "all"
}
```

#### 4.2.5 状态机

```ts
interface HistoryPageState {
  filters: HistoryFilters
  records: LoadState<AnalysisRecord[]>
  pagination: { offset: number; hasMore: boolean }
}
```

#### 4.2.6 组件树

```
<HistoryPage>
  <AppShell>
    <PageHeader title="分析记录" />
    <FilterBar
      search={{ ... }}
      chips={[scope tabs, signal chips, provider chips, date chips]}
    />
    <div className="space-y-3">
      {records.data.map(r => <AnalysisRecordCard record={r} />)}
    </div>
    {hasMore && <Button onClick={loadMore}>加载更多</Button>}
  </AppShell>
</HistoryPage>

<AnalysisRecordCard>:
  - ★ toggle（调 bookmark API）
  - 主点击区跳 /analysis/<id>
  - 底部 [查看详情] / [再次分析] buttons
  - provider badge
```

#### 4.2.7 后端 API 契约

| Method | Path | 状态 |
|---|---|---|
| GET | `/api/analysis/history?scope=my\|all&signal=&provider=&days=&limit=&offset=` | 可能需扩展 query 参数 |
| POST | `/api/analysis/bookmarks` `{analysis_id}` | ✅ [multi-tenant](./multi-tenant.md) v1.0 |
| DELETE | `/api/analysis/bookmarks/<analysis_id>` | 同上 |
| POST | `/api/analyze` | 再次分析 |

#### 4.2.8 交互清单

| 触发 | 动作 |
|---|---|
| search 输入 | 本地过滤（已拉取的）+ debounced 500ms 后重新 fetch（若有更多数据） |
| scope/signal/provider/date chip | 重新 fetch（filters 变） |
| ★ 切换 | POST / DELETE bookmark |
| 行主体点击 | 跳 `/analysis/<id>` |
| [再次分析] | `POST /api/analyze?ticker=<x>` → 跳 `/tasks/<id>` |
| 滚动到底部 | 自动 loadMore（IntersectionObserver） |

#### 4.2.9 空态

- scope=my 空：`"还没有分析过股票，去 /analysis 触发第一次分析"`
- scope=all 空（新部署）：`"全站还没有分析记录"`
- 搜索无结果：`"没有匹配 \"xxx\" 的记录"`

#### 4.2.10 移动端 + a11y

- chips 横滑（`.tabs-scrollable` / `.chip-row`）
- 卡片全宽，点击整卡跳详情
- bookmark ★ 放在右上角，44×44 触摸区
- 虚拟滚动 `react-virtual`（data > 500 时考虑 v1.1）

---

### 4.3 Alerts · 预警中心

#### 4.3.1 路由与入口

- **URL**：`/alerts`
- **React entry**：`src/islands/alerts/main.tsx`

#### 4.3.2 当前 Jinja 状态

[index.html:687-758](../../stock_trading_system/web/templates/index.html) 槽点：
- 添加规则表单 4 字段挤一行（参见 [mobile-optimization §4.6](./mobile-optimization.md)）
- 规则 table 与历史 table 分开两大块，缺 Tab 切换
- 无统计数字（总规则、已触发、今日触发）

#### 4.3.3 UI mockup

```
┌─ 预警中心 ────────────────────────────────────────────┐
│                                                        │
│  ┌───────┐ ┌───────┐ ┌───────┐                       │
│  │ 运行  │ │ 今日  │ │ 本周  │                       │
│  │ 中 12 │ │ 触发3 │ │ 触发 18│                       │
│  └───────┘ └───────┘ └───────┘                       │
│                                                        │
│  [Tabs: 规则 | 历史]                [+ 新增规则]      │
│                                                        │
│  当前 Tab = 规则:                                      │
│  ┌────────────────────────────────────────────────────┐│
│  │ ticker 条件   阈值      启用      操作             ││
│  │ NVDA  ≥ 价格  $210      [●] 开    ⋯               ││
│  │ AAPL  ≤ 价格  $200      [○] 关    ⋯               ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│  当前 Tab = 历史:                                      │
│  ┌────────────────────────────────────────────────────┐│
│  │ 2026-04-22 10:30  NVDA  ≥ $210  实价 $211  已通知  ││
│  │ ...                                                 ││
│  └────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────┘
```

#### 4.3.4 数据模型

```ts
export interface AlertRule {
  id: number
  ticker: string
  condition: "price_above" | "price_below" | "volume_spike" | "rsi_overbought" | "rsi_oversold"
  threshold: number
  enabled: boolean
  notify: { in_app: boolean; email: boolean; telegram: boolean }
  created_at: string
  last_triggered_at: string | null
  trigger_count: number
}

export interface AlertTrigger {
  id: number
  rule_id: number
  ticker: string
  triggered_at: string
  actual_value: number
  threshold: number
  notified_channels: string[]
}

export interface AlertsSummary {
  active_rules: number
  triggers_today: number
  triggers_this_week: number
}
```

#### 4.3.5 组件树

```
<AlertsPage>
  <AppShell>
    <PageHeader title="预警中心" actions={<NewAlertButton />} />
    <StatGrid>
      <Stat ... />×3
    </StatGrid>

    <Tabs value={tab}>
      <TabsList>
        <TabsTrigger value="rules">规则 ({rules.length})</TabsTrigger>
        <TabsTrigger value="history">历史 ({triggers.length})</TabsTrigger>
      </TabsList>
      <TabsContent value="rules">
        <DataTable data={rules} columns={ruleColumns} ... />
      </TabsContent>
      <TabsContent value="history">
        <DataTable data={triggers} columns={triggerColumns} ... />
      </TabsContent>
    </Tabs>

    <NewAlertDialog open={...} onClose={...} />
  </AppShell>
</AlertsPage>

<NewAlertDialog>:
  <Form>
    <FormField ticker /> (带搜索下拉 Combobox)
    <FormField condition /> (Select)
    <FormField threshold /> (NumberInput)
    <FormField notify.in_app /> (Switch)
    <FormField notify.email />
    <FormField notify.telegram />
  </Form>
```

#### 4.3.6 后端 API 契约

| Method | Path | 状态 |
|---|---|---|
| GET | `/api/alerts/summary` | **🆕 新增** |
| GET | `/api/alerts/rules` | ✅ 已有（现 `/api/alerts`） |
| POST | `/api/alerts/rules` | ✅ 已有（现 `/api/alerts/add`） |
| PUT | `/api/alerts/rules/<id>` | 改启用态 |
| DELETE | `/api/alerts/rules/<id>` | 已有（`/api/alerts/remove`） |
| GET | `/api/alerts/history?days=7` | **🆕 新增**（当前没独立端点） |

#### 4.3.7 交互清单

| 触发 | 动作 |
|---|---|
| 启用 Switch 切换 | `PUT /api/alerts/rules/<id>` { enabled } |
| 行末 ⋯ → 编辑 | 打开 NewAlertDialog 预填 |
| 行末 ⋯ → 删除 | 确认 Dialog → DELETE |
| [+ 新增规则] | 打开 NewAlertDialog |
| 规则触发（SocketIO event `alert_triggered`）| toast.info + 更新 summary |

#### 4.3.8 空态

- 规则 Tab 空：`"还没有预警规则 [+ 创建第一条]"`
- 历史 Tab 空：`"还没有触发过预警"`

#### 4.3.9 移动端

- Tabs 用 `<TabsList>` 正常横向排列（3 项以内可以撑满）
- DataTable ≤575.98px 切 card 视图
- 新增规则 Dialog 在移动端全屏 Sheet

---

### 4.4 Reports · 报告中心

（结构与 Alerts 类似，从简，仅列关键差异）

#### 差异

- **核心功能**：生成周报/月报/持仓复盘（异步任务）
- **主要交互**：
  - 顶部生成表单：类型（周报 / 月报 / 持仓复盘） + 标的（可选） + 时段
  - 点"生成" → `POST /api/reports/generate` → task_id → 跳 `/tasks/<id>`
  - 列表展示已生成报告，每行 3 种导出格式（PDF / MD / HTML）
- **API**：
  - `GET /api/reports` 列表（已有）
  - `POST /api/reports/generate` （已有）
  - `GET /api/reports/<id>/download?format=pdf\|md\|html` （下载）
  - `DELETE /api/reports/<id>`

---

### 4.5 Paper-trade list · 会话列表

#### 4.5.1 路由

- **URL**：`/paper-trade`（无 ticker 参数时显示列表；带参数已在 v1.0 做完）

#### 4.5.2 UI mockup

```
┌─ 纸面交易 ────────────────────────────────────────────┐
│                                                        │
│  默认会话 ★                    [+ 新建会话]            │
│  ┌────────────────────────────────────────────────────┐│
│  │ 系统追踪 · 全量自动                                 ││
│  │ 总值 $100,176.62 · Sharpe 1.82 · 48 天            ││
│  │ [进入详情]                                          ││
│  └────────────────────────────────────────────────────┘│
│                                                        │
│  [搜索...]  [Tab: 我的 | 全部]                         │
│                                                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │ NVDA 回测     │ │ AAPL 周趋势   │ │ AI 信号实盘 │  │
│  │ PnL +5.2%     │ │ PnL -1.8%    │ │ PnL +12.4%   │  │
│  │ 8 trades      │ │ 3 trades     │ │ 25 trades    │  │
│  │ Sharpe 1.2    │ │ 失效         │ │ live         │  │
│  └──────────────┘ └──────────────┘ └──────────────┘  │
└────────────────────────────────────────────────────────┘
```

#### 4.5.3 数据模型

```ts
export interface PaperSession {
  id: number
  name: string
  mode: "replay" | "live" | "ticker"
  is_system: boolean      // 默认系统 session
  auto_track: boolean
  ticker: string | null
  metrics: { total_value: number; pnl_pct: number; sharpe: number; num_trades: number }
  status: "running" | "ended" | "failed"
  created_at: string
}
```

#### 4.5.4 组件树

```
<PaperListPage>
  <AppShell>
    <PageHeader title="纸面交易" actions={<NewSessionButton />} />
    <DefaultSessionCard session={defaultSession} />      // 置顶 + 特殊样式
    <FilterBar search chips={["我的","全部"]} />
    <Grid cols={3} responsive>
      {sessions.map(s => <SessionCard session={s} />)}
    </Grid>
  </AppShell>
</PaperListPage>

<SessionCard>:
  - ticker / date range / mode badge
  - PnL %, Sharpe, trades count
  - 状态徽章（live / ended / failed）
  - 整卡点击跳 /paper-trade/<ticker_or_session_id>
  - 右上角 ⋯ 菜单（重命名 / 删除 / 导出）
```

#### 4.5.5 API

| Method | Path | 状态 |
|---|---|---|
| GET | `/api/paper/sessions?scope=my` | ✅ 已有 |
| POST | `/api/paper/sessions` | 新建（已有） |
| PUT | `/api/paper/sessions/<id>` | 重命名 |
| DELETE | `/api/paper/sessions/<id>` | 删除（已有） |

---

## 5. 复杂详情页（P0）

### 5.1 Backtest · 策略回测

#### 5.1.1 路由

- `/backtest` —— 新建 / 历史 Tab
- `/backtest/<id>` —— 结果详情

#### 5.1.2 当前 Jinja 状态

[index.html:796-865](../../stock_trading_system/web/templates/index.html) 槽点：
- 5 字段参数表单 col-6 挤
- 日期 picker 移动键盘遮挡（[mobile-optimization §4.8](./mobile-optimization.md)）
- 历史回测没独立展示
- 结果 ECharts 裸渲染无响应式

#### 5.1.3 UI mockup —— 新建 tab

桌面左右 2 栏：

```
┌─ 策略回测 ──────────────────────────────────────────────┐
│  [Tab: 新建 | 历史]                                       │
│                                                           │
│  新建 Tab:                                                │
│  ┌─ 左 40% ──────────┐ ┌─ 右 60% ─────────────────────┐ │
│  │ 基础参数           │ │ 即时预览                       │ │
│  │                    │ │                               │ │
│  │ 标的: [NVDA]       │ │ ┌─ mini 曲线 ─────────────┐ │ │
│  │ 区间: [3 个月▾]    │ │ │ [ECharts 小图]           │ │ │
│  │ 初始: [$10000]     │ │ │                          │ │ │
│  │                    │ │ └──────────────────────────┘ │ │
│  │ 策略: [买入持有▾]  │ │                               │ │
│  │ 参数:              │ │ 样本期 Sharpe: 1.42           │ │
│  │   - 买入信号条件    │ │ 胜率: 62%                     │ │
│  │   [+ 添加参数组合] │ │ 最大回撤: -8.3%                │ │
│  │                    │ │                               │ │
│  │ 预估              │ │                               │ │
│  │ LLM calls: 0      │ │                               │ │
│  │ 时长: ~30s        │ │                               │ │
│  │ 成本: 免费         │ │                               │ │
│  │                    │ │                               │ │
│  │ [开始回测]        │ │                               │ │
│  └────────────────────┘ └───────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

#### 5.1.4 UI mockup —— 结果详情（`/backtest/<id>`）

```
┌─ 回测结果 #17 · NVDA · 2026-01-01 → 2026-04-01 ────────┐
│                                                          │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐                    │
│  │Shar│ │胜率│ │PnL │ │MDD │ │天数│                    │
│  │1.82│ │62% │ │+12%│ │-8% │ │90  │                    │
│  └────┘ └────┘ └────┘ └────┘ └────┘                    │
│                                                          │
│  ┌─ 权益曲线 ───────────────────────────────────────────┐│
│  │ [ECharts 大图: 净值 + drawdown markArea + 买卖点]    ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  [Tab: 交易明细 | 月度回报 | 风险指标 | 参数]            │
│  当前 Tab = 交易明细:                                    │
│  ┌──────────────────────────────────────────────────────┐│
│  │ 日期       动作  价格    股数   PnL   理由           ││
│  │ 2026-01-15 BUY   $145.20 100   —     入场             ││
│  │ 2026-02-20 ADD   $158.40 50    —     突破加仓         ││
│  │ ...                                                    ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  [再次运行] [导出 CSV] [分享]                            │
└──────────────────────────────────────────────────────────┘
```

#### 5.1.5 数据模型

```ts
export interface BacktestParams {
  ticker: string
  start_date: string
  end_date: string
  initial_capital: number
  strategy_id: string
  strategy_params: Record<string, unknown>
}

export interface BacktestResult {
  id: number
  params: BacktestParams
  metrics: {
    sharpe: number
    win_rate: number
    total_return_pct: number
    max_drawdown_pct: number
    total_trades: number
    avg_hold_days: number
  }
  equity_curve: Array<{ date: string; value: number; drawdown_pct: number }>
  trades: Array<{
    date: string
    action: "buy" | "sell" | "add" | "reduce"
    price: number
    shares: number
    pnl: number | null
    reason: string
  }>
  monthly_returns: Array<{ month: string; return_pct: number }>
  created_at: string
  user_id: number
}
```

#### 5.1.6 API

| Method | Path | 状态 |
|---|---|---|
| POST | `/api/backtest/estimate` | **🆕 新增**（quick sample run） |
| POST | `/api/backtest/run` | 已有 |
| GET | `/api/backtest` | 已有（列表） |
| GET | `/api/backtest/<id>` | 已有 |

#### 5.1.7 关键交互

- 参数任意变化 → 500ms debounce `POST /estimate` → 右侧预览 + Sharpe 数字
- [开始回测] → `POST /api/backtest/run` → task_id → 跳 `/tasks/<id>` → 完成后自动跳 `/backtest/<result_id>`
- [再次运行] → 预填参数回到 `/backtest?from=<id>`
- 权益曲线 hover → 显示当天交易动作 markPoint
- 交易明细行点击 → 在权益曲线上标记该交易位置

---

### 5.2 Analysis · AI 多 Agent 分析

#### 5.2.1 路由

- `/analysis` —— 触发表单 + 最近列表
- `/analysis/<id>` —— 单次分析的 8 tab 详情

#### 5.2.2 当前 Jinja 状态

[index.html:263-437](../../stock_trading_system/web/templates/index.html) 是全仓库最复杂的页，~170 行 HTML + 对应 app.js handler ~500 行。槽点：
- 7 报告 Tab 在 375px 装不下（[mobile-optimization §4.2](./mobile-optimization.md)）
- signal-value 40px 溢出
- trade_decision Markdown 是 innerHTML 塞入（XSS 风险）
- debate 展示散乱

#### 5.2.3 UI mockup —— 列表 `/analysis`

```
┌─ AI 分析 ──────────────────────────────────────────────┐
│                                                         │
│  ┌─ 新建分析 ─────────────────────────────────────────┐│
│  │ 股票: [NVDA  搜索]   日期: [2026-04-24 ▾]          ││
│  │ 深度: ⬤ 标准  ○ 快速  ○ 深度                       ││
│  │ [估算]                    [开始分析]                ││
│  └────────────────────────────────────────────────────┘│
│                                                         │
│  最近的分析（我的 + 他人）                              │
│  [已在 /history，此处仅展示最近 5 条快捷卡]             │
└─────────────────────────────────────────────────────────┘
```

#### 5.2.4 UI mockup —— 详情 `/analysis/<id>`

```
┌─ Analysis #25 · NVDA · 2026-04-19 22:26 · alice ───────┐
│                                                         │
│  [BUY]  信号置信度 85%                                  │
│  [⋯ 操作] [↗ 再次分析]                                  │
│                                                         │
│  ┌─ Executive Summary (高亮) ─────────────────────────┐│
│  │ 📝 AI 基础设施周期上行, Blackwell 交付加速释放... ││
│  └────────────────────────────────────────────────────┘│
│                                                         │
│  [Tabs 横滑（移动端）]                                   │
│  [概览] [市场] [情绪] [新闻] [基本面] [辩论] [风险] [决策]│
│                                                         │
│  Tab = 市场:                                            │
│  ┌────────────────────────────────────────────────────┐│
│  │ # 市场分析                                           ││
│  │                                                      ││
│  │ 关键指标表:                                          ││
│  │ - 20 日均线: $195.40                                ││
│  │ - RSI: 62                                            ││
│  │ - MACD: 金叉                                         ││
│  │                                                      ││
│  │ 技术分析原文（react-markdown 渲染）:                ││
│  │ > NVDA 当前处于...                                  ││
│  └────────────────────────────────────────────────────┘│
│                                                         │
│  Tab = 辩论:                                            │
│  ┌─ 牛方（Bull）─────────────────┐                     │
│  │ 🐂 核心论点: ...               │                     │
│  │ - 论据 1                        │                     │
│  │ - 论据 2                        │                     │
│  └────────────────────────────────┘                     │
│  ┌─ 熊方（Bear）─────────────────┐                     │
│  │ 🐻 核心论点: ...               │                     │
│  └────────────────────────────────┘                     │
│  ┌─ 裁判（Judge）─────────────────┐                     │
│  │ ⚖️  综合评判: ...              │                     │
│  └────────────────────────────────┘                     │
│                                                         │
│  底部:                                                   │
│  [↑ 加入持仓追踪] [导出 PDF] [分享链接]                  │
└─────────────────────────────────────────────────────────┘
```

#### 5.2.5 数据模型

```ts
export interface AnalysisDetail {
  id: number
  ticker: string
  date: string               // YYYY-MM-DD
  signal: "buy" | "sell" | "hold" | "error"
  confidence: number
  executive_summary: string  // v1.3

  // 8 个报告字段
  market_report: string      // Markdown
  sentiment_report: string
  news_report: string
  fundamentals_report: string
  investment_debate: {
    bull: { thesis: string; arguments: string[] }
    bear: { thesis: string; arguments: string[] }
    judge: { verdict: string; reasoning: string }
  }
  risk_assessment: {
    conservative: { thesis: string; reasoning: string }
    aggressive: { thesis: string; reasoning: string }
    neutral: { thesis: string; reasoning: string }
  }
  trade_decision: {
    action: string
    entry_low: number
    entry_high: number
    stop_loss: number
    take_profit: number
    position_pct: number
    reasoning: string
  }

  // 元数据
  provider: "qwen" | "gemini"
  duration_sec: number
  created_at: string
  creator_id: number
  creator_display: string
  bookmarked: boolean
}
```

#### 5.2.6 组件树

```
<AnalysisDetailPage>
  <AppShell>
    <PageHeader
      title={`Analysis #${id} · ${ticker}`}
      subtitle={`${createdAt} · ${creatorDisplay} · ${provider}`}
      actions={<OperationsMenu />}
    />
    <SignalBar signal={signal} confidence={confidence} />
    <ExecutiveSummaryCard summary={executive_summary} />

    <Tabs defaultValue="market">
      <TabsList className="tabs-scrollable">
        <TabsTrigger value="overview">概览</TabsTrigger>
        <TabsTrigger value="market">市场</TabsTrigger>
        <TabsTrigger value="sentiment">情绪</TabsTrigger>
        <TabsTrigger value="news">新闻</TabsTrigger>
        <TabsTrigger value="fundamentals">基本面</TabsTrigger>
        <TabsTrigger value="debate">辩论</TabsTrigger>
        <TabsTrigger value="risk">风险</TabsTrigger>
        <TabsTrigger value="decision">决策</TabsTrigger>
      </TabsList>
      <TabsContent value="market">
        <MarkdownRenderer source={market_report} />
      </TabsContent>
      <TabsContent value="debate">
        <DebateView debate={investment_debate} />
      </TabsContent>
      ...
    </Tabs>

    <FooterActions>
      <Button onClick={() => addToTracking()}>加入持仓追踪</Button>
      <Button onClick={() => exportPdf()}>导出 PDF</Button>
      <Button onClick={() => share()}>分享链接</Button>
    </FooterActions>
  </AppShell>
</AnalysisDetailPage>
```

#### 5.2.7 Markdown 渲染

用 `react-markdown` + `remark-gfm` + `rehype-sanitize`（安全渲染）：

```tsx
<ReactMarkdown
  remarkPlugins={[remarkGfm]}
  rehypePlugins={[rehypeSanitize]}
  components={{
    code: ({ className, children }) => (
      <code className="px-1.5 py-0.5 rounded bg-[var(--color-bg-secondary)] font-mono text-[12px] text-[var(--color-accent-blue)]">
        {children}
      </code>
    ),
    h1: ({ children }) => <h3 className="text-lg font-bold mt-6 mb-3">{children}</h3>,
    h2: ({ children }) => <h4 className="text-base font-semibold mt-5 mb-2">{children}</h4>,
    p:  ({ children }) => <p className="text-sm leading-relaxed mb-3">{children}</p>,
    // ...
  }}
>
  {market_report}
</ReactMarkdown>
```

#### 5.2.8 API

| Method | Path | 状态 |
|---|---|---|
| GET | `/api/analysis/<id>` | 已有（需验证返回全量字段） |
| POST | `/api/analyze` | 已有（触发） |
| POST | `/api/analysis/<id>/bookmark` | 已有（multi-tenant） |
| POST | `/api/analysis/<id>/track` | 加入 paper-trade 追踪 |
| GET | `/api/analysis/<id>/export?format=pdf\|md` | **🆕 新增**（生成异步任务） |

---

## 6. 表单驱动页（P1）

### 6.1 Settings · 设置

#### 6.1.1 路由

- `/settings`
- `/settings/<section>/<item>`（可选，深链）

#### 6.1.2 UI mockup（Apple SysPref 风）

桌面：

```
┌─ 设置 ────────────────────────────────────────────────┐
│  ┌─ 220px ─┐ ┌─ main ──────────────────────────────┐ │
│  │ 账号     │ │ [当前子页标题]                        │ │
│  │  · 资料 ★│ │                                      │ │
│  │  · 密码  │ │ 邮箱       admin@local               │ │
│  │ 集成     │ │ 显示名     Admin [编辑]               │ │
│  │  · LLM   │ │ 角色       管理员                     │ │
│  │  · 通知  │ │ 注册时间    2026-04-15                │ │
│  │ 系统     │ │ 最后登录    2026-04-24 10:00          │ │
│  │  · 邀请码│ │                                      │ │
│  │  · 数据  │ │ [修改密码]                            │ │
│  │ 高级     │ │                                      │ │
│  │  · 诊断  │ │                                      │ │
│  └──────────┘ └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

#### 6.1.3 子页清单

| Section | Item | 对应现有功能 | 组件 |
|---|---|---|---|
| 账号 | 个人资料 | `/api/auth/me` + `/api/auth/profile` PUT | Form |
| 账号 | 修改密码 | `/api/auth/change-password` | Form |
| 集成 | LLM Provider | model-switch v1.0 | Select + RadioGroup |
| 集成 | 通知 | email/telegram 配置 | Form |
| 系统 | 邀请码（admin 专属）| multi-tenant v1.0 | DataTable + Dialog |
| 系统 | 用户管理（admin 专属） | multi-tenant v1.0 | DataTable |
| 系统 | 数据导入 / 导出 | DB dump/restore | File upload + 异步 task |
| 系统 | 会话（本人登录历史）| 未实现 | DataTable |
| 高级 | 系统诊断 | 依赖状态 + 日志尾 | Accordion |
| 高级 | 清理缓存 | 调用清理 API | Button + 二次确认 |

#### 6.1.4 组件树

```
<SettingsPage>
  <AppShell>
    <SettingsTabs
      sections={[
        { id: "account", label: "账号", icon: <User />, items: [
          { id: "profile",  label: "个人资料", component: <ProfilePanel /> },
          { id: "password", label: "修改密码", component: <PasswordPanel /> },
        ]},
        { id: "integrations", label: "集成", icon: <Plug />, items: [
          { id: "llm", label: "LLM", component: <LLMPanel /> },
          { id: "notif", label: "通知", component: <NotifPanel /> },
        ]},
        { id: "system", label: "系统", icon: <Server />, items: [
          { id: "invites",   label: "邀请码", adminOnly: true, component: <InvitesPanel /> },
          { id: "users",     label: "用户", adminOnly: true, component: <UsersPanel /> },
          { id: "data",      label: "数据", component: <DataPanel /> },
        ]},
        { id: "advanced", label: "高级", icon: <Wrench />, items: [
          { id: "diagnostics", label: "诊断", component: <DiagnosticsPanel /> },
        ]},
      ]}
      defaultItemId="profile"
    />
  </AppShell>
</SettingsPage>
```

#### 6.1.5 深链

URL `/settings/account/password` 直接打开"修改密码"。

实现：`SettingsTabs` 读 `useEffect(() => activate(window.location.pathname))`。

---

## 7. 认证页（P1）

### 7.1 Login

#### 7.1.1 路由

`/login`（已存在 Jinja 版本 [login.html](../../stock_trading_system/web/templates/login.html)）

#### 7.1.2 UI mockup

```
┌──────────────── viewport ────────────────┐
│                                           │
│                                           │
│              [Logo 64x64]                │
│           StockAI Terminal               │
│                                           │
│      ┌───────────────────────────┐       │
│      │                            │       │
│      │   登录                     │       │
│      │   欢迎回来                 │       │
│      │                            │       │
│      │   邮箱                     │       │
│      │   [admin@local]            │       │
│      │                            │       │
│      │   密码                     │       │
│      │   [••••••••••]             │       │
│      │                            │       │
│      │   ☑ 保持登录 30 天         │       │
│      │                            │       │
│      │   [──────── 登录 ────────] │       │
│      │                            │       │
│      │   忘记密码? 联系管理员      │       │
│      │   没账号? 去注册 →         │       │
│      │                            │       │
│      └───────────────────────────┘       │
│                                           │
│       · zh-CN · v1.0 · /api/health ·     │
│                                           │
└───────────────────────────────────────────┘
```

#### 7.1.3 数据模型 + 校验

```ts
const loginSchema = z.object({
  email: z.string().email("邮箱格式不正确"),
  password: z.string().min(8, "密码至少 8 位"),
  remember: z.boolean().default(true),
})
```

#### 7.1.4 关键交互

- 回车 submit
- 登录失败 → 表单整体 shake 动画 + `toast.error` + 密码字段清空
- 登录成功 → `window.location.href = next || "/"`（next 从 URL query 读）
- [去注册] → `/register`

#### 7.1.5 组件树

```
<LoginPage>
  <AppShell sidebarHidden>
    <AuthCard title="登录" description="欢迎回来">
      <Form schema={loginSchema}>
        <FormField email />
        <FormField password />
        <FormField remember />
        <Button fullWidth loading={submitting}>登录</Button>
      </Form>
      <footer>
        <a href="/register">没账号? 去注册 →</a>
        <span>忘记密码? 联系管理员</span>
      </footer>
    </AuthCard>
  </AppShell>
</LoginPage>
```

### 7.2 Register

差异点：
- 多一个字段 `invite_code`，失焦时 debounce 调 `GET /api/invite/validate?code=<x>`
  - 有效 → 绿色 `✓ 有效，剩 X 次可用`
  - 无效 / 已用 / 过期 / 吊销 → 红色 + 具体原因
- 多一个字段 `display_name`（可选，不填默认邮箱前缀）
- 密码需两次输入 + 一致校验

### 7.3 Reset

URL 模式：`/reset?token=<uuid>`

进入时立即调 `GET /api/auth/reset/validate?token=<x>`：
- 成功 → 显示新密码表单
- 失败 → 显示错误 `<AuthCard>`（"链接无效或已过期，请联系管理员"）+ [返回登录] 按钮

---

## 8. 页面矩阵总览

| 页面 | URL | React entry | AppShell | 后端 API（新增标 🆕） | 依赖组件 | Phase |
|---|---|---|---|---|---|---|
| Portfolio | `/portfolio` | islands/portfolio | ✅ | `/api/portfolio/*` + 🆕 summary / DELETE | DataTable · Dialog · Stat · EChartsPanel | 10 |
| History | `/history` | islands/history | ✅ | `/api/analysis/history` + bookmarks | FilterBar · 虚拟滚动 | 11 |
| Alerts | `/alerts` | islands/alerts | ✅ | `/api/alerts/*` + 🆕 summary/history | Tabs · DataTable · Dialog · Form · Switch | 12 |
| Reports | `/reports` | islands/reports | ✅ | `/api/reports/*` | DataTable · Form · Dropdown | 13 |
| Backtest | `/backtest` · `/backtest/<id>` | islands/backtest | ✅ | `/api/backtest/*` + 🆕 estimate | Tabs · Form · EChartsPanel · DataTable | 14 |
| Paper list | `/paper-trade` | islands/paper-trade-list | ✅ | `/api/paper/sessions` | Card grid · FilterBar | 15 |
| Analysis list | `/analysis` | islands/analysis | ✅ | `/api/analyze` · `/api/analysis/recent` | Form · 最近卡片列表 | 16 |
| Analysis detail | `/analysis/<id>` | （同上 entry） | ✅ | `/api/analysis/<id>` · 🆕 export | Tabs · Markdown · DebateView | 16 |
| Settings | `/settings/<section>/<item>` | islands/settings | ✅ | 多个散端点 | SettingsTabs · Form · DataTable | 17 |
| Login | `/login` | islands/auth-login | ⚠ sidebarHidden | `/api/auth/login` | AuthCard · Form | 9 |
| Register | `/register` | islands/auth-register | ⚠ | `/api/auth/register` · `/api/invite/validate` | AuthCard · Form | 9 |
| Reset | `/reset?token=<x>` | islands/auth-reset | ⚠ | `/api/auth/reset/*` | AuthCard · Form | 9 |

## 9. 类型定义集中索引

所有页面共用的核心类型建议放在 `frontend/src/lib/types.ts`：

```ts
// ===== 通用 =====
export type LoadState<T> = ...    // §2.3
export interface User { id, display_name, email, role }
export interface CsrfTokenCtx { token: string }

// ===== Portfolio =====
export interface Holding { ... }        // §4.1.4
export interface PortfolioSummary { ... }

// ===== History / Analysis =====
export interface AnalysisRecord { ... } // §4.2.4
export interface AnalysisDetail { ... } // §5.2.5

// ===== Alerts =====
export interface AlertRule { ... }      // §4.3.4
export interface AlertTrigger { ... }

// ===== Paper =====
export interface PaperSession { ... }   // §4.5.3

// ===== Backtest =====
export interface BacktestParams { ... } // §5.1.5
export interface BacktestResult { ... }

// ===== Screener V3（v1.0 已定义，挪过来共享）=====
export interface Guru { ... }
export interface GuruSignal { ... }
export interface Estimate { ... }

// ===== Tasks =====
export interface Task { ... }
export interface TaskEventEnvelope<P = unknown> { ... }  // unified-progress
```

## 10. 新增后端端点汇总（跨所有页）

| 优先级 | Method | Path | 用途 | 产生页 |
|---|---|---|---|---|
| P0 | GET | `/api/portfolio/summary` | 聚合 4 stat | Portfolio |
| P0 | DELETE | `/api/portfolio/<ticker>` | 移除 | Portfolio |
| P0 | GET | `/api/alerts/summary` | 聚合 3 stat | Alerts |
| P0 | GET | `/api/alerts/history?days=7` | 触发历史独立端点 | Alerts |
| P0 | POST | `/api/backtest/estimate` | 快速预估 | Backtest |
| P1 | GET | `/api/analysis/<id>/export?format=` | PDF/MD 导出 | Analysis |
| P1 | GET | `/api/invite/validate?code=` | 注册时邀请码校验 | Register |
| P1 | GET | `/api/auth/reset/validate?token=` | 重置链接校验 | Reset |
| P1 | PUT | `/api/portfolio/<ticker>/bookmark` · DELETE | Portfolio 书签 | Portfolio |
| P2 | GET | `/api/analysis/recent?limit=5` | /analysis 首页的最近卡片 | Analysis |

后端新增共约 **10 个端点**，大部分是聚合或简单查询，单端点 ≤ 30 LOC。总工时 ~4h。

## 11. 复用 / Reuse 审计

遵循 [engineering-principles.md](../engineering-principles.md) L0→L4：

### L0 项目内复用

- v1.0 完成的 14 个 shadcn 组件 + `lib/api.ts` / `lib/socket.ts` / `ProgressStream`
- 所有现有后端 API（本文 §10 新增的 10 个端点是增量 + 聚合，不改现有）
- [mobile-optimization](./mobile-optimization.md) CSS tokens + 断点 + 组件
- [paper-trade](./paper-trade.md) v1.3 的 tier 响应式布局思路

### L1 依赖库（v2.0 新增）

| 库 | 用途 | 节省自写 |
|---|---|---|
| `@tanstack/react-table` | 所有 DataTable 页（Portfolio / History / Alerts / Reports / Backtest / Paper list） | ~800 LOC |
| `react-hook-form` + `zod` + `@hookform/resolvers` | 所有表单（~15 表单）| ~600 LOC |
| `react-markdown` + `remark-gfm` + `rehype-sanitize` | Analysis 详情 + AI 决策 | ~300 LOC |
| `react-day-picker`（可选）| DatePicker 组件 | ~200 LOC |
| `@tanstack/react-virtual`（可选 v1.1）| History 超长列表 | ~200 LOC |

### L2 思路参考

- [shadcn/ui recipes](https://ui.shadcn.com/docs) —— DataTable / Form / Command 范例直接 copy
- Apple System Preferences 风 Settings 布局
- Linear / Vercel 的 Auth 卡片风格

### L4 自写（业务特定）

| 组件 / 页 | 估 LOC |
|---|---|
| 7 个共享组件（AppShell / DataTable / Form / EChartsPanel / AuthCard / SettingsTabs / FilterBar）| ~900 |
| 11 个 page components | ~1800 |
| Settings 子 panels（10 个）| ~700 |
| 各页数据模型 types | ~200 |
| **小计** | **~3600 LOC** |

v2.0 总自写 **~3600 LOC**，shadcn copy + tanstack/hook-form 替代了约 **~2500 LOC** 的潜在自写。

## 12. 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-04-24 | 初版：11 页详细施工图（每页 10 子节：路由 / 当前状态 / mockup / 数据模型 / 状态机 / 组件树 / API / 交互 / 空态 / 移动端+a11y）+ 7 共享组件详规 + 10 个新增后端端点汇总 + 类型索引 + 复用审计 |
